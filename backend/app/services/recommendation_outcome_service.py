"""Deterministic recommendation-to-execution outcome tracking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Farm,
    IrrigationEvent,
    IrrigationEventDetected,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Recommendation,
    RecommendationOutcome,
    Sector,
)

_MATCH_WINDOW_HOURS = 36
_LOOKBACK_DAYS = 21


async def evaluate_recent_for_farm(farm_id: str, db: AsyncSession) -> int:
    """Upsert outcomes for recent farmer-accepted recommendations."""
    since = datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)
    recommendations = (
        (
            await db.execute(
                select(Recommendation)
                .join(Sector, Recommendation.sector_id == Sector.id)
                .join(Plot, Sector.plot_id == Plot.id)
                .join(Farm, Plot.farm_id == Farm.id)
                .where(
                    Plot.farm_id == farm_id,
                    Farm.is_archived.is_(False),
                    Plot.is_archived.is_(False),
                    Sector.is_archived.is_(False),
                    Recommendation.is_accepted.is_(True),
                    Recommendation.generated_at >= since,
                )
            )
        )
        .scalars()
        .all()
    )

    evaluated = 0
    for recommendation in recommendations:
        if await evaluate_recommendation(recommendation, db):
            evaluated += 1
    await db.commit()
    return evaluated


async def evaluate_recommendation(
    recommendation: Recommendation,
    db: AsyncSession,
) -> RecommendationOutcome | None:
    start = recommendation.generated_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    deadline = start + timedelta(hours=_MATCH_WINDOW_HOURS)

    manual_event = (
        await db.execute(
            select(IrrigationEvent)
            .where(
                IrrigationEvent.sector_id == recommendation.sector_id,
                IrrigationEvent.start_time >= start,
                IrrigationEvent.start_time <= deadline,
            )
            .order_by(
                (IrrigationEvent.recommendation_id == recommendation.id).desc(),
                IrrigationEvent.start_time,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    detected_event = None
    if manual_event is None:
        detected_event = (
            await db.execute(
                select(IrrigationEventDetected)
                .where(
                    IrrigationEventDetected.sector_id == recommendation.sector_id,
                    IrrigationEventDetected.start_time >= start,
                    IrrigationEventDetected.start_time <= deadline,
                )
                .order_by(IrrigationEventDetected.start_time)
                .limit(1)
            )
        ).scalar_one_or_none()

    event_start = (
        manual_event.start_time
        if manual_event is not None
        else (detected_event.start_time if detected_event is not None else None)
    )
    actual_mm = (
        manual_event.applied_mm
        if manual_event is not None
        else (round(detected_event.total_m3_ha / 10.0, 3) if detected_event is not None else None)
    )

    now = datetime.now(UTC)
    if event_start is None and now < deadline:
        return None

    recommended_mm = recommendation.irrigation_depth_mm
    dose_error_mm = None
    dose_error_pct = None
    if actual_mm is not None and recommended_mm is not None:
        dose_error_mm = round(actual_mm - recommended_mm, 3)
        if recommended_mm > 0:
            dose_error_pct = round(dose_error_mm / recommended_mm * 100, 2)

    pre_vwc = post_vwc = response_delta = None
    response_by_depth: list[dict] = []
    if event_start is not None:
        pre_vwc, post_vwc, response_by_depth = await _probe_response(
            str(recommendation.sector_id), event_start, db
        )
        if pre_vwc is not None and post_vwc is not None:
            response_delta = round(post_vwc - pre_vwc, 5)

    if event_start is not None:
        status = "executed"
    elif recommendation.action in {"skip", "defer"}:
        status = "followed_skip"
        actual_mm = 0.0
    else:
        status = "no_event"

    outcome = (
        await db.execute(
            select(RecommendationOutcome).where(
                RecommendationOutcome.recommendation_id == recommendation.id
            )
        )
    ).scalar_one_or_none()
    if outcome is None:
        outcome = RecommendationOutcome(
            recommendation_id=recommendation.id,
            sector_id=recommendation.sector_id,
        )
        db.add(outcome)

    outcome.irrigation_event_id = manual_event.id if manual_event else None
    outcome.detected_event_id = detected_event.id if detected_event else None
    outcome.evaluated_at = now
    outcome.status = status
    outcome.recommended_depth_mm = recommended_mm
    outcome.actual_applied_mm = actual_mm
    outcome.dose_error_mm = dose_error_mm
    outcome.dose_error_pct = dose_error_pct
    outcome.pre_irrigation_vwc = pre_vwc
    outcome.post_irrigation_vwc = post_vwc
    outcome.probe_response_delta = response_delta
    outcome.details = {
        "recommendation_action": recommendation.action,
        "match_window_hours": _MATCH_WINDOW_HOURS,
        "actual_source": (
            "irrigation_event"
            if manual_event
            else ("flowmeter_detected_event" if detected_event else "none")
        ),
        "probe_response_by_depth": response_by_depth,
    }
    await db.flush()
    return outcome


async def _probe_response(
    sector_id: str,
    event_start: datetime,
    db: AsyncSession,
) -> tuple[float | None, float | None, list[dict]]:
    """Compare per-depth VWC immediately before and 2–24h after irrigation."""
    depths = (
        (
            await db.execute(
                select(ProbeDepth)
                .join(Probe, ProbeDepth.probe_id == Probe.id)
                .where(
                    Probe.sector_id == sector_id,
                    ProbeDepth.sensor_type.in_(("soil_moisture", "moisture")),
                )
            )
        )
        .scalars()
        .all()
    )
    if not depths:
        return None, None, []

    before_values: list[float] = []
    after_values: list[float] = []
    by_depth: list[dict] = []
    for depth in depths:
        before = (
            await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id == depth.id,
                    ProbeReading.timestamp >= event_start - timedelta(hours=6),
                    ProbeReading.timestamp <= event_start,
                    ProbeReading.quality_flag.notin_(("invalid", "suspect")),
                )
                .order_by(ProbeReading.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        after = (
            await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id == depth.id,
                    ProbeReading.timestamp >= event_start + timedelta(hours=2),
                    ProbeReading.timestamp <= event_start + timedelta(hours=24),
                    ProbeReading.quality_flag.notin_(("invalid", "suspect")),
                )
                .order_by(ProbeReading.calibrated_value.desc().nullslast())
                .limit(1)
            )
        ).scalar_one_or_none()
        if before and before.calibrated_value is not None:
            before_values.append(before.calibrated_value)
        if after and after.calibrated_value is not None:
            after_values.append(after.calibrated_value)
        if (
            before
            and after
            and before.calibrated_value is not None
            and after.calibrated_value is not None
        ):
            delta = round(after.calibrated_value - before.calibrated_value, 5)
            by_depth.append(
                {
                    "depth_cm": depth.depth_cm,
                    "delta_vwc": delta,
                    "response": (
                        "increase"
                        if delta > 0.003
                        else ("decrease" if delta < -0.003 else "stable")
                    ),
                }
            )

    return (
        round(sum(before_values) / len(before_values), 5) if before_values else None,
        round(sum(after_values) / len(after_values), 5) if after_values else None,
        by_depth,
    )
