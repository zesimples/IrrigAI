"""Recommendation service.

Calls the agronomic pipeline and persists results to the DB.
LLM explanation is NOT called here — that's a separate, optional step.
"""

import logging
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.pipeline import RecommendationPipeline
from app.engine.types import EngineRecommendation
from app.metrics import recommendations_generated_total
from app.models import Recommendation, RecommendationReason

logger = logging.getLogger(__name__)

_pipeline = RecommendationPipeline()


def _make_inputs_snapshot(eng: EngineRecommendation, target_date: date) -> dict:
    snap = {
        "sector_id": eng.sector_id,
        "target_date": target_date.isoformat(),
        "et0_mm": eng.et0_mm,
        "etc_mm": eng.etc_mm,
        "swc_current": eng.swc_current,
        "depletion_mm": eng.depletion_mm,
        "raw_mm": eng.raw_mm,
        "taw_mm": eng.taw_mm,
        "rain_effective_mm": eng.rain_effective_mm,
        "forecast_rain_next_48h": eng.forecast_rain_next_48h,
        "defaults_used": eng.defaults_used,
        "missing_config": eng.missing_config,
    }
    if eng.stress_projection is not None:
        snap["stress_projection"] = eng.stress_projection
    return snap


def _persist_rec(eng: EngineRecommendation, target_date: date) -> Recommendation:
    return Recommendation(
        sector_id=eng.sector_id,
        target_date=target_date,
        generated_at=eng.generated_at,
        action=eng.action,
        confidence_score=eng.confidence.score,
        confidence_level=eng.confidence.level,
        irrigation_depth_mm=eng.irrigation_depth_mm,
        irrigation_runtime_min=eng.irrigation_runtime_min,
        suggested_start_time=eng.suggested_start_time,
        engine_version=eng.engine_version,
        inputs_snapshot=_make_inputs_snapshot(eng, target_date),
        computation_log=eng.computation_log,
    )


async def generate_recommendation(
    sector_id: str,
    db: AsyncSession,
    target_date: date | None = None,
    farm_id: str | None = None,
) -> tuple[Recommendation, EngineRecommendation]:
    """Run engine for one sector and persist the recommendation.

    Returns (persisted Recommendation ORM object, EngineRecommendation dataclass).
    """
    if target_date is None:
        target_date = datetime.now(UTC).date()

    try:
        eng: EngineRecommendation = await _pipeline.run(
            sector_id=sector_id,
            target_date=target_date,
            db=db,
            farm_id=farm_id,
        )

        rec = _persist_rec(eng, target_date)
        db.add(rec)
        await db.flush()

        for entry in eng.reasons:
            db.add(RecommendationReason(
                recommendation_id=rec.id,
                order=entry.order,
                category=entry.category,
                message_pt=entry.message_pt,
                message_en=entry.message_en,
                data_key=entry.data_key,
                data_value=entry.data_value,
            ))

        await db.commit()
        await db.refresh(rec)

        logger.info(
            "Recommendation %s: sector=%s action=%s confidence=%.2f",
            rec.id, sector_id, eng.action, eng.confidence.score,
        )
        recommendations_generated_total.labels(eng.action, "success").inc()
        return rec, eng
    except Exception:
        recommendations_generated_total.labels("unknown", "failure").inc()
        raise


async def generate_for_farm(
    farm_id: str,
    db: AsyncSession,
    target_date: date | None = None,
) -> list[tuple[Recommendation, EngineRecommendation]]:
    """Run engine for all sectors of a farm and persist all recommendations."""
    if target_date is None:
        target_date = datetime.now(UTC).date()

    engine_results = await _pipeline.run_all_sectors(farm_id, target_date, db)

    saved = []
    for eng in engine_results:
        try:
            rec = _persist_rec(eng, target_date)
            db.add(rec)
            await db.flush()

            for entry in eng.reasons:
                db.add(RecommendationReason(
                    recommendation_id=rec.id,
                    order=entry.order,
                    category=entry.category,
                    message_pt=entry.message_pt,
                    message_en=entry.message_en,
                    data_key=entry.data_key,
                    data_value=entry.data_value,
                ))

            await db.commit()
            await db.refresh(rec)
            saved.append((rec, eng))
            logger.info("Saved recommendation %s for sector %s", rec.id, eng.sector_id)
        except Exception:
            logger.exception("Failed to persist recommendation for sector %s", eng.sector_id)
            recommendations_generated_total.labels("unknown", "failure").inc()
            await db.rollback()

    return saved
