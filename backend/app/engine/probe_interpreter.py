"""Probe readings interpreter.

Converts raw probe readings from the DB into a RootzoneStatus:
- Weighted average VWC over root-zone depths
- Data quality assessment per depth
- Staleness detection
"""

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.types import (
    DepthStatus,
    ProbeSnapshot,
    RootzoneStatus,
    SectorContext,
    TimestampedReading,
)
from app.models import Probe, ProbeDepth, ProbeReading

# Depth weights are computed dynamically using inverse-depth weighting
# so they work for any sensor configuration (olive 40/60cm, vineyard 20/40/60/80/100cm, etc.)
# Shallower depths represent the most active root zone and are weighted more.

STALE_THRESHOLD_H = 6.0
MAX_READINGS_PER_DEPTH = 48  # last 48h


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
            hours_since = (now - latest.timestamp.replace(tzinfo=UTC) if latest.timestamp.tzinfo is None
                           else now - latest.timestamp).total_seconds() / 3600

            tr_list = [
                TimestampedReading(
                    timestamp=r.timestamp,
                    value=r.calibrated_value if r.calibrated_value is not None else r.raw_value,
                    quality_flag=r.quality_flag,
                )
                for r in reversed(readings)
            ]

            # Quality assessment
            quality = "ok"
            if hours_since > STALE_THRESHOLD_H:
                quality = "stale"
                anomalies.append(f"Depth {pd.depth_cm}cm: stale ({hours_since:.1f}h)")
            elif latest.quality_flag in ("suspect", "invalid"):
                quality = latest.quality_flag
                anomalies.append(f"Depth {pd.depth_cm}cm: {latest.quality_flag} reading")

            # Check calibration
            if pd.calibration_factor == 1.0 and pd.calibration_offset == 0.0:
                is_calibrated = False

            latest_vwc = latest.calibrated_value if latest.calibrated_value is not None else latest.raw_value

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


def _compute_rootzone(depth_statuses: list[DepthStatus], root_depth_m: float) -> RootzoneStatus:
    """Weighted average VWC for depths within the root zone."""
    root_depth_cm = root_depth_m * 100
    in_zone = [d for d in depth_statuses if d.depth_cm <= root_depth_cm]
    if not in_zone:
        in_zone = depth_statuses  # use all if none within root zone

    valid = [d for d in in_zone if d.latest_vwc is not None and d.quality not in ("missing",)]
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

    # Inverse-depth weighting: shallower depths get higher weight.
    # w_i = 1 / depth_cm, normalised to sum to 1.
    total_weight = sum(1.0 / d.depth_cm for d in valid)
    weighted_swc = sum((1.0 / d.depth_cm) * d.latest_vwc for d in valid)
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
