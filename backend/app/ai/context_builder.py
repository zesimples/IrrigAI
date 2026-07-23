"""Builds structured context dicts injected into ChatGPT calls.

The LLM never queries the DB — it receives a JSON-serialisable snapshot built here.
Key design: config_status / defaults_used / missing_config propagate from the engine
so the LLM can explain what was inferred vs. user-configured.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_v2 import SectorAIContextV2
from app.engine.pipeline import (
    build_irrigation_context,
    build_sector_context,
    build_weather_context,
    resolve_sector_soil_bounds,
    resolve_weather_plot_id,
)
from app.engine.probe_interpreter import interpret_probes
from app.engine.staleness import PROBE_STALE_H, PROBE_VERY_STALE_H
from app.engine.types import SectorContext
from app.models import (
    Alert,
    DetectedWaterEvent,
    Farm,
    FieldObservation,
    IrrigationEvent,
    IrrigationEventDetected,
    IrrigationFingerprint,
    IrrigationSystem,
    Plot,
    Probe,
    ProbeCalibration,
    ProbeCalibrationRun,
    ProbeDepth,
    ProbeReading,
    ProviderIngestionRun,
    Recommendation,
    RecommendationOutcome,
    RecommendationReason,
    Sector,
    SectorCropProfile,
    WeatherForecast,
    WeatherObservation,
)
from app.utils.format_pt import fmt_pt

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
    config_status: dict[str, str]  # e.g. {"soil": "configured", "irrigation_system": "missing"}
    defaults_used: list[str]
    missing_config: list[str]

    # Latest recommendation
    recommendation_id: str | None
    recommendation_action: str | None
    recommendation_is_accepted: bool | None
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
    today_etc_mm: float | None
    rainfall_effective_mm: float | None
    rain_skip_applies: bool | None
    swc_source: str | None
    swc_model: dict | None
    fc_calibration: dict | None
    dose_band: str | None
    dose_source: str | None
    dose_presentation: dict | None
    stress_projection: dict | None
    confidence_penalties: list | dict | None

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

    # Live probe readings (independent of last recommendation)
    probe_live: dict | None

    # Data quality (#9 quality scoring)
    # "fresh" | "stale" | "forecast_only" | "no_probe"
    source_confidence: str
    # Pre-built Portuguese sentence for the AI to cite in its "Qualidade dos dados" bullet
    data_quality_explanation: str

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
# Data-quality helpers
# ---------------------------------------------------------------------------


def _farm_probe_confidence(
    *,
    has_probe: bool,
    last_reading_at: datetime | None,
    now: datetime,
) -> tuple[str, str]:
    """Honest (source_confidence, explanation) for the farm-summary aggregate view.

    The farm summary does not compute the full live probe snapshot per sector, so
    freshness is derived from the probe's stored ``last_reading_at`` using the
    canonical staleness thresholds — never fabricated as "fresh"/"no_probe" from
    the recommendation snapshot.
    """
    if not has_probe:
        return (
            "no_probe",
            "Sem sondas configuradas — resumo baseado em balanço hídrico e meteorologia.",
        )
    if last_reading_at is None:
        return (
            "forecast_only",
            "Sonda configurada mas ainda sem leituras — sem leitura real do solo.",
        )
    hours = (now - _ensure_utc(last_reading_at)).total_seconds() / 3600
    if hours > PROBE_VERY_STALE_H:
        return (
            "forecast_only",
            f"Sonda sem comunicação há {hours:.0f}h — sem leitura real recente do solo.",
        )
    if hours > PROBE_STALE_H:
        return (
            "stale",
            f"Última leitura da sonda há {hours:.0f}h — o estado do solo pode ter mudado.",
        )
    return (
        "fresh",
        f"Leitura da sonda recente (há {hours:.0f}h) — estado hídrico do solo actualizado.",
    )


def _source_confidence_and_explanation(probe_live: dict | None) -> tuple[str, str]:
    """Derive (source_confidence, data_quality_explanation) from the live probe snapshot."""
    if probe_live is None:
        return (
            "no_probe",
            "Sem sondas configuradas — recomendação baseada exclusivamente em "
            "balanço hídrico e dados meteorológicos.",
        )

    h = probe_live.get("hours_since_any_reading")
    if h is None:
        return (
            "fresh",
            "Dados da sonda disponíveis — leitura directa do estado hídrico do solo.",
        )

    if h > 24:
        return (
            "forecast_only",
            f"Sonda sem comunicação há {h:.0f}h — estimativa de humidade baseada "
            f"no modelo, sem leitura real do solo.",
        )
    if h > 6:
        return (
            "stale",
            f"Última leitura da sonda há {fmt_pt(h)}h — o estado actual do solo pode "
            f"ter mudado entretanto.",
        )

    # Fresh — express in minutes when < 1 h
    if h < 1:
        mins = round(h * 60)
        time_str = f"há {mins} min"
    else:
        time_str = f"há {fmt_pt(h)}h"
    return (
        "fresh",
        f"Dados da sonda actuais ({time_str}) — leitura directa do estado hídrico do solo.",
    )


async def build_canonical_probe_state(
    eng_ctx: SectorContext,
    db: AsyncSession,
) -> dict | None:
    """Build the single live probe representation used by every AI context path."""
    snapshot = await interpret_probes(eng_ctx, db)
    rootzone = snapshot.rootzone
    if not rootzone.has_data:
        return None

    depths: list[dict] = []
    for depth in rootzone.depth_statuses:
        latest = depth.readings[-1] if depth.readings else None
        depths.append(
            {
                "depth_cm": depth.depth_cm,
                "vwc": round(depth.latest_vwc, 4) if depth.latest_vwc is not None else None,
                "latest_reading_at": latest.timestamp.isoformat() if latest else None,
                "hours_since_reading": (
                    round(depth.hours_since_last, 1) if depth.hours_since_last is not None else None
                ),
                "quality": depth.quality,
                "quality_flag": latest.quality_flag if latest else None,
            }
        )

    return {
        "probe_ids": list(snapshot.probe_ids),
        "swc_weighted_avg": (
            round(rootzone.swc_current, 4) if rootzone.swc_current is not None else None
        ),
        "swc_source": rootzone.swc_source,
        "hours_since_any_reading": (
            round(rootzone.hours_since_any_reading, 1)
            if rootzone.hours_since_any_reading is not None
            else None
        ),
        "all_depths_ok": rootzone.all_depths_ok,
        "depths": depths,
        "anomalies": snapshot.anomalies_detected,
    }


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
                reasons.append(
                    {
                        "category": r.category,
                        "message": r.message_pt,
                    }
                )

            # Extract inputs from computation_log / inputs_snapshot
            snap = rec.inputs_snapshot or {}
            depletion_mm = snap.get("depletion_mm")
            taw_mm = snap.get("taw_mm")
            raw_mm = snap.get("raw_mm")
            swc = snap.get("swc_current")
            et0_mm = snap.get("et0_mm")
            temp_max = snap.get("temperature_max_c")
            rain_24h = snap.get("rainfall_mm", 0.0)
            rain_48h = snap.get("forecast_rain_next_48h", 0.0)
        snapshot_context = _recommendation_snapshot_context(rec) if rec else {}

        # Irrigation history
        irrig_ctx = await build_irrigation_context(sector_id, db)
        last_irrig_date = (
            irrig_ctx.last_irrigation_at.strftime("%Y-%m-%d")
            if irrig_ctx.last_irrigation_at
            else None
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

        # Live probe snapshot — independent of recommendation age and shared with
        # the extended structured agronomic context.
        probe_live = await build_canonical_probe_state(eng_ctx, db)

        src_conf, dqe = _source_confidence_and_explanation(probe_live)

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
            recommendation_id=rec.id if rec else None,
            recommendation_action=rec.action if rec else None,
            recommendation_is_accepted=rec.is_accepted if rec else None,
            # Only expose depth/runtime when action is actually "irrigate" —
            # a non-zero depth on a "no_irrigation" decision confuses the LLM.
            irrigation_depth_mm=(
                rec.irrigation_depth_mm if rec and rec.action == "irrigate" else None
            ),
            runtime_minutes=(
                rec.irrigation_runtime_min if rec and rec.action == "irrigate" else None
            ),
            confidence_score=rec.confidence_score if rec else None,
            confidence_level=rec.confidence_level if rec else None,
            reasons=reasons,
            rootzone_depletion_mm=depletion_mm,
            rootzone_taw_mm=taw_mm,
            rootzone_raw_mm=raw_mm,
            rootzone_swc=swc,
            today_etc_mm=snapshot_context.get("etc_mm"),
            rainfall_effective_mm=snapshot_context.get("rain_effective_mm"),
            rain_skip_applies=snapshot_context.get("rain_skip_applies"),
            swc_source=snapshot_context.get("swc_source"),
            swc_model=snapshot_context.get("swc_model"),
            fc_calibration=snapshot_context.get("fc_calibration"),
            dose_band=snapshot_context.get("dose_band"),
            dose_source=snapshot_context.get("dose_source"),
            dose_presentation=snapshot_context.get("dose_presentation"),
            stress_projection=snapshot_context.get("stress_projection"),
            confidence_penalties=snapshot_context.get("confidence_penalties"),
            today_et0_mm=et0_mm,
            today_temp_max_c=temp_max,
            rainfall_last_24h_mm=rain_24h or 0.0,
            forecast_rain_next_48h_mm=rain_48h or 0.0,
            last_irrigation_date=last_irrig_date,
            total_irrigation_7d_mm=irrig_ctx.total_applied_7d_mm,
            active_alerts=active_alerts,
            probe_live=probe_live,
            source_confidence=src_conf,
            data_quality_explanation=dqe,
            generated_at=rec.generated_at.isoformat() if rec else None,
        )

    async def build_sector_ai_context(
        self,
        sector_id: str,
        db: AsyncSession,
        *,
        compact: bool = False,
    ) -> SectorAIContextV2:
        """Build the versioned context used by all new sector-scoped AI surfaces."""
        return await build_sector_ai_context_v2(sector_id, db, compact=compact)

    async def build_farm_context(self, farm_id: str, db: AsyncSession) -> FarmAssistantContext:
        farm = await db.get(Farm, farm_id)
        farm_name = farm.name if farm else farm_id
        location = (
            {"lat": farm.location_lat, "lon": farm.location_lon, "region": farm.region}
            if farm
            else None
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

        # Farm summaries use a bounded set of aggregate queries instead of calling
        # build_sector_context once per sector (77 serial builds on Innoliva).
        sector_contexts = await self._build_farm_sector_contexts(farm_id, db)

        # Setup completion
        total = len(sector_contexts)
        if total > 0:
            configured = sum(
                1
                for s in sector_contexts
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
        return json.dumps(
            asdict(ctx),
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )

    async def _build_farm_sector_contexts(
        self,
        farm_id: str,
        db: AsyncSession,
    ) -> list[SectorAssistantContext]:
        sectors = (
            (
                await db.execute(
                    select(Sector)
                    .join(Plot, Sector.plot_id == Plot.id)
                    .where(
                        Plot.farm_id == farm_id,
                        Plot.is_archived.is_(False),
                        Sector.is_archived.is_(False),
                    )
                    .order_by(Sector.name)
                )
            )
            .scalars()
            .all()
        )
        if not sectors:
            return []

        sector_ids = [sector.id for sector in sectors]
        plots = {
            row.id: row
            for row in (
                await db.execute(select(Plot).where(Plot.id.in_({row.plot_id for row in sectors})))
            ).scalars()
        }
        recommendations = (
            (
                await db.execute(
                    select(Recommendation)
                    .where(Recommendation.sector_id.in_(sector_ids))
                    .distinct(Recommendation.sector_id)
                    .order_by(
                        Recommendation.sector_id,
                        Recommendation.generated_at.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        rec_by_sector = {row.sector_id: row for row in recommendations}
        rec_ids = [row.id for row in recommendations]

        reasons_by_rec: dict[str, list[dict]] = defaultdict(list)
        if rec_ids:
            reason_rows = (
                (
                    await db.execute(
                        select(RecommendationReason)
                        .where(RecommendationReason.recommendation_id.in_(rec_ids))
                        .order_by(
                            RecommendationReason.recommendation_id,
                            RecommendationReason.order,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in reason_rows:
                reasons_by_rec[row.recommendation_id].append(
                    {"category": row.category, "message": row.message_pt}
                )

        configured_systems = set(
            (
                await db.execute(
                    select(IrrigationSystem.sector_id).where(
                        IrrigationSystem.sector_id.in_(sector_ids)
                    )
                )
            ).scalars()
        )
        configured_profiles = set(
            (
                await db.execute(
                    select(SectorCropProfile.sector_id).where(
                        SectorCropProfile.sector_id.in_(sector_ids)
                    )
                )
            ).scalars()
        )
        alerts_by_sector: dict[str, list[dict]] = defaultdict(list)
        alert_rows = (
            (
                await db.execute(
                    select(Alert)
                    .where(
                        Alert.sector_id.in_(sector_ids),
                        Alert.is_active.is_(True),
                    )
                    .order_by(Alert.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for row in alert_rows:
            if len(alerts_by_sector[row.sector_id]) < 5:
                alerts_by_sector[row.sector_id].append(
                    {
                        "severity": row.severity,
                        "title": row.title_pt,
                        "description": row.description_pt,
                    }
                )

        # Real irrigation history (7-day applied total + last event date) — never
        # fabricate 0.0/None, which would tell the farm-summary LLM every sector
        # applied nothing. One aggregate query for all sectors.
        now = datetime.now(UTC)
        irrig_cutoff = now - timedelta(days=7)
        irrig_by_sector = {
            row[0]: (row[1], row[2])
            for row in (
                await db.execute(
                    select(
                        IrrigationEvent.sector_id,
                        func.max(IrrigationEvent.start_time),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        IrrigationEvent.start_time >= irrig_cutoff,
                                        IrrigationEvent.applied_mm,
                                    ),
                                    else_=0.0,
                                )
                            ),
                            0.0,
                        ),
                    )
                    .where(IrrigationEvent.sector_id.in_(sector_ids))
                    .group_by(IrrigationEvent.sector_id)
                )
            ).all()
        }
        # Probe freshness from the stored last_reading_at — a sector with a probe
        # whose reading is stale must not be reported as "fresh" or "no_probe".
        probe_last_by_sector = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(Probe.sector_id, func.max(Probe.last_reading_at))
                    .where(Probe.sector_id.in_(sector_ids))
                    .group_by(Probe.sector_id)
                )
            ).all()
        }

        contexts: list[SectorAssistantContext] = []
        for sector in sectors:
            rec = rec_by_sector.get(sector.id)
            snapshot = rec.inputs_snapshot or {} if rec else {}
            computation_log = rec.computation_log or {} if rec else {}
            plot = plots.get(sector.plot_id)
            soil_configured = bool(
                plot and plot.field_capacity is not None and plot.wilting_point is not None
            )
            missing: list[str] = []
            if not soil_configured:
                missing.append("soil FC/PWP")
            if sector.id not in configured_systems:
                missing.append("irrigation system")
            if sector.id not in configured_profiles:
                missing.append("no crop profile")
            action = _enum_value(rec.action) if rec else None
            last_irrig_start, total_irrig_7d = irrig_by_sector.get(sector.id, (None, 0.0))
            probe_confidence, probe_explanation = _farm_probe_confidence(
                has_probe=sector.id in probe_last_by_sector,
                last_reading_at=probe_last_by_sector.get(sector.id),
                now=now,
            )
            contexts.append(
                SectorAssistantContext(
                    sector_id=sector.id,
                    sector_name=sector.name,
                    crop_type=sector.crop_type,
                    variety=sector.variety,
                    phenological_stage=sector.current_phenological_stage,
                    area_ha=sector.area_ha,
                    config_status={
                        "soil": "configured" if soil_configured else "defaulted",
                        "irrigation_system": (
                            "configured" if sector.id in configured_systems else "missing"
                        ),
                        "phenological_stage": (
                            "configured" if sector.current_phenological_stage else "not_set"
                        ),
                        "crop_profile": (
                            "configured" if sector.id in configured_profiles else "missing"
                        ),
                    },
                    defaults_used=[],
                    missing_config=missing,
                    recommendation_id=rec.id if rec else None,
                    recommendation_action=action,
                    recommendation_is_accepted=rec.is_accepted if rec else None,
                    irrigation_depth_mm=(
                        rec.irrigation_depth_mm if rec and action == "irrigate" else None
                    ),
                    runtime_minutes=(
                        rec.irrigation_runtime_min if rec and action == "irrigate" else None
                    ),
                    confidence_score=rec.confidence_score if rec else None,
                    confidence_level=(_enum_value(rec.confidence_level) if rec else None),
                    reasons=reasons_by_rec.get(rec.id, []) if rec else [],
                    rootzone_depletion_mm=snapshot.get("depletion_mm"),
                    rootzone_taw_mm=snapshot.get("taw_mm"),
                    rootzone_raw_mm=snapshot.get("raw_mm"),
                    rootzone_swc=snapshot.get("swc_current"),
                    today_etc_mm=snapshot.get("etc_mm"),
                    rainfall_effective_mm=snapshot.get("rain_effective_mm"),
                    rain_skip_applies=snapshot.get("rain_skip_applies"),
                    swc_source=snapshot.get("swc_source"),
                    swc_model=snapshot.get("swc_model"),
                    fc_calibration=snapshot.get("fc_calibration"),
                    dose_band=snapshot.get("dose_band"),
                    dose_source=snapshot.get("dose_source"),
                    dose_presentation=snapshot.get("dose_presentation"),
                    stress_projection=snapshot.get("stress_projection"),
                    confidence_penalties=computation_log.get("confidence_penalties"),
                    today_et0_mm=snapshot.get("et0_mm"),
                    today_temp_max_c=snapshot.get("temperature_max_c"),
                    rainfall_last_24h_mm=snapshot.get("rainfall_mm") or 0.0,
                    forecast_rain_next_48h_mm=(snapshot.get("forecast_rain_next_48h") or 0.0),
                    last_irrigation_date=(
                        last_irrig_start.strftime("%Y-%m-%d") if last_irrig_start else None
                    ),
                    total_irrigation_7d_mm=round(total_irrig_7d or 0.0, 2),
                    active_alerts=alerts_by_sector.get(sector.id, []),
                    probe_live=None,
                    source_confidence=probe_confidence,
                    data_quality_explanation=probe_explanation,
                    generated_at=rec.generated_at.isoformat() if rec else None,
                )
            )
        return contexts


# ---------------------------------------------------------------------------
# Structured agronomic context for LLM grounding
# ---------------------------------------------------------------------------


async def get_probe_diagnostics(probe_id: str, db: AsyncSession) -> dict:
    """Per-probe diagnostics: depth freshness, latest readings, ingestion telemetry."""
    probe = await db.get(Probe, probe_id)
    if probe is None:
        return {"error": "probe_not_found"}

    depths = (
        (await db.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe_id)))
        .scalars()
        .all()
    )
    depth_info: list[dict] = []
    for d in sorted(depths, key=lambda x: x.depth_cm):
        depth_info.append(
            {
                "depth_cm": d.depth_cm,
                "sensor_type": d.sensor_type,
                "last_reading_at": d.last_reading_at.isoformat() if d.last_reading_at else None,
                "last_quality_flag": d.last_quality_flag,
                "last_unit": d.last_unit,
                "readings_count_total": d.readings_count_total,
                "data_status": d.data_status,
            }
        )

    # Most recent ingestion run for this probe
    last_run = (
        await db.execute(
            select(ProviderIngestionRun)
            .where(ProviderIngestionRun.probe_id == probe_id)
            .order_by(ProviderIngestionRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_run_info = None
    if last_run is not None:
        last_run_info = {
            "provider": last_run.provider,
            "started_at": last_run.started_at.isoformat(),
            "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
            "status": last_run.status,
            "latency_ms": last_run.latency_ms,
            "inserted": last_run.inserted,
            "skipped_duplicate": last_run.skipped_duplicate,
            "skipped_unknown_depth": last_run.skipped_unknown_depth,
            "flagged_invalid": last_run.flagged_invalid,
            "flagged_suspect": last_run.flagged_suspect,
            "error_message": last_run.error_message,
        }

    return {
        "probe_id": probe.id,
        "external_id": probe.external_id,
        "health_status": probe.health_status,
        "last_reading_at": probe.last_reading_at.isoformat() if probe.last_reading_at else None,
        "depths": depth_info,
        "last_ingestion_run": last_run_info,
    }


async def get_sector_water_events(sector_id: str, db: AsyncSession, days: int = 14) -> list[dict]:
    """Return persisted water events for a sector over the last N days."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        (
            await db.execute(
                select(DetectedWaterEvent)
                .where(
                    DetectedWaterEvent.sector_id == sector_id,
                    DetectedWaterEvent.timestamp >= since,
                )
                .order_by(DetectedWaterEvent.timestamp.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "probe_id": r.probe_id,
            "timestamp": r.timestamp.isoformat(),
            "kind": r.kind,
            "confidence": r.confidence,
            "score": round(r.score, 3),
            "depths_cm": list(r.depths_cm or []),
            "delta_vwc": round(r.delta_vwc, 4),
            "rainfall_mm": r.rainfall_mm,
            "irrigation_mm": r.irrigation_mm,
            "status": r.status,
            "message": r.message,
        }
        for r in rows
    ]


async def get_sector_water_balance(sector_id: str, db: AsyncSession) -> dict:
    """Return the most recent recommendation's water-balance snapshot."""
    rec = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector_id)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if rec is None:
        return {"available": False}
    snap = rec.inputs_snapshot or {}
    return {
        "available": True,
        "generated_at": rec.generated_at.isoformat(),
        "depletion_mm": snap.get("depletion_mm"),
        "taw_mm": snap.get("taw_mm"),
        "raw_mm": snap.get("raw_mm"),
        "swc_current": snap.get("swc_current"),
        "et0_mm": snap.get("et0_mm"),
        "kc": snap.get("kc"),
        "rainfall_mm": snap.get("rainfall_mm"),
        "forecast_rain_next_48h": snap.get("forecast_rain_next_48h"),
        "dose_band": snap.get("dose_band"),
        "dose_source": snap.get("dose_source"),
        "dose_presentation": snap.get("dose_presentation"),
        **_recommendation_snapshot_context(rec),
    }


def _recommendation_snapshot_context(rec: Recommendation) -> dict:
    """Fields persisted by the engine that the AI must pass through unchanged."""
    snap = rec.inputs_snapshot or {}
    computation_log = rec.computation_log or {}
    keys = (
        "etc_mm",
        "rain_effective_mm",
        "rain_skip_applies",
        "swc_source",
        "swc_model",
        "fc_calibration",
        "dose_band",
        "dose_source",
        "dose_presentation",
        "stress_projection",
    )
    return {
        **{key: snap.get(key) for key in keys},
        "confidence_penalties": computation_log.get("confidence_penalties"),
    }


async def get_weather_summary(
    farm_id: str,
    db: AsyncSession,
    obs_days: int = 7,
    fc_days: int = 3,
    plot_id: str | None = None,
) -> dict:
    """Recent observations + short-term forecast in the engine-resolved scope."""
    now = datetime.now(UTC)
    obs_since = now - timedelta(days=obs_days)
    weather_plot_id = await resolve_weather_plot_id(farm_id, db, plot_id)
    obs_scope = (
        WeatherObservation.plot_id == weather_plot_id
        if weather_plot_id is not None
        else WeatherObservation.plot_id.is_(None)
    )
    forecast_scope = (
        WeatherForecast.plot_id == weather_plot_id
        if weather_plot_id is not None
        else WeatherForecast.plot_id.is_(None)
    )
    obs = (
        (
            await db.execute(
                select(WeatherObservation)
                .where(
                    WeatherObservation.farm_id == farm_id,
                    WeatherObservation.timestamp >= obs_since,
                    obs_scope,
                )
                .order_by(WeatherObservation.timestamp.desc())
                .limit(obs_days * 4)
            )
        )
        .scalars()
        .all()
    )
    fc = (
        (
            await db.execute(
                select(WeatherForecast)
                .where(WeatherForecast.farm_id == farm_id, forecast_scope)
                .order_by(WeatherForecast.forecast_date)
                .limit(fc_days)
            )
        )
        .scalars()
        .all()
    )
    return {
        "recent_observations": [
            {
                "timestamp": o.timestamp.isoformat(),
                "temperature_max_c": o.temperature_max_c,
                "temperature_min_c": o.temperature_min_c,
                "humidity_pct": o.humidity_pct,
                "rainfall_mm": o.rainfall_mm,
                "et0_mm": o.et0_mm,
            }
            for o in obs
        ],
        "forecast": [
            {
                "date": f.forecast_date.isoformat(),
                "temperature_max_c": f.temperature_max_c,
                "temperature_min_c": f.temperature_min_c,
                "rainfall_mm": f.rainfall_mm,
                "rainfall_probability_pct": f.rainfall_probability_pct,
                "et0_mm": f.et0_mm,
            }
            for f in fc
        ],
    }


async def get_recommendation_history(
    sector_id: str, db: AsyncSession, limit: int = 5
) -> list[dict]:
    """Return the most recent recommendations for a sector."""
    rows = (
        (
            await db.execute(
                select(Recommendation)
                .where(Recommendation.sector_id == sector_id)
                .order_by(Recommendation.generated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "generated_at": r.generated_at.isoformat(),
            "action": r.action,
            "irrigation_depth_mm": r.irrigation_depth_mm,
            "irrigation_runtime_min": r.irrigation_runtime_min,
            "confidence_score": r.confidence_score,
            "confidence_level": r.confidence_level,
            "is_accepted": r.is_accepted,
        }
        for r in rows
    ]


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _context_block(
    *,
    observed_at: str | None,
    source: str,
    units: dict[str, str],
    **data,
) -> dict:
    """Add mandatory provenance metadata to one canonical context block."""
    return {
        "observed_at": observed_at,
        "source": source,
        "units": units,
        **data,
    }


def _outcome_row(row: RecommendationOutcome) -> dict:
    return {
        "id": row.id,
        "recommendation_id": row.recommendation_id,
        "evaluated_at": row.evaluated_at.isoformat(),
        "status": row.status,
        "recommended_depth_mm": row.recommended_depth_mm,
        "actual_applied_mm": row.actual_applied_mm,
        "dose_error_mm": row.dose_error_mm,
        "dose_error_pct": row.dose_error_pct,
        "pre_irrigation_vwc": row.pre_irrigation_vwc,
        "post_irrigation_vwc": row.post_irrigation_vwc,
        "probe_response_delta": row.probe_response_delta,
        "event_source": (
            "manual"
            if row.irrigation_event_id
            else "flowmeter_detected"
            if row.detected_event_id
            else None
        ),
        "details": row.details or {},
    }


def _calibration_run_row(row: ProbeCalibrationRun) -> dict:
    return {
        "id": row.id,
        "observed_fc": row.observed_fc,
        "observed_refill": row.observed_refill,
        "method": row.method,
        "num_cycles": row.num_cycles,
        "consistency": row.consistency,
        "window_days": row.window_days,
        "computed_at": row.computed_at.isoformat(),
        "source": row.source,
        "status": row.status,
        "previous_fc": row.previous_fc,
        "previous_refill": row.previous_refill,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


async def build_sector_ai_context_v2(
    sector_id: str,
    db: AsyncSession,
    *,
    compact: bool = False,
) -> SectorAIContextV2:
    """Build the canonical sector AI context from engine-owned sources.

    The latest recommendation's immutable snapshot owns the decision and water
    balance. Live resolvers add current weather, probe, calibration, and crop
    state without silently recomputing the historical recommendation.
    """
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    sector = await db.get(Sector, sector_id)
    if sector is None:
        raise ValueError(f"sector_not_found:{sector_id}")
    plot = await db.get(Plot, sector.plot_id) if sector.plot_id else None
    farm = await db.get(Farm, plot.farm_id) if plot else None

    crop_profile = (
        await db.execute(select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id))
    ).scalar_one_or_none()
    irrigation_system = (
        await db.execute(select(IrrigationSystem).where(IrrigationSystem.sector_id == sector_id))
    ).scalar_one_or_none()
    engine_context = await build_sector_context(sector_id, db)
    soil_bounds = await resolve_sector_soil_bounds(sector_id, db, plot=plot)

    recommendations = (
        (
            await db.execute(
                select(Recommendation)
                .where(Recommendation.sector_id == sector_id)
                .order_by(Recommendation.generated_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    latest = recommendations[0] if recommendations else None
    snapshot = latest.inputs_snapshot or {} if latest else {}
    computation_log = latest.computation_log or {} if latest else {}
    decision_at = latest.generated_at.isoformat() if latest else None
    reasons = []
    if latest:
        reason_rows = (
            (
                await db.execute(
                    select(RecommendationReason)
                    .where(RecommendationReason.recommendation_id == latest.id)
                    .order_by(RecommendationReason.order)
                )
            )
            .scalars()
            .all()
        )
        reasons = [
            {
                "category": _enum_value(row.category),
                "message": row.message_pt,
            }
            for row in reason_rows
        ]

    recommendation_history = [
        {
            "id": row.id,
            "generated_at": row.generated_at.isoformat(),
            "action": _enum_value(row.action),
            "irrigation_depth_mm": row.irrigation_depth_mm,
            "irrigation_runtime_min": row.irrigation_runtime_min,
            "confidence_score": row.confidence_score,
            "confidence_level": _enum_value(row.confidence_level),
            "is_accepted": row.is_accepted,
        }
        for row in recommendations
    ]

    probes = (await db.execute(select(Probe).where(Probe.sector_id == sector_id))).scalars().all()
    probe_live = await build_canonical_probe_state(engine_context, db)
    latest_readings = probe_live.get("depths", []) if probe_live else []
    diagnostics = []
    if not compact:
        for probe in probes:
            diagnostics.append(await get_probe_diagnostics(probe.id, db))
    fresh_depths = sum(1 for row in latest_readings if row.get("quality") == "ok")
    stale_depths = sum(
        1
        for row in latest_readings
        if row.get("quality") in ("stale", "missing", "needs_vwc_calibration")
    )
    probe_observed_at = max(
        (row["latest_reading_at"] for row in latest_readings if row.get("latest_reading_at")),
        default=None,
    )

    weather = (
        await get_weather_summary(farm.id, db, plot_id=plot.id if plot else None)
        if farm
        else {"recent_observations": [], "forecast": []}
    )
    weather_observed_at = (
        weather["recent_observations"][0]["timestamp"] if weather["recent_observations"] else None
    )
    if compact:
        weather = {
            "recent_observations": weather["recent_observations"][:1],
            "forecast": weather["forecast"][:2],
        }

    since = now - timedelta(days=14)
    manual_events = (
        (
            await db.execute(
                select(IrrigationEvent)
                .where(IrrigationEvent.sector_id == sector_id, IrrigationEvent.start_time >= since)
                .order_by(IrrigationEvent.start_time.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    detected_events = await get_sector_water_events(sector_id, db, days=14)
    flowmeter_events = (
        (
            await db.execute(
                select(IrrigationEventDetected)
                .where(
                    IrrigationEventDetected.sector_id == sector_id,
                    IrrigationEventDetected.start_time >= since,
                )
                .order_by(IrrigationEventDetected.start_time.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    fingerprint = (
        await db.execute(
            select(IrrigationFingerprint).where(IrrigationFingerprint.sector_id == sector_id)
        )
    ).scalar_one_or_none()
    manual_rows = [
        {
            "id": row.id,
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat() if row.end_time else None,
            "duration_minutes": row.duration_minutes,
            "applied_mm": row.applied_mm,
            "source": row.source,
            "recommendation_id": row.recommendation_id,
        }
        for row in manual_events
    ]
    flowmeter_rows = [
        {
            "id": row.id,
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat(),
            "duration_minutes": row.duration_minutes,
            "applied_mm": round(row.total_m3_ha / 10.0, 3),
            "total_m3_ha": row.total_m3_ha,
            "source": "flowmeter_detected",
        }
        for row in flowmeter_events
    ]
    habitual_dose = (
        {
            "typical_event_net_mm": fingerprint.typical_event_net_mm,
            "typical_event_duration_min": fingerprint.typical_event_duration_min,
            "n_events": fingerprint.n_events,
            "consistency": fingerprint.consistency,
            "confidence": fingerprint.confidence,
            "window_days": fingerprint.window_days,
            "computed_at": fingerprint.computed_at.isoformat(),
        }
        if fingerprint
        else None
    )
    execution_times = [
        *(row["start_time"] for row in manual_rows),
        *(row["timestamp"] for row in detected_events),
        *(row["start_time"] for row in flowmeter_rows),
    ]

    outcome_rows = (
        (
            await db.execute(
                select(RecommendationOutcome)
                .where(RecommendationOutcome.sector_id == sector_id)
                .order_by(RecommendationOutcome.evaluated_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    outcomes = [_outcome_row(row) for row in outcome_rows]

    calibration = (
        await db.execute(select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id))
    ).scalar_one_or_none()
    calibration_runs = (
        (
            await db.execute(
                select(ProbeCalibrationRun)
                .where(ProbeCalibrationRun.sector_id == sector_id)
                .order_by(ProbeCalibrationRun.computed_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    calibration_meta = soil_bounds.calibration or {}
    active_calibration = (
        {
            "observed_fc": calibration.observed_fc,
            "observed_refill": calibration.observed_refill,
            "method": calibration.method,
            "num_cycles": calibration.num_cycles,
            "consistency": calibration.consistency,
            "window_days": calibration.window_days,
            "computed_at": calibration.computed_at.isoformat(),
        }
        if calibration
        else None
    )
    run_rows = [_calibration_run_row(row) for row in calibration_runs]

    from app.engine.gdd_tracker import GDDTracker

    gdd_status = await GDDTracker().compute_accumulated_gdd(
        sector_id,
        db,
        scp_stages=crop_profile.stages if crop_profile else None,
    )
    gdd = asdict(gdd_status) if gdd_status else None

    observation_rows = (
        (
            await db.execute(
                select(FieldObservation)
                .where(
                    FieldObservation.sector_id == sector_id,
                    or_(
                        FieldObservation.expires_at.is_(None),
                        FieldObservation.expires_at > now,
                    ),
                )
                .order_by(FieldObservation.observed_at.desc())
                .limit(5 if compact else 20)
            )
        )
        .scalars()
        .all()
    )
    field_observations = [
        {
            "id": row.id,
            "type": row.observation_type,
            "text": row.text,
            "structured_value": row.structured_value,
            "observed_at": row.observed_at.isoformat(),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "verified": row.is_verified,
            "source": "user_field_observation",
        }
        for row in observation_rows
    ]

    alert_rows = (
        (
            await db.execute(
                select(Alert)
                .where(Alert.sector_id == sector_id, Alert.is_active == True)  # noqa: E712
                .order_by(Alert.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    alerts = [
        {
            "id": row.id,
            "type": _enum_value(row.alert_type),
            "severity": _enum_value(row.severity),
            "source": row.source,
            "rule_key": row.rule_key,
            "title": row.title_pt,
            "description": row.description_pt,
            "created_at": row.created_at.isoformat(),
        }
        for row in alert_rows
    ]

    limitations: list[str] = []
    if not probes:
        limitations.append("Sector has no probes — no direct soil moisture signal.")
    if latest_readings and stale_depths == len(latest_readings):
        limitations.append("All probe depths are stale; reasoning relies on water balance only.")
    if irrigation_system is None:
        limitations.append(
            "Irrigation system is not configured — applied-mm conversions use defaults."
        )
    if crop_profile is None:
        limitations.append("No sector crop profile attached — Kc and root depth use defaults.")
    if not weather["recent_observations"]:
        limitations.append("No recent weather observations are available in the sector scope.")
    if latest is None:
        limitations.append("No water-balance snapshot has been generated for this sector.")

    scope = _context_block(
        observed_at=now_iso,
        source="active farm/plot/sector configuration",
        units={"area_ha": "ha", "application_rate_mm_h": "mm/h"},
        detail_level="compact" if compact else "full",
        sector={
            "id": sector.id,
            "name": sector.name,
            "crop_type": sector.crop_type,
            "variety": sector.variety,
            "area_ha": sector.area_ha,
            "current_phenological_stage": sector.current_phenological_stage,
            "irrigation_strategy": sector.irrigation_strategy,
            "deficit_factor": sector.deficit_factor,
        },
        plot=(
            {"id": plot.id, "name": plot.name, "soil_texture": plot.soil_texture} if plot else None
        ),
        farm=(
            {
                "id": farm.id,
                "name": farm.name,
                "region": farm.region,
                "timezone": farm.timezone,
                "location_lat": farm.location_lat,
                "location_lon": farm.location_lon,
            }
            if farm
            else None
        ),
        irrigation_system=(
            {
                "system_type": irrigation_system.system_type,
                "application_rate_mm_h": irrigation_system.application_rate_mm_h,
                "efficiency": irrigation_system.efficiency,
                "distribution_uniformity": irrigation_system.distribution_uniformity,
                "max_runtime_hours": irrigation_system.max_runtime_hours,
            }
            if irrigation_system
            else None
        ),
    )
    engine_decision = _context_block(
        observed_at=decision_at,
        source="recommendation.inputs_snapshot",
        units={"irrigation_depth_mm": "mm", "irrigation_runtime_min": "min"},
        available=latest is not None,
        recommendation_id=latest.id if latest else None,
        action=_enum_value(latest.action) if latest else None,
        irrigation_depth_mm=latest.irrigation_depth_mm if latest else None,
        irrigation_runtime_min=latest.irrigation_runtime_min if latest else None,
        suggested_start_time=latest.suggested_start_time if latest else None,
        confidence_score=latest.confidence_score if latest else None,
        confidence_level=_enum_value(latest.confidence_level) if latest else None,
        confidence_penalties=computation_log.get("confidence_penalties"),
        is_accepted=latest.is_accepted if latest else None,
        reasons=reasons,
        dose_band=snapshot.get("dose_band"),
        dose_source=snapshot.get("dose_source"),
        dose_presentation=snapshot.get("dose_presentation"),
    )
    if not compact:
        engine_decision["history"] = recommendation_history

    water_balance = _context_block(
        observed_at=decision_at,
        source="recommendation.inputs_snapshot",
        units={
            "depletion_mm": "mm",
            "taw_mm": "mm",
            "raw_mm": "mm",
            "swc_current": "m3/m3",
            "et0_mm": "mm/day",
            "etc_mm": "mm/day",
            "rainfall_mm": "mm",
            "rain_effective_mm": "mm",
        },
        available=latest is not None,
        depletion_mm=snapshot.get("depletion_mm"),
        taw_mm=snapshot.get("taw_mm"),
        raw_mm=snapshot.get("raw_mm"),
        swc_current=snapshot.get("swc_current"),
        swc_source=snapshot.get("swc_source"),
        swc_model=snapshot.get("swc_model"),
        et0_mm=snapshot.get("et0_mm"),
        kc=snapshot.get("kc"),
        etc_mm=snapshot.get("etc_mm"),
        rainfall_mm=snapshot.get("rainfall_mm"),
        rain_effective_mm=snapshot.get("rain_effective_mm"),
        rain_skip_applies=snapshot.get("rain_skip_applies"),
        forecast_rain_next_48h=snapshot.get("forecast_rain_next_48h"),
        fc_calibration=snapshot.get("fc_calibration"),
    )
    probe_state = _context_block(
        observed_at=probe_observed_at,
        source="engine.probe_interpreter",
        units={"vwc": "m3/m3", "depth_cm": "cm", "hours_since_reading": "h"},
        live=probe_live,
        latest_readings=latest_readings,
        data_quality={
            "fresh_depths": fresh_depths,
            "stale_depths": stale_depths,
            "total_depths": len(latest_readings),
        },
    )
    if not compact:
        probe_state["diagnostics"] = diagnostics

    weather_block = _context_block(
        observed_at=weather_observed_at,
        source="engine.weather_scope_resolver",
        units={
            "temperature_max_c": "degC",
            "temperature_min_c": "degC",
            "rainfall_mm": "mm",
            "et0_mm": "mm/day",
        },
        **weather,
    )
    irrigation_execution = _context_block(
        observed_at=max(execution_times, default=None),
        source="manual, probe-detected, and flowmeter-detected irrigation events",
        units={
            "applied_mm": "mm",
            "duration_minutes": "min",
            "total_m3_ha": "m3/ha",
            "typical_event_net_mm": "mm",
        },
        habitual_dose=habitual_dose,
    )
    if compact:
        all_events = sorted(
            [
                *({**row, "event_source": "manual"} for row in manual_rows),
                *({**row, "event_source": "probe_detected"} for row in detected_events),
                *({**row, "event_source": "flowmeter_detected"} for row in flowmeter_rows),
            ],
            key=lambda row: row.get("start_time") or row.get("timestamp") or "",
            reverse=True,
        )
        irrigation_execution["latest_event"] = all_events[0] if all_events else None
    else:
        irrigation_execution.update(
            manual_events=manual_rows,
            probe_detected_events=detected_events,
            flowmeter_detected_events=flowmeter_rows,
        )

    outcomes_block = _context_block(
        observed_at=outcomes[0]["evaluated_at"] if outcomes else None,
        source="recommendation_outcome deterministic evaluator",
        units={
            "recommended_depth_mm": "mm",
            "actual_applied_mm": "mm",
            "dose_error_mm": "mm",
            "dose_error_pct": "%",
            "pre_irrigation_vwc": "m3/m3",
            "post_irrigation_vwc": "m3/m3",
            "probe_response_delta": "m3/m3",
        },
        count=len(outcomes),
        latest=outcomes[0] if outcomes else None,
    )
    if not compact:
        outcomes_block["recent"] = outcomes

    crop_state = _context_block(
        observed_at=decision_at or now_iso,
        source=(
            "sector crop profile, GDD tracker, recommendation snapshot, and user field observations"
        ),
        units={
            "root_depth_mature_m": "m",
            "root_depth_young_m": "m",
            "accumulated_gdd": "degree-days",
            "gdd_to_next_stage": "degree-days",
        },
        profile=(
            {
                "crop_type": crop_profile.crop_type,
                "mad": crop_profile.mad,
                "root_depth_mature_m": crop_profile.root_depth_mature_m,
                "root_depth_young_m": crop_profile.root_depth_young_m,
                "stages": crop_profile.stages if not compact else None,
                "is_customized": crop_profile.is_customized,
            }
            if crop_profile
            else None
        ),
        gdd=gdd,
        stress_projection=snapshot.get("stress_projection"),
        field_observations=field_observations,
    )
    calibration_block = _context_block(
        observed_at=(
            active_calibration["computed_at"]
            if active_calibration
            else calibration_meta.get("computed_at")
        ),
        source="engine.resolve_sector_soil_bounds",
        units={"field_capacity": "m3/m3", "wilting_point": "m3/m3"},
        soil_bounds={
            "field_capacity": soil_bounds.fc,
            "wilting_point": soil_bounds.pwp,
            "soil_texture": plot.soil_texture if plot else None,
            "stone_content_pct": plot.stone_content_pct if plot else None,
            "provenance": {
                "source": soil_bounds.source,
                "stale": bool(calibration_meta.get("stale", False)),
                "computed_at": calibration_meta.get("computed_at"),
            },
        },
        active=active_calibration,
        pending_candidate_count=sum(1 for row in calibration_runs if row.status == "candidate"),
    )
    if not compact:
        calibration_block["runs"] = run_rows

    alerts_and_limitations = _context_block(
        observed_at=alerts[0]["created_at"] if alerts else now_iso,
        source="deterministic alert producers and context completeness checks",
        units={},
        active_alerts=alerts,
        known_limitations=limitations,
        confidence_inputs={
            "fresh_depths": fresh_depths,
            "total_depths": len(latest_readings),
            "stale_depths": stale_depths,
            "has_weather": bool(weather["recent_observations"]),
            "has_forecast": bool(weather["forecast"]),
            "has_water_balance": latest is not None,
            "active_water_events_14d": sum(
                1 for row in detected_events if row.get("status") == "active"
            ),
            "irrigation_system_configured": irrigation_system is not None,
            "crop_profile_configured": crop_profile is not None,
        },
    )

    return SectorAIContextV2(
        scope=scope,
        engine_decision=engine_decision,
        water_balance=water_balance,
        probe_state=probe_state,
        weather=weather_block,
        irrigation_execution=irrigation_execution,
        outcomes=outcomes_block,
        crop_state=crop_state,
        calibration=calibration_block,
        alerts_and_limitations=alerts_and_limitations,
    )


async def _build_legacy_structured_agronomic_context(sector_id: str, db: AsyncSession) -> dict:
    """Build a complete agronomic context dict for LLM grounding.

    Returns a JSON-serialisable dict covering every data surface the LLM is
    allowed to reason over.  Each call hits the DB directly — callers should
    cache when re-using inside a single conversation turn.
    """
    sector = await db.get(Sector, sector_id)
    if sector is None:
        return {"error": "sector_not_found", "sector_id": sector_id}

    plot = await db.get(Plot, sector.plot_id) if sector.plot_id else None
    farm = await db.get(Farm, plot.farm_id) if plot else None
    soil_bounds = await resolve_sector_soil_bounds(sector_id, db, plot=plot)
    calibration_meta = soil_bounds.calibration or {}
    soil_provenance = {
        "source": soil_bounds.source,
        "stale": bool(calibration_meta.get("stale", False)),
        "computed_at": calibration_meta.get("computed_at"),
    }

    crop_profile = (
        await db.execute(select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id))
    ).scalar_one_or_none()
    irrigation_system = (
        await db.execute(select(IrrigationSystem).where(IrrigationSystem.sector_id == sector_id))
    ).scalar_one_or_none()

    # Probes + per-depth diagnostics
    probes = (await db.execute(select(Probe).where(Probe.sector_id == sector_id))).scalars().all()
    probe_diagnostics: list[dict] = []
    for probe in probes:
        diag = await get_probe_diagnostics(probe.id, db)
        probe_diagnostics.append(diag)

    engine_context = await build_sector_context(sector_id, db)
    probe_live = await build_canonical_probe_state(engine_context, db)
    latest_readings = probe_live.get("depths", []) if probe_live else []

    water_events = await get_sector_water_events(sector_id, db, days=14)
    weather = (
        await get_weather_summary(
            farm.id,
            db,
            plot_id=plot.id if plot else None,
        )
        if farm
        else {"recent_observations": [], "forecast": []}
    )
    water_balance = await get_sector_water_balance(sector_id, db)
    recs = await get_recommendation_history(sector_id, db)

    # Data quality scoring across all probes
    fresh_depths = sum(1 for depth in latest_readings if depth.get("quality") == "ok")
    total_depths = len(latest_readings)
    stale_depths = sum(
        1
        for depth in latest_readings
        if depth.get("quality") in ("stale", "missing", "needs_vwc_calibration")
    )

    known_limitations: list[str] = []
    if not probes:
        known_limitations.append("Sector has no probes — no direct soil moisture signal.")
    if total_depths and stale_depths == total_depths:
        known_limitations.append(
            "All probe depths are stale; reasoning relies on water balance only."
        )
    if irrigation_system is None:
        known_limitations.append(
            "Irrigation system is not configured — applied-mm conversions use defaults."
        )
    if crop_profile is None:
        known_limitations.append(
            "No sector crop profile attached — Kc and root depth fall back to defaults."
        )
    if not weather.get("recent_observations"):
        known_limitations.append("No recent weather observations available for this farm.")
    if not water_balance.get("available"):
        known_limitations.append(
            "No water-balance snapshot has been generated yet for this sector."
        )

    confidence_inputs = {
        "fresh_depths": fresh_depths,
        "total_depths": total_depths,
        "stale_depths": stale_depths,
        "has_weather": bool(weather.get("recent_observations")),
        "has_forecast": bool(weather.get("forecast")),
        "has_water_balance": water_balance.get("available", False),
        "active_water_events_14d": sum(1 for e in water_events if e["status"] == "active"),
        "irrigation_system_configured": irrigation_system is not None,
        "crop_profile_configured": crop_profile is not None,
    }

    return {
        "sector": {
            "id": sector.id,
            "name": sector.name,
            "crop_type": sector.crop_type,
            "variety": sector.variety,
            "area_ha": sector.area_ha,
            "current_phenological_stage": sector.current_phenological_stage,
            "irrigation_strategy": sector.irrigation_strategy,
            "deficit_factor": sector.deficit_factor,
        },
        "farm": (
            {
                "id": farm.id,
                "name": farm.name,
                "region": farm.region,
                "timezone": farm.timezone,
                "location_lat": farm.location_lat,
                "location_lon": farm.location_lon,
            }
            if farm
            else None
        ),
        "crop": (
            {
                "crop_type": crop_profile.crop_type,
                "mad": crop_profile.mad,
                "root_depth_mature_m": crop_profile.root_depth_mature_m,
                "root_depth_young_m": crop_profile.root_depth_young_m,
                "stages": crop_profile.stages,
                "is_customized": crop_profile.is_customized,
            }
            if crop_profile
            else None
        ),
        "soil": (
            {
                "field_capacity": soil_bounds.fc,
                "wilting_point": soil_bounds.pwp,
                "soil_texture": plot.soil_texture,
                "stone_content_pct": plot.stone_content_pct,
                "provenance": soil_provenance,
            }
            if plot
            else None
        ),
        "irrigation_system": (
            {
                "system_type": irrigation_system.system_type,
                "application_rate_mm_h": irrigation_system.application_rate_mm_h,
                "efficiency": irrigation_system.efficiency,
                "distribution_uniformity": irrigation_system.distribution_uniformity,
                "max_runtime_hours": irrigation_system.max_runtime_hours,
            }
            if irrigation_system
            else None
        ),
        "probe_summary": {
            "live": probe_live,
            "data_quality": {
                "fresh_depths": fresh_depths,
                "stale_depths": stale_depths,
                "total_depths": total_depths,
            },
            "depths": [d for diag in probe_diagnostics for d in diag.get("depths", [])],
            "latest_readings": latest_readings,
            "diagnostics": probe_diagnostics,
        },
        "water_events": water_events,
        "weather": weather,
        "water_balance": water_balance,
        "recommendation_history": recs,
        "known_limitations": known_limitations,
        "confidence_inputs": confidence_inputs,
    }


def _with_legacy_context_aliases(context: SectorAIContextV2) -> dict:
    """Expose old evidence paths while consumers migrate to the ten V2 blocks."""
    payload = context.to_dict()
    scope = payload["scope"]
    probe = payload["probe_state"]
    execution = payload["irrigation_execution"]
    crop = payload["crop_state"]
    calibration = payload["calibration"]
    alerts = payload["alerts_and_limitations"]
    decision = payload["engine_decision"]
    return {
        **payload,
        "sector": scope.get("sector"),
        "farm": scope.get("farm"),
        "crop": crop.get("profile"),
        "soil": calibration.get("soil_bounds"),
        "irrigation_system": scope.get("irrigation_system"),
        "probe_summary": {
            "live": probe.get("live"),
            "data_quality": probe.get("data_quality", {}),
            "depths": [
                depth
                for diagnostic in probe.get("diagnostics", [])
                for depth in diagnostic.get("depths", [])
            ],
            "latest_readings": probe.get("latest_readings", []),
            "diagnostics": probe.get("diagnostics", []),
        },
        "water_events": execution.get("probe_detected_events", []),
        "weather": payload["weather"],
        "water_balance": payload["water_balance"],
        "recommendation_history": decision.get("history", []),
        "known_limitations": alerts.get("known_limitations", []),
        "confidence_inputs": alerts.get("confidence_inputs", {}),
    }


async def build_structured_agronomic_context(
    sector_id: str,
    db: AsyncSession,
) -> dict:
    """Compatibility projection of the canonical V2 context.

    New code should call :func:`build_sector_ai_context_v2` directly.  The aliases
    keep existing prompt evidence paths valid until P2 changes the response contract.
    """
    try:
        context = await build_sector_ai_context_v2(sector_id, db, compact=False)
    except ValueError as exc:
        if str(exc).startswith("sector_not_found:"):
            return {"error": "sector_not_found", "sector_id": sector_id}
        raise
    return _with_legacy_context_aliases(context)


async def build_sector_change_context(
    sector_id: str,
    db: AsyncSession,
    window_hours: int = 72,
) -> dict:
    """Build a compact before/after context for LLM change analysis."""
    window_hours = max(24, min(window_hours, 168))
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)
    split = now - timedelta(hours=window_hours / 2)

    try:
        current = (await build_sector_ai_context_v2(sector_id, db, compact=False)).to_dict()
    except ValueError as exc:
        if str(exc).startswith("sector_not_found:"):
            return {"error": "sector_not_found", "sector_id": sector_id}
        raise

    probes = (await db.execute(select(Probe).where(Probe.sector_id == sector_id))).scalars().all()

    probe_changes: list[dict] = []
    for probe in probes:
        depths = (
            (await db.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)))
            .scalars()
            .all()
        )
        for depth in sorted(depths, key=lambda d: d.depth_cm):
            rows = (
                (
                    await db.execute(
                        select(ProbeReading)
                        .where(
                            ProbeReading.probe_depth_id == depth.id,
                            ProbeReading.timestamp >= since,
                            ProbeReading.timestamp <= now,
                            ProbeReading.unit == "vwc_m3m3",
                        )
                        .order_by(ProbeReading.timestamp)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                probe_changes.append(
                    {
                        "probe_id": probe.id,
                        "probe_external_id": probe.external_id,
                        "depth_cm": depth.depth_cm,
                        "status": "no_readings_in_window",
                        "data_status": depth.data_status,
                    }
                )
                continue

            previous_values = [_reading_value(r) for r in rows if _ensure_utc(r.timestamp) < split]
            recent_values = [_reading_value(r) for r in rows if _ensure_utc(r.timestamp) >= split]
            previous_values = [v for v in previous_values if v is not None]
            recent_values = [v for v in recent_values if v is not None]
            first_value = _reading_value(rows[0])
            last_value = _reading_value(rows[-1])

            probe_changes.append(
                {
                    "probe_id": probe.id,
                    "probe_external_id": probe.external_id,
                    "depth_cm": depth.depth_cm,
                    "reading_count": len(rows),
                    "first_reading_at": _ensure_utc(rows[0].timestamp).isoformat(),
                    "last_reading_at": _ensure_utc(rows[-1].timestamp).isoformat(),
                    "first_vwc": round(first_value, 4) if first_value is not None else None,
                    "last_vwc": round(last_value, 4) if last_value is not None else None,
                    "delta_vwc": round(last_value - first_value, 4)
                    if first_value is not None and last_value is not None
                    else None,
                    "previous_half_avg_vwc": round(sum(previous_values) / len(previous_values), 4)
                    if previous_values
                    else None,
                    "recent_half_avg_vwc": round(sum(recent_values) / len(recent_values), 4)
                    if recent_values
                    else None,
                    "quality_counts": _quality_counts(rows),
                    "data_status": depth.data_status,
                }
            )

    water_events = (
        (
            await db.execute(
                select(DetectedWaterEvent)
                .where(
                    DetectedWaterEvent.sector_id == sector_id,
                    DetectedWaterEvent.timestamp >= since,
                )
                .order_by(DetectedWaterEvent.timestamp.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    recs = (
        (
            await db.execute(
                select(Recommendation)
                .where(Recommendation.sector_id == sector_id)
                .order_by(Recommendation.generated_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    latest_rec = recs[0] if recs else None
    previous_rec = recs[1] if len(recs) > 1 else None

    weather_observations = [
        observation
        for observation in current["weather"].get("recent_observations", [])
        if _ensure_utc(datetime.fromisoformat(observation["timestamp"])) >= since
    ]
    limitations = current["alerts_and_limitations"].get("known_limitations", [])

    return {
        "analysis_type": "sector_change_analysis",
        "window_hours": window_hours,
        "generated_at": now.isoformat(),
        "sector": current["scope"].get("sector"),
        "current_context": current,
        "current_context_summary": {
            "probe_data_quality": current["probe_state"].get("data_quality"),
            "water_balance": current["water_balance"],
            "known_limitations": limitations,
        },
        "probe_changes": probe_changes,
        "water_event_changes": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "kind": e.kind,
                "status": e.status,
                "confidence": e.confidence,
                "score": round(e.score, 3),
                "depths_cm": list(e.depths_cm or []),
                "delta_vwc": round(e.delta_vwc, 4),
                "rainfall_mm": e.rainfall_mm,
                "irrigation_mm": e.irrigation_mm,
                "message": e.message,
            }
            for e in water_events
        ],
        "recommendation_change": {
            "latest": _recommendation_change_row(latest_rec),
            "previous": _recommendation_change_row(previous_rec),
        },
        "weather_changes": {
            "observations": weather_observations,
            "forecast": current["weather"].get("forecast", []),
        },
        "known_limitations": limitations,
    }


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reading_value(reading: ProbeReading) -> float | None:
    value = reading.calibrated_value if reading.calibrated_value is not None else reading.raw_value
    return float(value) if value is not None else None


def _quality_counts(rows: list[ProbeReading]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.quality_flag] = counts.get(row.quality_flag, 0) + 1
    return counts


def _recommendation_change_row(rec: Recommendation | None) -> dict | None:
    if rec is None:
        return None
    return {
        "id": rec.id,
        "generated_at": rec.generated_at.isoformat(),
        "action": rec.action,
        "irrigation_depth_mm": rec.irrigation_depth_mm,
        "irrigation_runtime_min": rec.irrigation_runtime_min,
        "confidence_score": rec.confidence_score,
        "confidence_level": rec.confidence_level,
        "is_accepted": rec.is_accepted,
        "inputs_snapshot": rec.inputs_snapshot or {},
    }
