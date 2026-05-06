"""Water event detection from probe signal plus irrigation/weather sources."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IrrigationEvent, Plot, Sector, WeatherObservation
from app.schemas.probe import DepthReadings, ProbeDetectedEvent, TimeSeriesPoint

_MIN_VWC = 0.01
_MAX_VWC = 0.65
_MIN_DYNAMIC_THRESHOLD = 0.008
_MAX_DYNAMIC_THRESHOLD = 0.035
_NOISE_MULTIPLIER = 3.0
_MAX_READING_GAP_H = 12.0
_GROUP_WINDOW_H = 8.0
_IRRIGATION_MATCH_BEFORE_H = 2.0
_IRRIGATION_MATCH_AFTER_H = 18.0
_RAIN_MATCH_H = 24.0


@dataclass(frozen=True)
class _Candidate:
    timestamp: datetime
    depth_cm: int
    delta_vwc: float
    threshold_vwc: float
    elapsed_h: float
    quality: str

    @property
    def strength(self) -> float:
        return self.delta_vwc / self.threshold_vwc if self.threshold_vwc > 0 else 0.0


async def detect_water_events(
    db: AsyncSession,
    sector: Sector | None,
    plot: Plot | None,
    depths: list[DepthReadings],
    since: datetime,
    until: datetime,
) -> list[ProbeDetectedEvent]:
    """Detect and classify likely water entries from probe VWC response.

    This intentionally returns scored events, not just labels. The scores make
    later threshold tuning and user feedback loops possible without changing
    the public API again.
    """
    if not sector or not depths:
        return []

    candidates = _build_candidates(depths)
    if not candidates:
        return []

    groups = _group_candidates(candidates)
    irrigation_events, weather_events = await _load_source_events(
        db=db,
        sector=sector,
        plot=plot,
        since=since,
        until=until,
    )

    detected: list[ProbeDetectedEvent] = []
    total_depth_count = len({depth.depth_cm for depth in depths})

    for idx, group in enumerate(groups[:12]):
        event = _score_group(
            group=group,
            index=idx,
            total_depth_count=total_depth_count,
            irrigation_events=irrigation_events,
            weather_events=weather_events,
        )
        if event is not None:
            detected.append(event)

    return detected


def _build_candidates(depths: list[DepthReadings]) -> list[_Candidate]:
    candidates: list[_Candidate] = []

    for depth in depths:
        readings = _usable_readings(depth.readings)
        if len(readings) < 2:
            continue

        threshold = _dynamic_threshold(readings)
        previous = readings[0]
        for point in readings[1:]:
            elapsed_h = (point.timestamp - previous.timestamp).total_seconds() / 3600
            if 0 < elapsed_h <= _MAX_READING_GAP_H:
                delta = point.vwc - previous.vwc
                if delta >= threshold:
                    candidates.append(
                        _Candidate(
                            timestamp=point.timestamp,
                            depth_cm=depth.depth_cm,
                            delta_vwc=delta,
                            threshold_vwc=threshold,
                            elapsed_h=elapsed_h,
                            quality=point.quality,
                        )
                    )
            previous = point

    return sorted(candidates, key=lambda candidate: candidate.timestamp)


def _usable_readings(readings: list[TimeSeriesPoint]) -> list[TimeSeriesPoint]:
    return sorted(
        (
            point
            for point in readings
            if point.quality != "invalid" and _MIN_VWC <= point.vwc <= _MAX_VWC
        ),
        key=lambda point: point.timestamp,
    )


def _dynamic_threshold(readings: list[TimeSeriesPoint]) -> float:
    deltas: list[float] = []
    previous = readings[0]
    for point in readings[1:]:
        elapsed_h = (point.timestamp - previous.timestamp).total_seconds() / 3600
        if 0 < elapsed_h <= _MAX_READING_GAP_H:
            delta = abs(point.vwc - previous.vwc)
            if delta <= 0.01:
                deltas.append(delta)
        previous = point

    if len(deltas) >= 4:
        noise = statistics.pstdev(deltas)
    elif deltas:
        noise = statistics.mean(deltas) / 2
    else:
        noise = 0.0

    return min(
        _MAX_DYNAMIC_THRESHOLD,
        max(_MIN_DYNAMIC_THRESHOLD, noise * _NOISE_MULTIPLIER),
    )


def _group_candidates(candidates: list[_Candidate]) -> list[list[_Candidate]]:
    groups: list[list[_Candidate]] = []
    for candidate in candidates:
        if not groups:
            groups.append([candidate])
            continue

        group_start = groups[-1][0].timestamp
        if (candidate.timestamp - group_start).total_seconds() <= _GROUP_WINDOW_H * 3600:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])

    return groups


async def _load_source_events(
    db: AsyncSession,
    sector: Sector,
    plot: Plot | None,
    since: datetime,
    until: datetime,
) -> tuple[list[IrrigationEvent], list[WeatherObservation]]:
    window_start = since - timedelta(hours=24)
    window_end = until + timedelta(hours=24)

    irrigation_events = (
        await db.execute(
            select(IrrigationEvent)
            .where(
                IrrigationEvent.sector_id == sector.id,
                IrrigationEvent.start_time >= window_start,
                IrrigationEvent.start_time <= window_end,
            )
            .order_by(IrrigationEvent.start_time)
        )
    ).scalars().all()

    weather_events: list[WeatherObservation] = []
    if plot:
        weather_events = (
            await db.execute(
                select(WeatherObservation)
                .where(
                    WeatherObservation.farm_id == plot.farm_id,
                    WeatherObservation.timestamp >= window_start,
                    WeatherObservation.timestamp <= window_end,
                    WeatherObservation.rainfall_mm.is_not(None),
                    WeatherObservation.rainfall_mm > 0.2,
                )
                .order_by(WeatherObservation.timestamp)
            )
        ).scalars().all()

    return irrigation_events, weather_events


def _score_group(
    group: list[_Candidate],
    index: int,
    total_depth_count: int,
    irrigation_events: list[IrrigationEvent],
    weather_events: list[WeatherObservation],
) -> ProbeDetectedEvent | None:
    if not group:
        return None

    event_ts = min(candidate.timestamp for candidate in group)
    max_by_depth: dict[int, _Candidate] = {}
    first_by_depth: dict[int, _Candidate] = {}
    for candidate in group:
        current = max_by_depth.get(candidate.depth_cm)
        if current is None or candidate.delta_vwc > current.delta_vwc:
            max_by_depth[candidate.depth_cm] = candidate

        first = first_by_depth.get(candidate.depth_cm)
        if first is None or candidate.timestamp < first.timestamp:
            first_by_depth[candidate.depth_cm] = candidate

    depths_cm = sorted(max_by_depth)
    if not depths_cm:
        return None

    total_delta = round(sum(candidate.delta_vwc for candidate in max_by_depth.values()), 4)
    depth_coverage_score = min(1.0, len(depths_cm) / max(1, min(3, total_depth_count)))
    signal_strength_score = min(
        1.0,
        statistics.mean(candidate.strength for candidate in max_by_depth.values()) / 3.0,
    )
    depth_sequence_score = _depth_sequence_score(first_by_depth)
    sensor_quality_score = _sensor_quality_score(first_by_depth)

    irrigation, irrigation_source_score = _nearest_irrigation(irrigation_events, event_ts)
    rain, rain_source_score = _nearest_rain(weather_events, event_ts)

    signal_score = (
        0.35 * signal_strength_score
        + 0.25 * depth_coverage_score
        + 0.25 * depth_sequence_score
        + 0.15 * sensor_quality_score
    )

    probability_irrigation = _clamp(
        0.62 * irrigation_source_score
        + 0.28 * signal_score
        + 0.10 * (1.0 - rain_source_score)
    )
    probability_rain = _clamp(
        0.58 * rain_source_score
        + 0.22 * signal_score
        + 0.20 * _rain_pattern_bonus(irrigation_source_score, depth_coverage_score)
    )
    probability_unlogged = _clamp(
        signal_score
        * (1.0 - max(irrigation_source_score, rain_source_score) * 0.65)
    )

    kind = "unlogged"
    score = probability_unlogged
    if probability_irrigation >= probability_rain and probability_irrigation >= probability_unlogged:
        kind = "irrigation"
        score = probability_irrigation
    elif probability_rain >= probability_unlogged:
        kind = "rain"
        score = probability_rain

    if score < 0.35:
        return None

    confidence = "high" if score >= 0.78 else "medium" if score >= 0.55 else "low"
    irrigation_mm = irrigation.applied_mm if irrigation else None
    rainfall_mm = rain.rainfall_mm if rain else None
    source_match_score = max(irrigation_source_score, rain_source_score)

    return ProbeDetectedEvent(
        id=f"wetting-{index}-{int(event_ts.timestamp())}",
        timestamp=event_ts,
        kind=kind,
        confidence=confidence,
        depths_cm=depths_cm,
        delta_vwc=total_delta,
        rainfall_mm=rainfall_mm,
        irrigation_mm=irrigation_mm,
        score=round(score, 3),
        probability_irrigation=round(probability_irrigation, 3),
        probability_rain=round(probability_rain, 3),
        probability_unlogged=round(probability_unlogged, 3),
        source_match_score=round(source_match_score, 3),
        depth_sequence_score=round(depth_sequence_score, 3),
        signal_strength_score=round(signal_strength_score, 3),
        sensor_quality_score=round(sensor_quality_score, 3),
        message=_build_message(kind, len(depths_cm), confidence, score),
    )


def _depth_sequence_score(by_depth: dict[int, _Candidate]) -> float:
    ordered = sorted(by_depth.items())
    if len(ordered) == 1:
        return 0.55

    valid_pairs = 0
    total_pairs = 0
    for left_idx, (left_depth, left_candidate) in enumerate(ordered):
        for right_depth, right_candidate in ordered[left_idx + 1:]:
            total_pairs += 1
            if left_depth <= right_depth and left_candidate.timestamp <= right_candidate.timestamp:
                valid_pairs += 1

    if total_pairs == 0:
        return 0.55

    return valid_pairs / total_pairs


def _sensor_quality_score(by_depth: dict[int, _Candidate]) -> float:
    scores = []
    for candidate in by_depth.values():
        quality_score = 1.0 if candidate.quality == "ok" else 0.72
        gap_score = 1.0 if candidate.elapsed_h <= 3 else 0.82 if candidate.elapsed_h <= 6 else 0.65
        scores.append(quality_score * gap_score)
    return statistics.mean(scores) if scores else 0.0


def _nearest_irrigation(
    events: list[IrrigationEvent],
    timestamp: datetime,
) -> tuple[IrrigationEvent | None, float]:
    best_event: IrrigationEvent | None = None
    best_score = 0.0

    for event in events:
        delta_h = (timestamp - event.start_time).total_seconds() / 3600
        if -_IRRIGATION_MATCH_BEFORE_H <= delta_h <= _IRRIGATION_MATCH_AFTER_H:
            time_score = 1.0 - abs(delta_h) / _IRRIGATION_MATCH_AFTER_H
            amount_score = 0.15 if event.applied_mm else 0.0
            score = _clamp(time_score + amount_score)
            if score > best_score:
                best_event = event
                best_score = score

    return best_event, best_score


def _nearest_rain(
    events: list[WeatherObservation],
    timestamp: datetime,
) -> tuple[WeatherObservation | None, float]:
    best_event: WeatherObservation | None = None
    best_score = 0.0

    for event in events:
        delta_h = abs((timestamp - event.timestamp).total_seconds()) / 3600
        if delta_h <= _RAIN_MATCH_H:
            rain_mm = event.rainfall_mm or 0.0
            time_score = 1.0 - delta_h / _RAIN_MATCH_H
            amount_score = min(1.0, rain_mm / 8.0)
            score = _clamp(0.7 * time_score + 0.3 * amount_score)
            if score > best_score:
                best_event = event
                best_score = score

    return best_event, best_score


def _rain_pattern_bonus(irrigation_source_score: float, depth_coverage_score: float) -> float:
    if irrigation_source_score > 0.2:
        return 0.0
    return depth_coverage_score


def _build_message(kind: str, depth_count: int, confidence: str, score: float) -> str:
    source = {
        "irrigation": "compatível com rega registada",
        "rain": "compatível com chuva registada",
        "unlogged": "sem fonte registada próxima",
    }.get(kind, "fonte incerta")
    return (
        f"Entrada de água detectada em {depth_count} profundidade(s), "
        f"{source}; confiança {confidence} ({score:.0%})."
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
