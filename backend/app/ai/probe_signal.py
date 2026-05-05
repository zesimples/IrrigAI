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

        # Is this sensor depth beyond the configured root zone?
        # Roots don't consume at this depth → stable VWC is expected, not a fault.
        beyond_roots = root_depth_cm is not None and pd.depth_cm > root_depth_cm

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

        # Human-readable moisture level descriptor
        moisture_level = _moisture_level(latest_vwc, field_capacity, wilting_point)
        _latest_vwc_raw = latest_vwc  # kept internally for cross-depth divergence, stripped before return

        # Qualitative trend based on slope
        if abs(slope) < 0.0001:
            trend = "estável"
        elif slope < -0.001:
            trend = "a consumir rapidamente"
        elif slope < 0:
            trend = "a consumir gradualmente"
        elif slope > 0.001:
            trend = "a aumentar rapidamente (recarga)"
        else:
            trend = "a aumentar ligeiramente"

        depth_stats.append({
            "depth_cm": pd.depth_cm,
            "n_readings": len(vwc_series),
            "humidade_actual": moisture_level,
            "tendencia": trend,
            "sinal_estavel": vwc_std < _FLATLINE_STD and len(vwc_series) >= 4,
            "causa_sinal_estavel": (
                "solo próximo da capacidade de campo, sem consumo nem drenagem activa"
                if vwc_std < _FLATLINE_STD and len(vwc_series) >= 4 and flatline_near_fc
                else "profundidade além da zona radicular activa — sem consumo radicular nem drenagem, comportamento normal"
                if vwc_std < _FLATLINE_STD and len(vwc_series) >= 4 and beyond_roots
                else "humidade estável sem consumo nem recarga activos — equilíbrio hídrico"
                if vwc_std < _FLATLINE_STD and len(vwc_series) >= 4
                else None
            ),
            "profundidade_alem_raizes": beyond_roots if vwc_std < _FLATLINE_STD and len(vwc_series) >= 4 else None,
            "variabilidade_sinal": (
                "muito baixa (sinal plano)" if vwc_std < _FLATLINE_STD
                else "baixa" if vwc_std < 0.01
                else "moderada" if vwc_std < 0.03
                else "alta (sinal instável)"
            ),
            "variacao_24h": _delta_qualitative(change_24h),
            "variacao_48h": _delta_qualitative(change_48h),
            "resposta_rega": (
                "forte" if post_irrig_delta is not None and post_irrig_delta > 0.05
                else "moderada" if post_irrig_delta is not None and post_irrig_delta > _RESPONSE_THRESHOLD
                else "fraca ou ausente" if post_irrig_delta is not None
                else None
            ),
            "horas_ate_pico_apos_rega": hours_to_peak,
            "_latest_vwc_raw": _latest_vwc_raw,  # internal — stripped before LLM sees it
        })

    # Cross-depth signals
    valid = [d for d in depth_stats if "humidade_actual" in d]
    cross_depth: dict = {}
    if len(valid) >= 2:
        shallowest = valid[0]
        deepest = valid[-1]
        cross_depth["profundidade_rasa_cm"] = shallowest["depth_cm"]
        cross_depth["profundidade_funda_cm"] = deepest["depth_cm"]
        cross_depth["rasa_consome_mais_rapido"] = shallowest["tendencia"] in (
            "a consumir rapidamente", "a consumir gradualmente"
        ) and deepest["tendencia"] in ("estável", "a aumentar ligeiramente")
        cross_depth["divergencia_entre_profundidades"] = _divergence_label(
            _raw_vwc_lookup(depth_stats, shallowest["depth_cm"]),
            _raw_vwc_lookup(depth_stats, deepest["depth_cm"]),
        )
        s_resp = shallowest.get("resposta_rega")
        d_resp = deepest.get("resposta_rega")
        if s_resp is not None and d_resp is not None:
            cross_depth["rega_chegou_a_rasa"] = s_resp in ("forte", "moderada")
            cross_depth["rega_chegou_a_funda"] = d_resp in ("forte", "moderada")
            cross_depth["rega_so_na_rasa"] = (
                s_resp in ("forte", "moderada") and d_resp == "fraca ou ausente"
            )

    # Strip internal-only fields before returning to LLM
    for d in depth_stats:
        d.pop("_latest_vwc_raw", None)

    return {
        "probe_id": probe_id,
        "probe_external_id": probe.external_id,
        "sector_id": probe.sector_id,
        "sector_name": sector_name,
        "soil_texture": soil_texture,
        "root_depth_cm": root_depth_cm,
        "analysis_window_hours": _ANALYSIS_HOURS,
        "n_irrigation_events_in_window": len(irrigation_events),
        "last_irrigation_applied_mm": last_event.applied_mm if last_event else None,
        "depths": depth_stats,
        "cross_depth_signals": cross_depth,
    }


def _moisture_level(vwc: float, fc: float | None, wp: float | None) -> str:
    """Convert raw VWC to a qualitative moisture descriptor."""
    if fc and wp and fc > wp:
        ratio = (vwc - wp) / (fc - wp)
        if ratio >= 0.95:
            return "saturado / próximo da capacidade de campo"
        if ratio >= 0.70:
            return "humidade elevada"
        if ratio >= 0.45:
            return "humidade adequada"
        if ratio >= 0.20:
            return "humidade baixa"
        return "humidade crítica / próximo do ponto de murchamento"
    # Fallback: generic thresholds when FC/WP not configured
    if vwc >= 0.38:
        return "saturado / próximo da capacidade de campo"
    if vwc >= 0.28:
        return "humidade elevada"
    if vwc >= 0.20:
        return "humidade adequada"
    if vwc >= 0.12:
        return "humidade baixa"
    return "humidade crítica"


def _delta_qualitative(delta: float | None) -> str | None:
    if delta is None:
        return None
    if abs(delta) < 0.003:
        return "sem variação significativa"
    if delta < -0.03:
        return "descida acentuada"
    if delta < -0.01:
        return "descida moderada"
    if delta < 0:
        return "descida ligeira"
    if delta > 0.03:
        return "subida acentuada (rega ou chuva)"
    if delta > 0.01:
        return "subida moderada"
    return "subida ligeira"


def _divergence_label(vwc_a: float | None, vwc_b: float | None) -> str:
    if vwc_a is None or vwc_b is None:
        return "não determinada"
    diff = abs(vwc_a - vwc_b)
    if diff < 0.03:
        return "pequena (profundidades semelhantes)"
    if diff < 0.08:
        return "moderada"
    return "significativa (profundidades muito diferentes)"


def _raw_vwc_lookup(depth_stats: list[dict], depth_cm: int) -> float | None:
    """Retrieve the raw latest VWC for a depth (kept internally for divergence calc only)."""
    for d in depth_stats:
        if d.get("depth_cm") == depth_cm and "_latest_vwc_raw" in d:
            return d["_latest_vwc_raw"]
    return None


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
