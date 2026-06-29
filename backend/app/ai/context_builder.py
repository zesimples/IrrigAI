"""Builds structured context dicts injected into ChatGPT calls.

The LLM never queries the DB — it receives a JSON-serialisable snapshot built here.
Key design: config_status / defaults_used / missing_config propagate from the engine
so the LLM can explain what was inferred vs. user-configured.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.pipeline import (
    build_irrigation_context,
    build_sector_context,
    build_weather_context,
)
from app.engine.probe_interpreter import interpret_probes
from app.models import (
    Alert,
    DetectedWaterEvent,
    Farm,
    IrrigationSystem,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    ProviderIngestionRun,
    Recommendation,
    RecommendationReason,
    Sector,
    SectorCropProfile,
    WeatherForecast,
    WeatherObservation,
)

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
            f"Última leitura da sonda há {h:.1f}h — o estado actual do solo pode "
            f"ter mudado entretanto.",
        )

    # Fresh — express in minutes when < 1 h
    if h < 1:
        mins = round(h * 60)
        time_str = f"há {mins} min"
    else:
        time_str = f"há {h:.1f}h"
    return (
        "fresh",
        f"Dados da sonda actuais ({time_str}) — leitura directa do estado hídrico do solo.",
    )


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

        # Live probe snapshot — independent of recommendation age
        probe_snapshot = await interpret_probes(eng_ctx, db)
        rz = probe_snapshot.rootzone
        probe_live: dict | None = None
        # Populated below; used by _source_confidence_and_explanation afterwards
        if rz.has_data:
            depths_info = [
                {
                    "depth_cm": d.depth_cm,
                    "vwc": round(d.latest_vwc, 3) if d.latest_vwc is not None else None,
                    "hours_since_reading": round(d.hours_since_last, 1) if d.hours_since_last is not None else None,
                    "quality": d.quality,
                }
                for d in rz.depth_statuses
                if d.latest_vwc is not None
            ]
            probe_live = {
                "swc_weighted_avg": round(rz.swc_current, 3) if rz.swc_current is not None else None,
                "swc_source": rz.swc_source,
                "hours_since_any_reading": round(rz.hours_since_any_reading, 1) if rz.hours_since_any_reading is not None else None,
                "all_depths_ok": rz.all_depths_ok,
                "depths": depths_info,
                "anomalies": probe_snapshot.anomalies_detected,
            }

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
            recommendation_action=rec.action if rec else None,
            # Only expose depth/runtime when action is actually "irrigate" —
            # a non-zero depth on a "no_irrigation" decision confuses the LLM.
            irrigation_depth_mm=(
                rec.irrigation_depth_mm
                if rec and rec.action == "irrigate"
                else None
            ),
            runtime_minutes=(
                rec.irrigation_runtime_min
                if rec and rec.action == "irrigate"
                else None
            ),
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
            probe_live=probe_live,
            source_confidence=src_conf,
            data_quality_explanation=dqe,
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


# ---------------------------------------------------------------------------
# Structured agronomic context for LLM grounding
# ---------------------------------------------------------------------------

async def get_probe_diagnostics(probe_id: str, db: AsyncSession) -> dict:
    """Per-probe diagnostics: depth freshness, latest readings, ingestion telemetry."""
    probe = await db.get(Probe, probe_id)
    if probe is None:
        return {"error": "probe_not_found"}

    depths = (
        await db.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe_id))
    ).scalars().all()
    depth_info: list[dict] = []
    for d in sorted(depths, key=lambda x: x.depth_cm):
        depth_info.append({
            "depth_cm": d.depth_cm,
            "sensor_type": d.sensor_type,
            "last_reading_at": d.last_reading_at.isoformat() if d.last_reading_at else None,
            "last_quality_flag": d.last_quality_flag,
            "last_unit": d.last_unit,
            "readings_count_total": d.readings_count_total,
            "data_status": d.data_status,
        })

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


async def get_sector_water_events(
    sector_id: str, db: AsyncSession, days: int = 14
) -> list[dict]:
    """Return persisted water events for a sector over the last N days."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            select(DetectedWaterEvent)
            .where(
                DetectedWaterEvent.sector_id == sector_id,
                DetectedWaterEvent.timestamp >= since,
            )
            .order_by(DetectedWaterEvent.timestamp.desc())
            .limit(50)
        )
    ).scalars().all()
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
    }


async def get_weather_summary(
    farm_id: str, db: AsyncSession, obs_days: int = 7, fc_days: int = 3
) -> dict:
    """Recent observations + short-term forecast for a farm."""
    now = datetime.now(UTC)
    obs_since = now - timedelta(days=obs_days)
    obs = (
        await db.execute(
            select(WeatherObservation)
            .where(
                WeatherObservation.farm_id == farm_id,
                WeatherObservation.timestamp >= obs_since,
            )
            .order_by(WeatherObservation.timestamp.desc())
            .limit(obs_days * 4)
        )
    ).scalars().all()
    fc = (
        await db.execute(
            select(WeatherForecast)
            .where(WeatherForecast.farm_id == farm_id)
            .order_by(WeatherForecast.forecast_date)
            .limit(fc_days)
        )
    ).scalars().all()
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
        await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector_id)
            .order_by(Recommendation.generated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
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


async def build_structured_agronomic_context(
    sector_id: str, db: AsyncSession
) -> dict:
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

    crop_profile = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
        )
    ).scalar_one_or_none()
    irrigation_system = (
        await db.execute(
            select(IrrigationSystem).where(IrrigationSystem.sector_id == sector_id)
        )
    ).scalar_one_or_none()

    # Probes + per-depth diagnostics
    probes = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalars().all()
    probe_diagnostics: list[dict] = []
    latest_readings: list[dict] = []
    for probe in probes:
        diag = await get_probe_diagnostics(probe.id, db)
        probe_diagnostics.append(diag)
        # Pull the latest VWC reading per depth for the last 48h
        for d in diag.get("depths", []):
            if d.get("last_reading_at") is None:
                continue
            latest_readings.append({
                "probe_id": probe.id,
                "probe_external_id": probe.external_id,
                "depth_cm": d["depth_cm"],
                "last_reading_at": d["last_reading_at"],
                "quality_flag": d["last_quality_flag"],
                "data_status": d["data_status"],
            })

    water_events = await get_sector_water_events(sector_id, db, days=14)
    weather = await get_weather_summary(farm.id if farm else "", db) if farm else {
        "recent_observations": [], "forecast": []
    }
    water_balance = await get_sector_water_balance(sector_id, db)
    recs = await get_recommendation_history(sector_id, db)

    # Data quality scoring across all probes
    fresh_depths = sum(
        1 for d in probe_diagnostics for x in d.get("depths", [])
        if x.get("data_status") == "ok"
    )
    total_depths = sum(len(d.get("depths", [])) for d in probe_diagnostics)
    stale_depths = sum(
        1 for d in probe_diagnostics for x in d.get("depths", [])
        if x.get("data_status") in ("stale", "no_data")
    )

    known_limitations: list[str] = []
    if not probes:
        known_limitations.append("Sector has no probes — no direct soil moisture signal.")
    if total_depths and stale_depths == total_depths:
        known_limitations.append("All probe depths are stale; reasoning relies on water balance only.")
    if irrigation_system is None:
        known_limitations.append("Irrigation system is not configured — applied-mm conversions use defaults.")
    if crop_profile is None:
        known_limitations.append("No sector crop profile attached — Kc and root depth fall back to defaults.")
    if not weather.get("recent_observations"):
        known_limitations.append("No recent weather observations available for this farm.")
    if not water_balance.get("available"):
        known_limitations.append("No water-balance snapshot has been generated yet for this sector.")

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
            if farm else None
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
            if crop_profile else None
        ),
        "soil": (
            {
                "field_capacity": plot.field_capacity,
                "wilting_point": plot.wilting_point,
                "soil_texture": plot.soil_texture,
                "stone_content_pct": plot.stone_content_pct,
            }
            if plot else None
        ),
        "irrigation_system": (
            {
                "system_type": irrigation_system.system_type,
                "application_rate_mm_h": irrigation_system.application_rate_mm_h,
                "efficiency": irrigation_system.efficiency,
                "distribution_uniformity": irrigation_system.distribution_uniformity,
                "max_runtime_hours": irrigation_system.max_runtime_hours,
            }
            if irrigation_system else None
        ),
        "probe_summary": {
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

    current = await build_structured_agronomic_context(sector_id, db)
    if current.get("error"):
        return current

    probes = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalars().all()

    probe_changes: list[dict] = []
    for probe in probes:
        depths = (
            await db.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe.id))
        ).scalars().all()
        for depth in sorted(depths, key=lambda d: d.depth_cm):
            rows = (
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
            ).scalars().all()
            if not rows:
                probe_changes.append({
                    "probe_id": probe.id,
                    "probe_external_id": probe.external_id,
                    "depth_cm": depth.depth_cm,
                    "status": "no_readings_in_window",
                    "data_status": depth.data_status,
                })
                continue

            previous_values = [_reading_value(r) for r in rows if _ensure_utc(r.timestamp) < split]
            recent_values = [_reading_value(r) for r in rows if _ensure_utc(r.timestamp) >= split]
            previous_values = [v for v in previous_values if v is not None]
            recent_values = [v for v in recent_values if v is not None]
            first_value = _reading_value(rows[0])
            last_value = _reading_value(rows[-1])

            probe_changes.append({
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
                if previous_values else None,
                "recent_half_avg_vwc": round(sum(recent_values) / len(recent_values), 4)
                if recent_values else None,
                "quality_counts": _quality_counts(rows),
                "data_status": depth.data_status,
            })

    water_events = (
        await db.execute(
            select(DetectedWaterEvent)
            .where(
                DetectedWaterEvent.sector_id == sector_id,
                DetectedWaterEvent.timestamp >= since,
            )
            .order_by(DetectedWaterEvent.timestamp.desc())
            .limit(50)
        )
    ).scalars().all()

    recs = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector_id)
            .order_by(Recommendation.generated_at.desc())
            .limit(2)
        )
    ).scalars().all()
    latest_rec = recs[0] if recs else None
    previous_rec = recs[1] if len(recs) > 1 else None

    farm_id = current.get("farm", {}).get("id") if current.get("farm") else None
    weather_observations: list[dict] = []
    if farm_id:
        obs = (
            await db.execute(
                select(WeatherObservation)
                .where(
                    WeatherObservation.farm_id == farm_id,
                    WeatherObservation.timestamp >= since,
                )
                .order_by(WeatherObservation.timestamp.desc())
                .limit(20)
            )
        ).scalars().all()
        weather_observations = [
            {
                "timestamp": o.timestamp.isoformat(),
                "rainfall_mm": o.rainfall_mm,
                "et0_mm": o.et0_mm,
                "temperature_max_c": o.temperature_max_c,
            }
            for o in obs
        ]

    return {
        "analysis_type": "sector_change_analysis",
        "window_hours": window_hours,
        "generated_at": now.isoformat(),
        "sector": current.get("sector"),
        "current_context_summary": {
            "probe_data_quality": current.get("probe_summary", {}).get("data_quality"),
            "water_balance": current.get("water_balance"),
            "known_limitations": current.get("known_limitations", []),
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
            "forecast": current.get("weather", {}).get("forecast", []),
        },
        "known_limitations": current.get("known_limitations", []),
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
