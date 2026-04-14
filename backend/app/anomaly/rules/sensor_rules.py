"""Sensor anomaly detection rules.

Each rule takes a sorted list of (timestamp, vwc) tuples for a single probe depth
and returns a list of Anomaly objects.

Readings are assumed to be ordered by timestamp ascending.
"""

from datetime import UTC, datetime
from typing import NamedTuple

from app.anomaly.types import Anomaly

# Thresholds
FLATLINE_TOLERANCE = 0.001         # m³/m³ — values within this are "the same"
FLATLINE_WARN_N = 6                # consecutive readings → warning
FLATLINE_CRIT_N = 12               # consecutive readings → critical
JUMP_THRESHOLD = 0.15              # m³/m³ per hour
IMPOSSIBLE_LOW = 0.0
IMPOSSIBLE_HIGH = 0.55             # physical max for mineral soils
DEPTH_INCONSISTENCY_DELTA = 0.08   # shallow > deep by this much (m³/m³)
DEPTH_INCONSISTENCY_HOURS = 48     # must persist this long
SATURATION_PCT = 0.95              # fraction of FC
SATURATION_HOURS = 72
SUDDEN_DRY_DELTA = 0.10            # m³/m³ drop
SUDDEN_DRY_HOURS = 4


class Reading(NamedTuple):
    timestamp: datetime
    vwc: float


def detect_flatline(
    readings: list[Reading],
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
) -> list[Anomaly]:
    """Same VWC value (within ±0.001) for 6+ consecutive readings."""
    if len(readings) < FLATLINE_WARN_N:
        return []

    anomalies: list[Anomaly] = []
    run_start = 0
    run_len = 1

    for i in range(1, len(readings)):
        if abs(readings[i].vwc - readings[i - 1].vwc) <= FLATLINE_TOLERANCE:
            run_len += 1
        else:
            if run_len >= FLATLINE_WARN_N:
                anomalies.append(_make_flatline(
                    readings, run_start, run_len, sector_id, probe_id, depth_cm
                ))
            run_start = i
            run_len = 1

    # Check trailing run
    if run_len >= FLATLINE_WARN_N:
        anomalies.append(_make_flatline(
            readings, run_start, run_len, sector_id, probe_id, depth_cm
        ))

    return anomalies


def _make_flatline(
    readings: list[Reading],
    start: int,
    length: int,
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
) -> Anomaly:
    severity = "critical" if length >= FLATLINE_CRIT_N else "warning"
    value = readings[start].vwc
    first_ts = readings[start].timestamp
    last_ts = readings[start + length - 1].timestamp
    return Anomaly(
        anomaly_type="flatline",
        severity=severity,
        confidence=0.95,
        sector_id=sector_id,
        probe_id=probe_id,
        depth_cm=depth_cm,
        detected_at=last_ts,
        description_pt=(
            f"Sensor a {depth_cm}cm fixo em {value:.3f} m³/m³ durante {length} leituras "
            f"({first_ts:%Y-%m-%d %H:%M}–{last_ts:%Y-%m-%d %H:%M})"
        ),
        description_en=(
            f"Sensor at {depth_cm}cm stuck at {value:.3f} m³/m³ for {length} readings "
            f"({first_ts:%Y-%m-%d %H:%M}–{last_ts:%Y-%m-%d %H:%M})"
        ),
        likely_causes=(
            "Sensor malfunction",
            "Cable disconnect or short circuit",
            "Datalogger freeze / buffer not flushed",
        ),
        recommended_actions=(
            "Check physical sensor and cable connections",
            "Restart datalogger if accessible",
            "Compare with adjacent depths for context",
        ),
        data_context={
            "stuck_value": value,
            "run_length": length,
            "first_timestamp": first_ts.isoformat(),
            "last_timestamp": last_ts.isoformat(),
        },
    )


def detect_impossible_jump(
    readings: list[Reading],
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
) -> list[Anomaly]:
    """VWC change > 0.15 m³/m³ between consecutive hourly readings."""
    anomalies = []
    for i in range(1, len(readings)):
        prev, curr = readings[i - 1], readings[i]
        hours = max((curr.timestamp - prev.timestamp).total_seconds() / 3600, 0.1)
        rate = abs(curr.vwc - prev.vwc) / hours
        if rate > JUMP_THRESHOLD:
            delta = curr.vwc - prev.vwc
            anomalies.append(Anomaly(
                anomaly_type="impossible_jump",
                severity="warning",
                confidence=0.85,
                sector_id=sector_id,
                probe_id=probe_id,
                depth_cm=depth_cm,
                detected_at=curr.timestamp,
                description_pt=(
                    f"Variação impossível de {delta:+.3f} m³/m³ em {hours:.1f}h "
                    f"a {depth_cm}cm ({prev.timestamp:%H:%M}→{curr.timestamp:%H:%M})"
                ),
                description_en=(
                    f"Impossible jump of {delta:+.3f} m³/m³ in {hours:.1f}h "
                    f"at {depth_cm}cm ({prev.timestamp:%H:%M}→{curr.timestamp:%H:%M})"
                ),
                likely_causes=(
                    "Physical sensor disturbance or installation shift",
                    "Electrical interference or ground fault",
                    "Data transmission error",
                ),
                recommended_actions=(
                    "Compare with adjacent depths for context",
                    "Check for physical disturbance near probe",
                    "Inspect cable routing for interference sources",
                ),
                data_context={
                    "delta_vwc": round(delta, 4),
                    "rate_per_hour": round(rate, 4),
                    "from_ts": prev.timestamp.isoformat(),
                    "to_ts": curr.timestamp.isoformat(),
                    "from_vwc": prev.vwc,
                    "to_vwc": curr.vwc,
                },
            ))
    return anomalies


def detect_impossible_value(
    readings: list[Reading],
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
) -> list[Anomaly]:
    """VWC < 0 or > 0.55 — physically impossible for mineral soils."""
    anomalies = []
    for r in readings:
        if r.vwc < IMPOSSIBLE_LOW or r.vwc > IMPOSSIBLE_HIGH:
            direction = "below zero" if r.vwc < IMPOSSIBLE_LOW else "above physical max"
            anomalies.append(Anomaly(
                anomaly_type="impossible_value",
                severity="critical",
                confidence=1.0,
                sector_id=sector_id,
                probe_id=probe_id,
                depth_cm=depth_cm,
                detected_at=r.timestamp,
                description_pt=(
                    f"Valor impossível: {r.vwc:.4f} m³/m³ a {depth_cm}cm "
                    f"({r.timestamp:%Y-%m-%d %H:%M}) — fora dos limites físicos [0, 0.55]"
                ),
                description_en=(
                    f"Impossible value: {r.vwc:.4f} m³/m³ at {depth_cm}cm "
                    f"({r.timestamp:%Y-%m-%d %H:%M}) — {direction}, outside physical bounds [0, 0.55]"
                ),
                likely_causes=(
                    "Sensor failure or complete malfunction",
                    "Wrong calibration parameters applied",
                    "Air gap around sensor (soil cracking in clay)",
                ),
                recommended_actions=(
                    "Re-calibrate sensor using known soil moisture references",
                    "Inspect sensor for air gaps and re-seat if necessary",
                    "Replace sensor if re-calibration fails",
                ),
                data_context={
                    "value": r.vwc,
                    "timestamp": r.timestamp.isoformat(),
                    "bounds": [IMPOSSIBLE_LOW, IMPOSSIBLE_HIGH],
                },
            ))
    return anomalies


def detect_depth_inconsistency(
    shallow_readings: list[Reading],   # 10 cm
    deep_readings: list[Reading],      # 60 cm
    sector_id: str | None,
    probe_id: str | None,
) -> list[Anomaly]:
    """Shallow (10cm) consistently wetter than deep (60cm) by >0.08 m³/m³ for >48h."""
    if not shallow_readings or not deep_readings:
        return []

    # Build a time-aligned dict for the deep readings
    deep_by_ts = {r.timestamp: r.vwc for r in deep_readings}

    # Find windows where shallow > deep by threshold
    exceed_start: datetime | None = None
    exceed_count = 0

    anomalies: list[Anomaly] = []

    for s in shallow_readings:
        d_vwc = deep_by_ts.get(s.timestamp)
        if d_vwc is None:
            # Try nearest within 30 min
            close = [r for r in deep_readings if abs((r.timestamp - s.timestamp).total_seconds()) < 1800]
            d_vwc = close[0].vwc if close else None

        if d_vwc is not None and (s.vwc - d_vwc) > DEPTH_INCONSISTENCY_DELTA:
            if exceed_start is None:
                exceed_start = s.timestamp
            exceed_count += 1
        else:
            if exceed_start is not None:
                duration_h = (s.timestamp - exceed_start).total_seconds() / 3600
                if duration_h >= DEPTH_INCONSISTENCY_HOURS:
                    anomalies.append(_make_depth_inconsistency(
                        exceed_start, s.timestamp, exceed_count, sector_id, probe_id
                    ))
            exceed_start = None
            exceed_count = 0

    # Trailing window
    if exceed_start is not None and shallow_readings:
        last_ts = shallow_readings[-1].timestamp
        duration_h = (last_ts - exceed_start).total_seconds() / 3600
        if duration_h >= DEPTH_INCONSISTENCY_HOURS:
            anomalies.append(_make_depth_inconsistency(
                exceed_start, last_ts, exceed_count, sector_id, probe_id
            ))

    return anomalies


def _make_depth_inconsistency(
    start: datetime, end: datetime, count: int, sector_id: str | None, probe_id: str | None
) -> Anomaly:
    return Anomaly(
        anomaly_type="depth_inconsistency",
        severity="info",
        confidence=0.75,
        sector_id=sector_id,
        probe_id=probe_id,
        depth_cm=10,
        detected_at=end,
        description_pt=(
            f"Camada superficial (10cm) consistentemente mais húmida que a camada profunda (60cm) "
            f"em >{DEPTH_INCONSISTENCY_DELTA} m³/m³ durante {(end - start).total_seconds()/3600:.0f}h"
        ),
        description_en=(
            f"Shallow layer (10cm) consistently wetter than deep layer (60cm) "
            f"by >{DEPTH_INCONSISTENCY_DELTA} m³/m³ for {(end - start).total_seconds()/3600:.0f}h"
        ),
        likely_causes=(
            "Shallow probe calibration error",
            "Perched water table or impermeable layer",
            "Different soil texture across depths",
        ),
        recommended_actions=(
            "Verify probe calibration at 10cm against gravimetric sample",
            "Check for perched water table with auger",
            "Review soil profile log from installation",
        ),
        data_context={"start": start.isoformat(), "end": end.isoformat(), "readings_count": count},
    )


def detect_no_response_to_irrigation(
    readings: list[Reading],
    irrigation_start: datetime,
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
    response_window_h: float = 6.0,
    min_response_delta: float = 0.02,
) -> list[Anomaly]:
    """No VWC increase >0.02 at 10cm or 30cm within 6h of irrigation start."""
    if not readings:
        return []

    window_end = datetime.fromtimestamp(
        irrigation_start.timestamp() + response_window_h * 3600,
        tz=UTC,
    )
    before = [r for r in readings if r.timestamp <= irrigation_start]
    after = [r for r in readings if irrigation_start < r.timestamp <= window_end]

    if not before or not after:
        return []

    vwc_before = before[-1].vwc
    max_after = max(r.vwc for r in after)

    if (max_after - vwc_before) < min_response_delta:
        return [Anomaly(
            anomaly_type="no_response_to_irrigation",
            severity="warning",
            confidence=0.80,
            sector_id=sector_id,
            probe_id=probe_id,
            depth_cm=depth_cm,
            detected_at=after[-1].timestamp,
            description_pt=(
                f"Sem resposta de humidade a {depth_cm}cm nas {response_window_h:.0f}h após irrigação "
                f"(antes: {vwc_before:.3f}, máx. depois: {max_after:.3f} m³/m³)"
            ),
            description_en=(
                f"No moisture response at {depth_cm}cm within {response_window_h:.0f}h of irrigation "
                f"(before: {vwc_before:.3f}, max after: {max_after:.3f} m³/m³)"
            ),
            likely_causes=(
                "Emitter clog near probe",
                "Sector valve failure — water not reaching field",
                "Probe located outside the wetted zone",
                "Incorrect sector mapping in controller",
            ),
            recommended_actions=(
                "Inspect emitters closest to probe for blockage",
                "Verify sector valve opens during irrigation",
                "Check sector mapping in controller vs. field reality",
            ),
            data_context={
                "irrigation_start": irrigation_start.isoformat(),
                "vwc_before": vwc_before,
                "max_vwc_after": max_after,
                "delta": round(max_after - vwc_before, 4),
            },
        )]
    return []


def detect_persistent_saturation(
    readings: list[Reading],
    field_capacity: float,
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
) -> list[Anomaly]:
    """Deep sensor (60cm+) consistently >95% FC for >72h."""
    if not readings:
        return []

    threshold = field_capacity * SATURATION_PCT
    sat_start: datetime | None = None
    anomalies: list[Anomaly] = []

    for r in readings:
        if r.vwc >= threshold:
            if sat_start is None:
                sat_start = r.timestamp
        else:
            if sat_start is not None:
                duration_h = (r.timestamp - sat_start).total_seconds() / 3600
                if duration_h >= SATURATION_HOURS:
                    anomalies.append(_make_saturation(
                        sat_start, r.timestamp, field_capacity, threshold,
                        sector_id, probe_id, depth_cm
                    ))
            sat_start = None

    # Trailing window
    if sat_start is not None and readings:
        last_ts = readings[-1].timestamp
        duration_h = (last_ts - sat_start).total_seconds() / 3600
        if duration_h >= SATURATION_HOURS:
            anomalies.append(_make_saturation(
                sat_start, last_ts, field_capacity, threshold,
                sector_id, probe_id, depth_cm
            ))

    return anomalies


def _make_saturation(
    start: datetime, end: datetime, fc: float, threshold: float,
    sector_id: str | None, probe_id: str | None, depth_cm: int | None,
) -> Anomaly:
    duration_h = (end - start).total_seconds() / 3600
    return Anomaly(
        anomaly_type="persistent_saturation",
        severity="warning",
        confidence=0.85,
        sector_id=sector_id,
        probe_id=probe_id,
        depth_cm=depth_cm,
        detected_at=end,
        description_pt=(
            f"Saturação persistente a {depth_cm}cm: >95% da CC ({threshold:.3f} m³/m³) "
            f"durante {duration_h:.0f}h"
        ),
        description_en=(
            f"Persistent saturation at {depth_cm}cm: >95% of FC ({threshold:.3f} m³/m³) "
            f"for {duration_h:.0f}h"
        ),
        likely_causes=(
            "High water table impeding drainage",
            "Drainage problem (blocked drains, clay pan below root zone)",
            "Chronic over-irrigation",
        ),
        recommended_actions=(
            "Check drainage infrastructure for blockages",
            "Reduce irrigation depth — apply smaller, more frequent irrigations",
            "Investigate soil profile for restrictive layers",
        ),
        data_context={
            "start": start.isoformat(), "end": end.isoformat(),
            "duration_h": round(duration_h, 1),
            "field_capacity": fc, "threshold_95pct": round(threshold, 4),
        },
    )


def detect_suspicious_repetition(
    readings: list[Reading],
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
    pattern_len: int = 3,
) -> list[Anomaly]:
    """Exact same value sequence of 3+ readings repeats within 24h."""
    if len(readings) < pattern_len * 2:
        return []

    values = [round(r.vwc, 4) for r in readings]
    found: list[tuple[int, int]] = []  # (first_start, second_start)

    for i in range(len(values) - pattern_len):
        pattern = values[i:i + pattern_len]
        for j in range(i + pattern_len, len(values) - pattern_len + 1):
            # Only within 24h window
            delta_h = (readings[j].timestamp - readings[i].timestamp).total_seconds() / 3600
            if delta_h > 24:
                break
            if values[j:j + pattern_len] == pattern:
                found.append((i, j))

    if not found:
        return []

    first_i, second_i = found[0]
    pattern = values[first_i:first_i + pattern_len]
    return [Anomaly(
        anomaly_type="suspicious_repetition",
        severity="info",
        confidence=0.70,
        sector_id=sector_id,
        probe_id=probe_id,
        depth_cm=depth_cm,
        detected_at=readings[second_i].timestamp,
        description_pt=(
            f"Sequência de {pattern_len} valores idênticos repetida a {depth_cm}cm: {pattern}"
        ),
        description_en=(
            f"Sequence of {pattern_len} identical values repeated at {depth_cm}cm: {pattern}"
        ),
        likely_causes=(
            "Data transmission error causing replay of buffered data",
            "Datalogger buffer not cleared between transmissions",
        ),
        recommended_actions=(
            "Check data transmission logs for gaps or duplicates",
            "Verify datalogger buffer settings and transmission schedule",
        ),
        data_context={
            "pattern": pattern,
            "first_occurrence": readings[first_i].timestamp.isoformat(),
            "second_occurrence": readings[second_i].timestamp.isoformat(),
            "occurrences": len(found),
        },
    )]


def detect_sudden_drying(
    readings: list[Reading],
    et0_mm_day: float | None,
    sector_id: str | None,
    probe_id: str | None,
    depth_cm: int | None,
) -> list[Anomaly]:
    """VWC drops >0.10 m³/m³ in <4h without matching ET demand."""
    # Only flag if ET0 is below threshold (10mm/day = 0.42mm/h)
    et0_high = et0_mm_day is not None and et0_mm_day >= 10.0

    anomalies = []
    for i in range(1, len(readings)):
        prev, curr = readings[i - 1], readings[i]
        hours = (curr.timestamp - prev.timestamp).total_seconds() / 3600
        if hours <= 0 or hours > SUDDEN_DRY_HOURS:
            continue
        delta = prev.vwc - curr.vwc  # positive = drying
        if delta > SUDDEN_DRY_DELTA and not et0_high:
            anomalies.append(Anomaly(
                anomaly_type="sudden_drying",
                severity="warning",
                confidence=0.75,
                sector_id=sector_id,
                probe_id=probe_id,
                depth_cm=depth_cm,
                detected_at=curr.timestamp,
                description_pt=(
                    f"Secagem súbita de {delta:.3f} m³/m³ em {hours:.1f}h a {depth_cm}cm "
                    f"sem ET correspondente"
                ),
                description_en=(
                    f"Sudden drying of {delta:.3f} m³/m³ in {hours:.1f}h at {depth_cm}cm "
                    f"without matching ET demand"
                ),
                likely_causes=(
                    "Sensor air gap (soil shrinkage in clay soils)",
                    "Probe shifted upward by soil movement",
                    "Rapid localised root uptake at very shallow depths",
                ),
                recommended_actions=(
                    "Check probe for soil contact loss — probe may need re-seating",
                    "Compare with adjacent sensor depths",
                    "If clay soil, note if coincides with hot/dry spell",
                ),
                data_context={
                    "delta_vwc": round(delta, 4),
                    "hours": round(hours, 2),
                    "et0_mm_day": et0_mm_day,
                    "from_ts": prev.timestamp.isoformat(),
                    "to_ts": curr.timestamp.isoformat(),
                },
            ))
    return anomalies
