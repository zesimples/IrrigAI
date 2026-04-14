"""Builds structured context dicts injected into ChatGPT calls.

The LLM never queries the DB — it receives a JSON-serialisable snapshot built here.
Key design: config_status / defaults_used / missing_config propagate from the engine
so the LLM can explain what was inferred vs. user-configured.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.pipeline import build_sector_context, build_weather_context, build_irrigation_context
from app.models import Alert, Farm, Plot, Recommendation, RecommendationReason, Sector


# ---------------------------------------------------------------------------
# Context dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SectorAssistantContext:
    # Identity
    sector_id: str
    sector_name: str
    crop_type: str
    variety: str | None
    phenological_stage: str | None
    area_ha: float | None

    # Configuration status
    config_status: dict[str, str]           # e.g. {"soil": "configured", "irrigation_system": "missing"}
    defaults_used: list[str]
    missing_config: list[str]

    # Latest recommendation
    recommendation_action: str | None
    irrigation_depth_mm: float | None
    runtime_minutes: float | None
    confidence_score: float | None
    confidence_level: str | None
    reasons: list[dict]

    # Rootzone / water balance snapshot from computation_log
    rootzone_depletion_mm: float | None
    rootzone_taw_mm: float | None
    rootzone_raw_mm: float | None
    rootzone_swc: float | None

    # Weather
    today_et0_mm: float | None
    today_temp_max_c: float | None
    rainfall_last_24h_mm: float
    forecast_rain_next_48h_mm: float

    # Irrigation history
    last_irrigation_date: str | None
    total_irrigation_7d_mm: float

    # Active alerts
    active_alerts: list[dict]

    # Data freshness
    generated_at: str | None


@dataclass
class FarmAssistantContext:
    farm_id: str
    farm_name: str
    date: str
    location: dict | None
    weather_summary: dict
    sectors: list[SectorAssistantContext]
    total_active_alerts: int
    missing_data_priorities: list[str]
    setup_completion_pct: float


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class AssistantContextBuilder:
    """Assembles LLM context by reading from the DB and engine output."""

    async def build_sector_context(
        self, sector_id: str, db: AsyncSession
    ) -> SectorAssistantContext:
        # Engine context (agronomic params + provenance)
        eng_ctx = await build_sector_context(sector_id, db)

        sector = await db.get(Sector, sector_id)

        # Config status inference
        config_status: dict[str, str] = {}
        config_status["soil"] = (
            "configured" if "soil FC/PWP" not in " ".join(eng_ctx.defaults_used) else "defaulted"
        )
        config_status["irrigation_system"] = (
            "missing" if eng_ctx.irrigation_system_type is None else "configured"
        )
        config_status["phenological_stage"] = (
            "configured" if eng_ctx.phenological_stage else "not_set"
        )
        config_status["crop_profile"] = (
            "missing" if "no crop profile" in " ".join(eng_ctx.missing_config) else "configured"
        )

        # Latest recommendation
        rec_result = await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector_id)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
        rec: Recommendation | None = rec_result.scalar_one_or_none()

        reasons: list[dict] = []
        depletion_mm = taw_mm = raw_mm = swc = None
        et0_mm = temp_max = rain_24h = rain_48h = None

        if rec:
            # Extract reasons
            reasons_result = await db.execute(
                select(RecommendationReason)
                .where(RecommendationReason.recommendation_id == rec.id)
                .order_by(RecommendationReason.order)
            )
            for r in reasons_result.scalars().all():
                reasons.append({
                    "category": r.category,
                    "message": r.message_pt,
                })

            # Extract inputs from computation_log / inputs_snapshot
            snap = rec.inputs_snapshot or {}
            log = rec.computation_log or {}
            depletion_mm = snap.get("depletion_mm")
            taw_mm = snap.get("taw_mm")
            raw_mm = snap.get("raw_mm")
            swc = snap.get("swc_current")
            et0_mm = snap.get("et0_mm")
            temp_max = snap.get("temperature_max_c")
            rain_24h = snap.get("rainfall_mm", 0.0)
            rain_48h = snap.get("forecast_rain_next_48h", 0.0)

        # Irrigation history
        irrig_ctx = await build_irrigation_context(sector_id, db)
        last_irrig_date = (
            irrig_ctx.last_irrigation_at.strftime("%Y-%m-%d")
            if irrig_ctx.last_irrigation_at else None
        )

        # Active alerts for this sector
        alerts_result = await db.execute(
            select(Alert)
            .where(Alert.sector_id == sector_id, Alert.is_active == True)  # noqa: E712
            .order_by(Alert.created_at.desc())
            .limit(5)
        )
        active_alerts = [
            {"severity": a.severity, "title": a.title_pt, "description": a.description_pt}
            for a in alerts_result.scalars().all()
        ]

        return SectorAssistantContext(
            sector_id=sector_id,
            sector_name=eng_ctx.sector_name,
            crop_type=eng_ctx.crop_type,
            variety=sector.variety if sector else None,
            phenological_stage=eng_ctx.phenological_stage,
            area_ha=eng_ctx.area_ha,
            config_status=config_status,
            defaults_used=eng_ctx.defaults_used,
            missing_config=eng_ctx.missing_config,
            recommendation_action=rec.action if rec else None,
            irrigation_depth_mm=rec.irrigation_depth_mm if rec else None,
            runtime_minutes=rec.irrigation_runtime_min if rec else None,
            confidence_score=rec.confidence_score if rec else None,
            confidence_level=rec.confidence_level if rec else None,
            reasons=reasons,
            rootzone_depletion_mm=depletion_mm,
            rootzone_taw_mm=taw_mm,
            rootzone_raw_mm=raw_mm,
            rootzone_swc=swc,
            today_et0_mm=et0_mm,
            today_temp_max_c=temp_max,
            rainfall_last_24h_mm=rain_24h or 0.0,
            forecast_rain_next_48h_mm=rain_48h or 0.0,
            last_irrigation_date=last_irrig_date,
            total_irrigation_7d_mm=irrig_ctx.total_applied_7d_mm,
            active_alerts=active_alerts,
            generated_at=rec.generated_at.isoformat() if rec else None,
        )

    async def build_farm_context(
        self, farm_id: str, db: AsyncSession
    ) -> FarmAssistantContext:
        farm = await db.get(Farm, farm_id)
        farm_name = farm.name if farm else farm_id
        location = (
            {"lat": farm.location_lat, "lon": farm.location_lon, "region": farm.region}
            if farm else None
        )

        # Weather summary
        weather_ctx = await build_weather_context(farm_id, db)
        today = weather_ctx.today
        weather_summary = {
            "et0_mm": today.et0_mm,
            "rainfall_mm": today.rainfall_mm,
            "temp_max_c": today.t_max,
            "temp_min_c": today.t_min,
            "forecast_rain_next_48h_mm": sum(
                (f.rainfall_mm or 0.0) for f in weather_ctx.forecast[:2]
            ),
        }

        # All sectors under this farm
        plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
        plots = plots_result.scalars().all()

        sector_contexts: list[SectorAssistantContext] = []
        for plot in plots:
            sectors_result = await db.execute(
                select(Sector).where(Sector.plot_id == plot.id)
            )
            for sector in sectors_result.scalars().all():
                try:
                    sc = await self.build_sector_context(sector.id, db)
                    sector_contexts.append(sc)
                except Exception:
                    pass

        # Setup completion
        total = len(sector_contexts)
        if total > 0:
            configured = sum(
                1 for s in sector_contexts
                if s.config_status.get("irrigation_system") == "configured"
                and s.config_status.get("soil") == "configured"
            )
            setup_pct = configured / total * 100
        else:
            setup_pct = 0.0

        # Missing data priorities (deduplicated across sectors)
        missing: list[str] = []
        seen: set[str] = set()
        for sc in sector_contexts:
            for m in sc.missing_config:
                if m not in seen:
                    missing.append(m)
                    seen.add(m)

        # Total active alerts
        alerts_result = await db.execute(
            select(Alert).where(Alert.farm_id == farm_id, Alert.is_active == True)  # noqa: E712
        )
        total_alerts = len(alerts_result.scalars().all())

        return FarmAssistantContext(
            farm_id=farm_id,
            farm_name=farm_name,
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            location=location,
            weather_summary=weather_summary,
            sectors=sector_contexts,
            total_active_alerts=total_alerts,
            missing_data_priorities=missing,
            setup_completion_pct=round(setup_pct, 1),
        )

    def to_json(self, ctx: SectorAssistantContext | FarmAssistantContext) -> str:
        """Serialise context to JSON string for injection into LLM prompt."""
        return json.dumps(asdict(ctx), ensure_ascii=False, default=str, indent=2)
