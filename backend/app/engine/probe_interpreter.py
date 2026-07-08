"""Probe readings interpreter.

Converts raw probe readings from the DB into a RootzoneStatus:
- Weighted average VWC over root-zone depths using depth-interval weighting
- Unit validation: only vwc_m3m3 readings feed into the water balance
- Data quality assessment per depth
- Staleness detection
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.staleness import PROBE_STALE_H
from app.engine.types import (
    DepthStatus,
    ProbeSnapshot,
    RootzoneStatus,
    SectorContext,
    TimestampedReading,
)
from app.models import Probe, ProbeDepth, ProbeReading

STALE_THRESHOLD_H = PROBE_STALE_H  # shared source of truth (see engine/staleness.py)
MAX_READINGS_PER_DEPTH = 48  # last 48h

# VWC plausible range (m³/m³)
_VWC_MIN = 0.0
_VWC_MAX = 0.65


async def interpret_probes(
    ctx: SectorContext,
    db: AsyncSession,
) -> ProbeSnapshot:
    """Load and interpret probe readings for the sector."""
    now = datetime.now(UTC)

    probe_result = await db.execute(
        select(Probe).where(Probe.sector_id == ctx.sector_id)
    )
    probes = probe_result.scalars().all()

    if not probes:
        return _empty_snapshot(ctx.sector_id, "no probes registered")

    all_depth_statuses: list[DepthStatus] = []
    anomalies: list[str] = []
    is_calibrated = True

    for probe in probes:
        depth_result = await db.execute(
            select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)
        )
        depths = depth_result.scalars().all()

        for pd in depths:
            readings_result = await db.execute(
                select(ProbeReading)
                .where(ProbeReading.probe_depth_id == pd.id)
                .order_by(ProbeReading.timestamp.desc())
                .limit(MAX_READINGS_PER_DEPTH)
            )
            readings = readings_result.scalars().all()

            if not readings:
                all_depth_statuses.append(DepthStatus(
                    depth_cm=pd.depth_cm,
                    readings=[],
                    latest_vwc=None,
                    hours_since_last=None,
                    quality="missing",
                ))
                continue

            latest = readings[0]
            hours_since = (
                now - (latest.timestamp.replace(tzinfo=UTC) if latest.timestamp.tzinfo is None
                       else latest.timestamp)
            ).total_seconds() / 3600

            tr_list = [
                TimestampedReading(
                    timestamp=r.timestamp,
                    value=r.calibrated_value if r.calibrated_value is not None else r.raw_value,
                    quality_flag=r.quality_flag,
                )
                for r in reversed(readings)
            ]

            # ── Unit check ──────────────────────────────────────────────────
            # Only values in m³/m³ are usable as VWC. For tension sensors
            # (soil_tension_cbar), the raw value is in cBar (0-200) which is
            # not VWC — using it as such would corrupt the water balance.
            # Accept the calibrated_value if it falls in the VWC plausible
            # range (user has set up a proper calibration).
            latest_vwc: float | None = None

            if latest.unit == "vwc_m3m3":
                v = latest.calibrated_value if latest.calibrated_value is not None else latest.raw_value
                latest_vwc = v if _VWC_MIN <= v <= _VWC_MAX else None
            elif (
                latest.calibrated_value is not None
                and _VWC_MIN < latest.calibrated_value <= _VWC_MAX
            ):
                # Non-VWC unit but calibrated_value is in VWC range — accept it
                latest_vwc = latest.calibrated_value
            else:
                # cBar or unknown unit with no valid VWC calibration
                is_calibrated = False
                anomalies.append(
                    f"Depth {pd.depth_cm}cm: readings in '{latest.unit}' — "
                    "VWC calibration needed (skipping from water balance)"
                )

            # ── Quality assessment ───────────────────────────────────────────
            quality = "ok"
            if latest_vwc is None and latest.unit != "vwc_m3m3":
                quality = "needs_vwc_calibration"
            elif hours_since > STALE_THRESHOLD_H:
                quality = "stale"
                anomalies.append(f"Depth {pd.depth_cm}cm: stale ({hours_since:.1f}h)")
            elif latest.quality_flag in ("suspect", "invalid"):
                quality = latest.quality_flag
                anomalies.append(f"Depth {pd.depth_cm}cm: {latest.quality_flag} reading")

            # Uncalibrated check (identity transform means no calibration applied)
            if latest.unit == "vwc_m3m3" and pd.calibration_factor == 1.0 and pd.calibration_offset == 0.0:
                is_calibrated = False

            all_depth_statuses.append(DepthStatus(
                depth_cm=pd.depth_cm,
                readings=tr_list,
                latest_vwc=latest_vwc,
                hours_since_last=round(hours_since, 1),
                quality=quality,
            ))

    rootzone = _compute_rootzone(all_depth_statuses, ctx.root_depth_m)

    return ProbeSnapshot(
        sector_id=ctx.sector_id,
        probe_ids=[p.id for p in probes],
        rootzone=rootzone,
        anomalies_detected=anomalies,
        is_calibrated=is_calibrated,
    )


def _depth_interval_weights(depths_cm: list[int], root_depth_cm: float) -> list[float]:
    """Layer thickness represented by each sensor depth (depth-interval method).

    Each sensor represents the soil layer from the midpoint to the shallower
    neighbour to the midpoint to the deeper neighbour (or 0 / root_depth_cm
    at the boundaries). This is more physically correct than inverse-depth
    weighting because it reflects the actual volume of soil being sampled.

    Example — sensors at 40cm and 60cm, root_depth 80cm:
      40cm → 0 to 50cm  (50cm thick)
      60cm → 50 to 80cm (30cm thick)
    """
    n = len(depths_cm)
    if n == 1:
        return [1.0]

    weights = []
    for i, d in enumerate(depths_cm):
        lower = 0.0 if i == 0 else (depths_cm[i - 1] + d) / 2.0
        if i == n - 1:
            # Extend the last sensor to root_depth (or half a step further)
            step = d - depths_cm[i - 1]
            upper = min(root_depth_cm, d + step / 2.0)
        else:
            upper = (d + depths_cm[i + 1]) / 2.0
        weights.append(max(0.0, upper - lower))

    return weights


def _compute_rootzone(depth_statuses: list[DepthStatus], root_depth_m: float) -> RootzoneStatus:
    """Depth-interval weighted average VWC for depths within the root zone."""
    root_depth_cm = root_depth_m * 100
    in_zone = [d for d in depth_statuses if d.depth_cm <= root_depth_cm]
    if not in_zone:
        in_zone = depth_statuses  # use all if none within root zone

    valid = [
        d for d in in_zone
        if d.latest_vwc is not None and d.quality not in ("missing", "needs_vwc_calibration")
    ]

    if not valid:
        hours = min(
            (d.hours_since_last for d in depth_statuses if d.hours_since_last is not None),
            default=None,
        )
        return RootzoneStatus(
            swc_current=None,
            swc_source="no_data",
            depth_statuses=depth_statuses,
            has_data=False,
            hours_since_any_reading=hours,
            all_depths_ok=False,
        )

    # Depth-interval weighting: sorted by depth, each sensor weighted by
    # the thickness of the soil layer it represents.
    valid.sort(key=lambda d: d.depth_cm)
    depths_cm = [d.depth_cm for d in valid]
    weights = _depth_interval_weights(depths_cm, root_depth_cm)

    total_weight = sum(weights)
    weighted_swc = sum(w * d.latest_vwc for w, d in zip(weights, valid))
    swc = weighted_swc / total_weight if total_weight > 0 else valid[0].latest_vwc

    hours_any = min(
        (d.hours_since_last for d in depth_statuses if d.hours_since_last is not None),
        default=None,
    )
    all_ok = all(d.quality == "ok" for d in depth_statuses)

    return RootzoneStatus(
        swc_current=round(swc, 4),
        swc_source="probe_weighted",
        depth_statuses=depth_statuses,
        has_data=True,
        hours_since_any_reading=hours_any,
        all_depths_ok=all_ok,
    )


def weighted_rootzone_series(
    series_by_depth: dict[int, list[tuple[datetime, float]]],
    root_depth_cm: float,
) -> list[tuple[datetime, float]]:
    """Rootzone-weighted VWC time series, for overlaying on the probe chart.

    Pure function: `series_by_depth` maps depth_cm -> [(timestamp, vwc), ...]
    (already deduped/merged upstream). Only depths within the root zone
    (`depth_cm <= root_depth_cm`) contribute; each contributing depth is weighted
    by `_depth_interval_weights` — the same depth-interval weighting
    `_compute_rootzone` uses for the engine's SWC — so this line can never
    diverge from the recommendation.

    At each timestamp, the average is renormalized over whichever in-zone depths
    actually have a reading at that timestamp (matching `_compute_rootzone`,
    which averages over `valid` with `total_weight`). Timestamps with no in-zone
    reading at all are skipped. Values are rounded to 4 decimal places. Results
    are sorted by timestamp.

    If no sensor falls within the root zone, this falls back to weighting ALL
    depths (still against `root_depth_cm`) — mirroring `_compute_rootzone`'s
    `if not in_zone: in_zone = depth_statuses` fallback, so the chart line can't
    silently vanish while the engine still produces an SWC.
    """
    in_zone_depths = sorted(d for d in series_by_depth if d <= root_depth_cm)
    if not in_zone_depths:
        in_zone_depths = sorted(series_by_depth)
    if not in_zone_depths:
        return []

    weights_by_depth = dict(
        zip(
            in_zone_depths,
            _depth_interval_weights(in_zone_depths, root_depth_cm),
            strict=True,
        )
    )

    # Group readings by timestamp across in-zone depths.
    by_ts: dict[datetime, dict[int, float]] = {}
    for depth_cm in in_zone_depths:
        for ts, vwc in series_by_depth.get(depth_cm, []):
            by_ts.setdefault(ts, {})[depth_cm] = vwc

    result: list[tuple[datetime, float]] = []
    for ts in sorted(by_ts):
        present = by_ts[ts]
        if not present:
            continue
        total_weight = sum(weights_by_depth[d] for d in present)
        if total_weight <= 0:
            continue
        weighted_sum = sum(weights_by_depth[d] * v for d, v in present.items())
        result.append((ts, round(weighted_sum / total_weight, 4)))

    return result


def _empty_snapshot(sector_id: str, reason: str) -> ProbeSnapshot:
    return ProbeSnapshot(
        sector_id=sector_id,
        probe_ids=[],
        rootzone=RootzoneStatus(
            swc_current=None,
            swc_source=reason,
            depth_statuses=[],
            has_data=False,
            hours_since_any_reading=None,
            all_depths_ok=False,
        ),
        anomalies_detected=[reason],
        is_calibrated=False,
    )
