"""Deterministic water-entry detection using probe signals only."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.probe import DepthReadings, ProbeDetectedEvent, TimeSeriesPoint

_MIN_VWC = 0.01
_MAX_VWC = 0.65
_MIN_DYNAMIC_THRESHOLD = 0.006
_MAX_DYNAMIC_THRESHOLD = 0.035
_NOISE_MULTIPLIER = 4.0
_MAX_RISE_WINDOW_H = 8.0
_MIN_SUSTAIN_FRACTION = 0.60
_PROPAGATION_WINDOW_H = 6.0
_MIN_EVENT_SCORE = 0.35


@dataclass(frozen=True)
class _Candidate:
    timestamp: datetime
    depth_cm: int
    delta_vwc: float
    threshold_vwc: float
    elapsed_h: float
    quality: str
    sustained_score: float = 1.0
    cadence_score: float = 1.0

    @property
    def strength(self) -> float:
        return self.delta_vwc / self.threshold_vwc if self.threshold_vwc > 0 else 0.0


async def detect_water_events(
    *,
    depths: list[DepthReadings],
    since: datetime,
    until: datetime,
) -> list[ProbeDetectedEvent]:
    """Detect likely water entries from cumulative, sustained probe responses.

    This detector deliberately uses no flowmeter, manual irrigation, or weather
    input. New events therefore remain ``unlogged`` until a user confirms their
    origin. The confidence describes the probe signal, not certainty that the
    source was irrigation.
    """
    if not depths:
        return []

    candidates = _build_candidates(depths)
    if not candidates:
        return []

    groups = _group_candidates(candidates)
    total_depth_count = len({depth.depth_cm for depth in depths})
    detected: list[ProbeDetectedEvent] = []

    for index, group in enumerate(groups):
        event = _score_group(
            group=group,
            index=index,
            total_depth_count=total_depth_count,
        )
        if event is not None and since <= event.timestamp <= until:
            detected.append(event)

    return detected


def _build_candidates(depths: list[DepthReadings]) -> list[_Candidate]:
    """Build one candidate per sustained rising episode at each depth."""
    candidates: list[_Candidate] = []

    for depth in depths:
        readings = _usable_readings(depth.readings)
        if len(readings) < 3:
            continue

        threshold = _dynamic_threshold(readings)
        cadence_h = _expected_cadence_h(readings)
        candidates.extend(
            _depth_candidates(
                depth_cm=depth.depth_cm,
                readings=readings,
                threshold=threshold,
                cadence_h=cadence_h,
            )
        )

    return sorted(candidates, key=lambda candidate: candidate.timestamp)


def _depth_candidates(
    *,
    depth_cm: int,
    readings: list[TimeSeriesPoint],
    threshold: float,
    cadence_h: float,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    baseline_index = 0
    index = 1

    while index < len(readings):
        point = readings[index]
        baseline = readings[baseline_index]
        elapsed_h = _hours_between(point.timestamp, baseline.timestamp)

        if elapsed_h <= 0:
            index += 1
            continue

        # Follow the drying minimum. A later increase is measured from this local
        # pre-event baseline rather than from only the immediately previous point.
        if point.vwc <= baseline.vwc:
            baseline_index = index
            index += 1
            continue

        cumulative_delta = point.vwc - baseline.vwc
        if cumulative_delta < threshold:
            index += 1
            continue

        peak_index = _peak_index_within_window(
            readings,
            crossing_index=index,
            threshold=threshold,
        )
        peak = readings[peak_index]
        full_delta = peak.vwc - baseline.vwc
        sustained_score = _sustained_score(
            readings=readings,
            crossing_index=index,
            peak_index=peak_index,
            baseline_vwc=baseline.vwc,
            threshold=threshold,
            cadence_h=cadence_h,
        )
        if sustained_score < _MIN_SUSTAIN_FRACTION:
            # Treat an isolated spike as noise and keep looking from the lower of
            # the current baseline or the reading after the spike.
            if peak_index + 1 < len(readings) and readings[peak_index + 1].vwc <= point.vwc:
                baseline_index = peak_index + 1
                index = peak_index + 2
            else:
                index += 1
            continue

        onset_index = _onset_index(
            readings=readings,
            baseline_index=baseline_index,
            crossing_index=index,
            threshold=threshold,
        )
        onset = readings[onset_index]
        event_elapsed_h = max(
            cadence_h,
            _hours_between(peak.timestamp, baseline.timestamp),
        )
        candidates.append(
            _Candidate(
                timestamp=onset.timestamp,
                depth_cm=depth_cm,
                delta_vwc=round(full_delta, 5),
                threshold_vwc=threshold,
                elapsed_h=event_elapsed_h,
                quality=_episode_quality(readings, onset_index, peak_index),
                sustained_score=sustained_score,
                cadence_score=_cadence_score(event_elapsed_h, cadence_h),
            )
        )

        # Re-arm at the peak. Subsequent drying lowers the baseline, while a
        # second rise above a plateau becomes a separate episode.
        baseline_index = peak_index
        index = peak_index + 1

    return candidates


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
    """Robust per-depth noise threshold based on quiet adjacent changes."""
    deltas: list[float] = []
    previous = readings[0]
    for point in readings[1:]:
        elapsed_h = _hours_between(point.timestamp, previous.timestamp)
        if elapsed_h > 0:
            signed_delta = point.vwc - previous.vwc
            # Rising runs are the signal being detected, so including them in
            # the noise floor would hide gradual irrigation responses. Drying,
            # flat readings and only very small positive jitter represent the
            # quiet sensor behaviour.
            if signed_delta <= 0.002 and abs(signed_delta) <= 0.012:
                deltas.append(abs(signed_delta))
        previous = point

    if len(deltas) >= 4:
        median = statistics.median(deltas)
        mad = statistics.median(abs(delta - median) for delta in deltas)
        noise = median + 1.4826 * mad
    elif deltas:
        noise = statistics.median(deltas)
    else:
        noise = 0.0

    return min(
        _MAX_DYNAMIC_THRESHOLD,
        max(_MIN_DYNAMIC_THRESHOLD, noise * _NOISE_MULTIPLIER),
    )


def _expected_cadence_h(readings: list[TimeSeriesPoint]) -> float:
    intervals = [
        _hours_between(right.timestamp, left.timestamp)
        for left, right in zip(readings, readings[1:], strict=False)
    ]
    usable = [interval for interval in intervals if 0 < interval <= 72]
    return statistics.median(usable) if usable else 1.0


def _peak_index_within_window(
    readings: list[TimeSeriesPoint],
    crossing_index: int,
    threshold: float,
) -> int:
    crossing = readings[crossing_index]
    peak_index = crossing_index
    meaningful_decline = max(0.002, threshold * 0.35)
    for index in range(crossing_index + 1, len(readings)):
        elapsed_h = _hours_between(readings[index].timestamp, crossing.timestamp)
        if elapsed_h > _MAX_RISE_WINDOW_H:
            break
        if readings[index].vwc > readings[peak_index].vwc:
            peak_index = index
            continue
        # End the episode once the profile clearly recedes from its peak. This
        # prevents a second same-depth rise a few hours later from being folded
        # into the first marker while tolerating ordinary millivolt-scale noise.
        if readings[peak_index].vwc - readings[index].vwc >= meaningful_decline:
            break
    return peak_index


def _sustained_score(
    *,
    readings: list[TimeSeriesPoint],
    crossing_index: int,
    peak_index: int,
    baseline_vwc: float,
    threshold: float,
    cadence_h: float,
) -> float:
    """Score whether the rise persists beyond one isolated reading."""
    window_end = readings[crossing_index].timestamp + timedelta(hours=max(3.0, cadence_h * 2.5))
    after = [
        point
        for point in readings[crossing_index : peak_index + 3]
        if point.timestamp <= window_end
    ]
    if len(after) < 2:
        return 0.0

    retained = sum(point.vwc - baseline_vwc >= threshold * _MIN_SUSTAIN_FRACTION for point in after)
    return retained / len(after)


def _onset_index(
    *,
    readings: list[TimeSeriesPoint],
    baseline_index: int,
    crossing_index: int,
    threshold: float,
) -> int:
    baseline_vwc = readings[baseline_index].vwc
    onset_threshold = min(threshold, max(0.003, threshold * 0.5))
    for index in range(baseline_index + 1, crossing_index + 1):
        if readings[index].vwc - baseline_vwc >= onset_threshold:
            return index
    return crossing_index


def _episode_quality(
    readings: list[TimeSeriesPoint],
    onset_index: int,
    peak_index: int,
) -> str:
    qualities = {point.quality for point in readings[onset_index : peak_index + 1]}
    return "ok" if qualities == {"ok"} else "suspect"


def _cadence_score(elapsed_h: float, cadence_h: float) -> float:
    expected_window = max(_MAX_RISE_WINDOW_H, cadence_h * 3)
    if elapsed_h <= expected_window:
        return 1.0
    if elapsed_h <= expected_window * 2:
        return 0.70
    return 0.45


def _group_candidates(candidates: list[_Candidate]) -> list[list[_Candidate]]:
    """Group delayed depth responses without merging two rises at one depth."""
    groups: list[list[_Candidate]] = []
    for candidate in candidates:
        if not groups:
            groups.append([candidate])
            continue

        current = groups[-1]
        group_start = current[0].timestamp
        elapsed_h = _hours_between(candidate.timestamp, group_start)
        depths_in_group = {item.depth_cm for item in current}
        if elapsed_h <= _PROPAGATION_WINDOW_H and candidate.depth_cm not in depths_in_group:
            current.append(candidate)
        else:
            groups.append([candidate])

    return groups


def _score_group(
    group: list[_Candidate],
    index: int,
    total_depth_count: int,
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
    depth_coverage_score = min(
        1.0,
        len(depths_cm) / max(1, min(3, total_depth_count)),
    )
    signal_strength_score = min(
        1.0,
        statistics.mean(candidate.strength for candidate in max_by_depth.values()) / 2.0,
    )
    depth_sequence_score = _depth_sequence_score(first_by_depth)
    sensor_quality_score = _sensor_quality_score(first_by_depth)
    sustained_score = statistics.mean(
        candidate.sustained_score for candidate in max_by_depth.values()
    )

    score = _clamp(
        0.38 * signal_strength_score
        + 0.20 * depth_coverage_score
        + 0.16 * depth_sequence_score
        + 0.14 * sensor_quality_score
        + 0.12 * sustained_score
    )
    if score < _MIN_EVENT_SCORE:
        return None

    confidence = "high" if score >= 0.78 else "medium" if score >= 0.55 else "low"
    return ProbeDetectedEvent(
        id=f"wetting-{index}-{int(event_ts.timestamp())}",
        timestamp=event_ts,
        kind="unlogged",
        confidence=confidence,
        depths_cm=depths_cm,
        delta_vwc=total_delta,
        rainfall_mm=None,
        irrigation_mm=None,
        score=round(score, 3),
        probability_irrigation=0.0,
        probability_rain=0.0,
        probability_unlogged=round(score, 3),
        source_match_score=0.0,
        depth_sequence_score=round(depth_sequence_score, 3),
        signal_strength_score=round(signal_strength_score, 3),
        sensor_quality_score=round(sensor_quality_score, 3),
        message=_build_message(len(depths_cm), confidence, score),
    )


def _depth_sequence_score(by_depth: dict[int, _Candidate]) -> float:
    ordered = sorted(by_depth.items())
    if len(ordered) == 1:
        return 0.65

    valid_pairs = 0
    total_pairs = 0
    for left_index, (left_depth, left_candidate) in enumerate(ordered):
        for right_depth, right_candidate in ordered[left_index + 1 :]:
            total_pairs += 1
            if left_depth <= right_depth and left_candidate.timestamp <= right_candidate.timestamp:
                valid_pairs += 1

    return valid_pairs / total_pairs if total_pairs else 0.65


def _sensor_quality_score(by_depth: dict[int, _Candidate]) -> float:
    scores = []
    for candidate in by_depth.values():
        quality_score = 1.0 if candidate.quality == "ok" else 0.65
        scores.append(quality_score * candidate.cadence_score)
    return statistics.mean(scores) if scores else 0.0


def _build_message(depth_count: int, confidence: str, score: float) -> str:
    confidence_label = {
        "low": "baixa",
        "medium": "média",
        "high": "alta",
    }.get(confidence, confidence)
    return (
        f"Entrada de água provável detectada pela sonda em "
        f"{depth_count} profundidade(s); confiança {confidence_label} ({score:.0%})."
    )


def _hours_between(right: datetime, left: datetime) -> float:
    return (right - left).total_seconds() / 3600


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
