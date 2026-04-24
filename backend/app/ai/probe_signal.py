"""Compute signal statistics from probe time-series for LLM pattern interpretation.

We compute the numbers here (variance, slope, irrigation response delta, cross-depth
divergence). The LLM receives a structured description and classifies patterns.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IrrigationEvent, Plot, Probe, ProbeDepth, ProbeReading, Sector
from app.models.sector_crop_profile import SectorCropProfile

# m³/m³ plausible VWC range
_VWC_MIN, _VWC_MAX = 0.01, 0.65
_ANALYSIS_HOURS = 72
_FLATLINE_STD = 0.003   # std dev below this → suspect flatline
_RESPONSE_THRESHOLD = 0.008  # min delta to count as an irrigation response


async def compute_probe_signal_stats(probe_id: str, db: AsyncSession) -> dict:
    """Return a JSON-serialisable signal statistics dict for the probe."""
    probe = await db.get(Probe, probe_id)
    if not probe:
        return {"error": "probe_not_found"}

    sector = await db.get(Sector, probe.sector_id)
    sector_name = sector.name if sector else probe.sector_id

    # Soil texture from plot
    soil_texture: str | None = None
    field_capacity: float | None = None
    wilting_point: float | None = None
    root_depth_cm: int | None = None
    if sector:
        plot = await db.get(Plot, sector.plot_id)
        if plot:
            soil_texture = plot.soil_texture
            field_capacity = plot.field_capacity
            wilting_point = plot.wilting_point
        # root depth from crop profile
        cp_result = await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == probe.sector_id)
        )
        cp = cp_result.scalar_one_or_none()
        if cp:
            rd = cp.root_depth_mature_m or cp.root_depth_young_m
            if rd:
                root_depth_cm = int(rd * 100)

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=_ANALYSIS_HOURS)

    # Irrigation events in window
    events_result = await db.execute(
        select(IrrigationEvent)
        .where(
            IrrigationEvent.sector_id == probe.sector_id,
            IrrigationEvent.start_time >= window_start,
        )
        .order_by(IrrigationEvent.start_time)
    )
    irrigation_events = events_result.scalars().all()
    last_event = max(irrigation_events, key=lambda e: e.start_time) if irrigation_events else None

    # Depths and readings
    depths_result = await db.execute(
        select(ProbeDepth).where(ProbeDepth.probe_id == probe_id).order_by(ProbeDepth.depth_cm)
    )
    depths = depths_result.scalars().all()

    depth_stats: list[dict] = []
    for pd in depths:
        readings_result = await db.execute(
            select(ProbeReading)
            .where(
                ProbeReading.probe_depth_id == pd.id,
                ProbeReading.timestamp >= window_start,
            )
            .order_by(ProbeReading.timestamp)
        )
        readings = readings_result.scalars().all()

        if not readings:
            depth_stats.append({"depth_cm": pd.depth_cm, "n_readings": 0, "status": "no_data_in_window"})
            continue

        # Extract usable VWC values
        vwc_series: list[tuple[datetime, float]] = []
        for r in readings:
            v = r.calibrated_value if r.calibrated_value is not None else r.raw_value
            if r.unit == "vwc_m3m3" and _VWC_MIN <= v <= _VWC_MAX:
                ts = r.timestamp.replace(tzinfo=UTC) if r.timestamp.tzinfo is None else r.timestamp
                vwc_series.append((ts, v))
            elif r.calibrated_value is not None and _VWC_MIN < r.calibrated_value <= _VWC_MAX:
                ts = r.timestamp.replace(tzinfo=UTC) if r.timestamp.tzinfo is None else r.timestamp
                vwc_series.append((ts, v))

        if not vwc_series:
            depth_stats.append({"depth_cm": pd.depth_cm, "n_readings": len(readings), "status": "no_vwc_available"})
            continue

        vals = [v for _, v in vwc_series]
        latest_vwc = vals[-1]
        vwc_std = statistics.stdev(vals) if len(vals) > 1 else 0.0

        # Contextualise flatline: near field capacity means stable because soil is
        # saturated/well-hydrated, not because the sensor is stuck.
        # Use configured FC if available, otherwise use a generic wet threshold (0.32).
        fc_threshold = (field_capacity * 0.90) if field_capacity else 0.32
        flatline_near_fc = latest_vwc >= fc_threshold

        # Slope over full window
        first_ts, first_v = vwc_series[0]
        last_ts, last_v = vwc_series[-1]
        elapsed_h = (last_ts - first_ts).total_seconds() / 3600
        slope = (last_v - first_v) / elapsed_h if elapsed_h > 0.5 else 0.0

        # 24h and 48h change
        change_24h = _delta_from(vwc_series, now - timedelta(hours=24), latest_vwc)
        change_48h = _delta_from(vwc_series, now - timedelta(hours=48), latest_vwc)

        # Post-irrigation response
        post_irrig_delta: float | None = None
        hours_to_peak: float | None = None
        if last_event is not None:
            evt_ts = last_event.start_time.replace(tzinfo=UTC) if last_event.start_time.tzinfo is None else last_event.start_time
            vwc_at_event = _nearest_value(vwc_series, evt_ts)
            post_window = [(t, v) for t, v in vwc_series if evt_ts <= t <= evt_ts + timedelta(hours=12)]
            if post_window and vwc_at_event is not None:
                peak_v = max(v for _, v in post_window)
                peak_t = next(t for t, v in post_window if v == peak_v)
                post_irrig_delta = round(peak_v - vwc_at_event, 4)
                hours_to_peak = round((peak_t - evt_ts).total_seconds() / 3600, 1)

        depth_stats.append({
            "depth_cm": pd.depth_cm,
            "n_readings": len(vwc_series),
            "latest_vwc": round(latest_vwc, 3),
            "vwc_min": round(min(vals), 3),
            "vwc_max": round(max(vals), 3),
            "variance_std": round(vwc_std, 4),
            "sinal_estavel": vwc_std < _FLATLINE_STD and len(vwc_series) >= 4,
            "causa_sinal_estavel": (
                "solo próximo da capacidade de campo, sem consumo nem drenagem activa"
                if vwc_std < _FLATLINE_STD and len(vwc_series) >= 4 and flatline_near_fc
                else "VWC estável em gama baixa ou média, verificar sensor"
                if vwc_std < _FLATLINE_STD and len(vwc_series) >= 4
                else None
            ),
            "slope_vwc_per_h": round(slope, 6),
            "change_last_24h": round(change_24h, 4) if change_24h is not None else None,
            "change_last_48h": round(change_48h, 4) if change_48h is not None else None,
            "post_irrigation_response_delta": post_irrig_delta,
            "hours_to_peak_after_irrigation": hours_to_peak,
        })

    # Cross-depth signals
    valid = [d for d in depth_stats if "latest_vwc" in d]
    cross_depth: dict = {}
    if len(valid) >= 2:
        shallowest = valid[0]
        deepest = valid[-1]
        cross_depth["shallowest_depth_cm"] = shallowest["depth_cm"]
        cross_depth["deepest_depth_cm"] = deepest["depth_cm"]
        cross_depth["shallowest_depletes_faster"] = (
            (shallowest.get("slope_vwc_per_h") or 0) < (deepest.get("slope_vwc_per_h") or 0)
        )
        cross_depth["vwc_divergence"] = round(
            abs(shallowest["latest_vwc"] - deepest["latest_vwc"]), 3
        )
        s_resp = shallowest.get("post_irrigation_response_delta")
        d_resp = deepest.get("post_irrigation_response_delta")
        if s_resp is not None and d_resp is not None:
            cross_depth["irrigation_reached_shallow"] = s_resp > _RESPONSE_THRESHOLD
            cross_depth["irrigation_reached_deep"] = d_resp > _RESPONSE_THRESHOLD
            cross_depth["irrigation_reached_shallow_not_deep"] = (
                s_resp > _RESPONSE_THRESHOLD and d_resp <= _RESPONSE_THRESHOLD
            )

    return {
        "probe_id": probe_id,
        "probe_external_id": probe.external_id,
        "sector_id": probe.sector_id,
        "sector_name": sector_name,
        "soil_texture": soil_texture,
        "field_capacity": field_capacity,
        "wilting_point": wilting_point,
        "root_depth_cm": root_depth_cm,
        "analysis_window_hours": _ANALYSIS_HOURS,
        "n_irrigation_events_in_window": len(irrigation_events),
        "last_irrigation_applied_mm": last_event.applied_mm if last_event else None,
        "depths": depth_stats,
        "cross_depth_signals": cross_depth,
    }


def _nearest_value(series: list[tuple[datetime, float]], target: datetime) -> float | None:
    """Return VWC nearest to target, accepting up to ±2 h."""
    if not series:
        return None
    closest = min(series, key=lambda x: abs((x[0] - target).total_seconds()))
    if abs((closest[0] - target).total_seconds()) <= 7200:
        return closest[1]
    return None


def _delta_from(series: list[tuple[datetime, float]], past: datetime, latest: float) -> float | None:
    v = _nearest_value(series, past)
    return round(latest - v, 4) if v is not None else None
