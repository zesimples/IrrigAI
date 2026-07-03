"""Recommendation pipeline orchestration.

Loads user-configured context from DB, runs all engine components, and assembles
a full EngineRecommendation. Every parameter is sourced from the user's DB records
(SectorCropProfile, Plot, IrrigationSystem, etc.) — never from hardcoded constants.
"""

import logging
import re
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import (
    confidence,
    crop_demand,
    dosage,
    et0,
    forecast_impact,
    probe_interpreter,
    trigger,
    water_balance,
)
from app.engine.auto_calibration import CALIB_MAX_AGE_DAYS, is_calibration_stale
from app.engine.rainfall_effectiveness import compute_effective_rainfall
from app.engine.soil_bounds import resolve_soil_bounds
from app.engine.stress_projection import StressProjector
from app.engine.types import (
    ConfidenceResult,
    DailyWeather,
    EngineRecommendation,
    ProbeSnapshot,
    ReasonEntry,
    RecentIrrigationContext,
    SectorContext,
    WeatherContext,
)
from app.models import (
    Farm,
    IrrigationEvent,
    IrrigationSystem,
    Plot,
    Sector,
    SectorCropProfile,
    WeatherObservation,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context builder — reads from user-configured DB records
# ---------------------------------------------------------------------------

# Fallback values (used when user hasn't configured something)
_FALLBACK_FC = 0.28
_FALLBACK_PWP = 0.14
_FALLBACK_MAD = 0.60
_FALLBACK_ROOT_DEPTH = 0.60
_FALLBACK_EFFICIENCY = 0.90


async def resolve_sector_soil_bounds(sector_id: str, db: AsyncSession, plot=None):
    """Resolve a sector's FC/refill bounds: calibration > SCP > plot > default.

    Single source of truth shared by the recommendation engine
    (`build_sector_context`) and the probe-readings chart (`api/v1/probes`), so the
    chart's CC/PMP reference lines can never diverge from the FC the engine actually
    uses. Returns a ResolvedSoilBounds (fc, pwp, source, calibration).
    """
    from app.models.probe_calibration import ProbeCalibration

    if plot is None:
        sector = await db.get(Sector, sector_id)
        plot = await db.get(Plot, sector.plot_id) if sector else None

    scp = (await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )).scalar_one_or_none()
    calib = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalar_one_or_none()

    calib_stale = is_calibration_stale(calib.computed_at) if calib is not None else False
    calib_meta = (
        {
            "observed_fc": calib.observed_fc,
            "observed_refill": calib.observed_refill,
            "method": calib.method,
            "num_cycles": calib.num_cycles,
            "consistency": calib.consistency,
            "window_days": calib.window_days,
            "computed_at": calib.computed_at.isoformat() if calib.computed_at else None,
            "max_age_days": CALIB_MAX_AGE_DAYS,
            "stale": calib_stale,
            "used": not calib_stale,
        }
        if calib is not None else None
    )
    return resolve_soil_bounds(
        scp_fc=scp.field_capacity if scp else None,
        scp_pwp=scp.wilting_point if scp else None,
        scp_customized=bool(scp.is_customized) if scp else False,
        calib_fc=calib.observed_fc if calib else None,
        calib_refill=calib.observed_refill if calib else None,
        calib_meta=calib_meta,
        calib_stale=calib_stale,
        plot_fc=plot.field_capacity if plot and plot.field_capacity is not None else None,
        plot_pwp=plot.wilting_point if plot and plot.wilting_point is not None else None,
    )


async def build_sector_context(sector_id: str, db: AsyncSession) -> SectorContext:
    """Load all engine inputs for a sector from user-configured DB records.

    Tracks defaults_used (agronomic fallbacks) and missing_config (not yet set up).
    """
    defaults_used: list[str] = []
    missing_config: list[str] = []

    # --- Sector ---
    sector = await db.get(Sector, sector_id)
    if sector is None:
        raise ValueError(f"Sector {sector_id} not found")

    # --- Plot + soil ---
    plot = await db.get(Plot, sector.plot_id)
    soil_texture = plot.soil_texture if plot else None

    # Soil reference points. Precedence: probe-calibrated envelope > SCP > plot/preset
    # > clay-loam default. Resolved by the shared resolve_sector_soil_bounds helper so
    # the chart's CC/PMP can never diverge from the FC the engine uses.
    bounds = await resolve_sector_soil_bounds(sector_id, db, plot=plot)
    fc = bounds.fc
    pwp = bounds.pwp
    field_capacity_source = bounds.source
    fc_calibration = bounds.calibration
    if bounds.source == "default":
        defaults_used.append("soil FC/PWP (not configured, using clay-loam defaults)")
    elif bounds.source == "probe_calibrated":
        method = (bounds.calibration or {}).get("method", "?")
        defaults_used.append(
            f"FC/refill calibrated from probe envelope ({method}, FC={fc:.2f})"
        )

    # --- SectorCropProfile ---
    scp_result = await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )
    scp: SectorCropProfile | None = scp_result.scalar_one_or_none()

    if scp is None:
        # This shouldn't happen — SCP is created on sector creation
        # Fall back to hard defaults and note it
        kc = 0.80
        kc_source = "default (no crop profile — check sector setup)"
        mad = _FALLBACK_MAD
        root_depth_m = _FALLBACK_ROOT_DEPTH
        rdi_eligible = False
        rdi_factor = None
        defaults_used.append("Kc/MAD/root_depth (no crop profile found)")
        missing_config.append("crop profile not created")
    else:
        # Kc from profile stages, keyed by current stage
        kc, kc_source = crop_demand.get_kc_from_profile(
            scp.stages or [],
            sector.current_phenological_stage,
        )
        if sector.current_phenological_stage is None:
            defaults_used.append(f"Kc={kc:.2f} ({kc_source})")

        mad = scp.mad
        maturity_age = scp.maturity_age_years

        # Root depth — use young if tree is immature
        tree_age = (
            datetime.now(UTC).year - sector.planting_year
            if sector.planting_year is not None
            else None
        )
        if tree_age is not None and maturity_age is not None and tree_age < 4:
            root_depth_m = scp.root_depth_young_m
            defaults_used.append(f"root_depth={root_depth_m}m (young tree, age {tree_age}yr)")
        else:
            root_depth_m = scp.root_depth_mature_m

        # RDI eligibility + stage-specific root depth
        rdi_eligible = False
        rdi_factor = None
        if sector.current_phenological_stage:
            stage_dict = next(
                (s for s in (scp.stages or []) if s.get("key") == sector.current_phenological_stage),
                None,
            )
            if stage_dict:
                rdi_eligible = stage_dict.get("rdi_eligible", False)
                rdi_factor = stage_dict.get("rdi_factor")
                # Override root depth with stage-specific value if present
                stage_root = stage_dict.get("root_depth_m")
                if stage_root is not None:
                    root_depth_m = float(stage_root)
                    defaults_used = [d for d in defaults_used if "root_depth" not in d]

    # --- IrrigationSystem ---
    irrig_result = await db.execute(
        select(IrrigationSystem).where(IrrigationSystem.sector_id == sector_id)
    )
    irrig: IrrigationSystem | None = irrig_result.scalar_one_or_none()

    if irrig is None:
        missing_config.append("irrigation system not configured")
        irrig_system_type = None
        app_rate = None
        efficiency = _FALLBACK_EFFICIENCY
        distribution_uniformity = 0.90
        emitter_flow = None
        emitter_spacing = None
        row_spacing = None
        max_runtime = None
        min_irrig = None
        max_irrig = None
    else:
        irrig_system_type = irrig.system_type
        app_rate = irrig.application_rate_mm_h
        efficiency = irrig.efficiency or _FALLBACK_EFFICIENCY
        distribution_uniformity = getattr(irrig, "distribution_uniformity", None) or 0.90
        emitter_flow = irrig.emitter_flow_lph
        emitter_spacing = irrig.emitter_spacing_m
        row_spacing = sector.row_spacing_m
        max_runtime = irrig.max_runtime_hours
        min_irrig = irrig.min_irrigation_mm
        max_irrig = irrig.max_irrigation_mm

    tree_age_years = (
        datetime.now(UTC).year - sector.planting_year
        if sector.planting_year is not None else None
    )

    return SectorContext(
        sector_id=sector_id,
        sector_name=sector.name,
        crop_type=sector.crop_type,
        phenological_stage=sector.current_phenological_stage,
        planting_year=sector.planting_year,
        tree_age_years=tree_age_years,
        soil_texture=soil_texture,
        field_capacity=fc,
        wilting_point=pwp,
        kc=kc,
        kc_source=kc_source,
        mad=mad,
        root_depth_m=root_depth_m,
        rdi_eligible=rdi_eligible,
        rdi_factor=rdi_factor,
        irrigation_system_type=irrig_system_type,
        application_rate_mm_h=app_rate,
        irrigation_efficiency=efficiency,
        distribution_uniformity=distribution_uniformity,
        emitter_flow_lph=emitter_flow,
        emitter_spacing_m=emitter_spacing,
        row_spacing_m=row_spacing,
        max_runtime_hours=max_runtime,
        min_irrigation_mm=min_irrig,
        max_irrigation_mm=max_irrig,
        irrigation_strategy=sector.irrigation_strategy,
        deficit_factor=sector.deficit_factor,
        area_ha=sector.area_ha,
        rainfall_effectiveness=sector.rainfall_effectiveness,
        defaults_used=defaults_used,
        missing_config=missing_config,
        field_capacity_source=field_capacity_source,
        fc_calibration=fc_calibration,
    )


# ---------------------------------------------------------------------------
# Weather context builder
# ---------------------------------------------------------------------------

async def build_weather_context(
    farm_id: str,
    db: AsyncSession,
    plot_id: str | None = None,
) -> WeatherContext:
    """Load recent weather observations and forecast from DB.

    When *plot_id* is given, prefers rows scoped to that plot
    (``WeatherObservation.plot_id == plot_id``).  If both the observation and
    forecast queries return nothing for the plot, falls back to the farm-level
    rows (``plot_id IS NULL``).  When *plot_id* is ``None``, queries farm-level
    rows directly — identical to the previous behaviour.
    """
    from app.models import WeatherForecast

    now = datetime.now(UTC)

    farm = await db.get(Farm, farm_id)
    lat = farm.location_lat if farm else None
    lon = farm.location_lon if farm else None
    elevation_m = (farm.elevation_m or 0.0) if farm else 0.0

    # Build the plot predicate: exact-match when plot_id given, IS NULL otherwise.
    if plot_id:
        obs_pred = WeatherObservation.plot_id == plot_id
        fct_pred = WeatherForecast.plot_id == plot_id
    else:
        obs_pred = WeatherObservation.plot_id.is_(None)
        fct_pred = WeatherForecast.plot_id.is_(None)

    # --- Latest observation ---
    obs_result = await db.execute(
        select(WeatherObservation)
        .where(WeatherObservation.farm_id == farm_id, obs_pred)
        .order_by(WeatherObservation.timestamp.desc())
        .limit(1)
    )
    latest_obs = obs_result.scalar_one_or_none()

    # --- Forecast ---
    forecast_result = await db.execute(
        select(WeatherForecast)
        .where(WeatherForecast.farm_id == farm_id, fct_pred)
        .order_by(WeatherForecast.forecast_date)
        .limit(7)
    )
    forecasts = forecast_result.scalars().all()

    # Fallback to farm-level when plot-scoped queries returned nothing.
    if plot_id and latest_obs is None and not forecasts:
        farm_obs_pred = WeatherObservation.plot_id.is_(None)
        farm_fct_pred = WeatherForecast.plot_id.is_(None)

        obs_result = await db.execute(
            select(WeatherObservation)
            .where(WeatherObservation.farm_id == farm_id, farm_obs_pred)
            .order_by(WeatherObservation.timestamp.desc())
            .limit(1)
        )
        latest_obs = obs_result.scalar_one_or_none()

        forecast_result = await db.execute(
            select(WeatherForecast)
            .where(WeatherForecast.farm_id == farm_id, farm_fct_pred)
            .order_by(WeatherForecast.forecast_date)
            .limit(7)
        )
        forecasts = forecast_result.scalars().all()

    # Build typed weather objects from query results.
    hours_since_obs = None
    today_weather = DailyWeather(date=now.date())

    if latest_obs:
        obs_ts = latest_obs.timestamp
        if obs_ts.tzinfo is None:
            obs_ts = obs_ts.replace(tzinfo=UTC)
        hours_since_obs = (now - obs_ts).total_seconds() / 3600
        today_weather = DailyWeather(
            date=obs_ts.date(),
            t_max=latest_obs.temperature_max_c,
            t_min=latest_obs.temperature_min_c,
            t_mean=latest_obs.temperature_mean_c,
            humidity_pct=latest_obs.humidity_pct,
            wind_ms=latest_obs.wind_speed_ms,
            solar_mjm2=latest_obs.solar_radiation_mjm2,
            rainfall_mm=latest_obs.rainfall_mm or 0.0,
            et0_mm=latest_obs.et0_mm,
        )

    forecast_days = [
        DailyWeather(
            date=f.forecast_date,
            t_max=f.temperature_max_c,
            t_min=f.temperature_min_c,
            rainfall_mm=f.rainfall_mm or 0.0,
            humidity_pct=f.humidity_pct,
            wind_ms=f.wind_speed_ms,
            et0_mm=f.et0_mm,
            rainfall_probability_pct=f.rainfall_probability_pct,
        )
        for f in forecasts
    ]

    return WeatherContext(
        farm_id=farm_id,
        lat=lat,
        lon=lon,
        elevation_m=elevation_m,
        today=today_weather,
        forecast=forecast_days,
        hours_since_observation=hours_since_obs,
        has_forecast=bool(forecast_days),
    )


# ---------------------------------------------------------------------------
# Irrigation history context
# ---------------------------------------------------------------------------

async def build_irrigation_context(sector_id: str, db: AsyncSession) -> RecentIrrigationContext:
    from datetime import timedelta

    from app.engine.types import IrrigationEventSummary

    since = datetime.now(UTC) - timedelta(days=7)
    result = await db.execute(
        select(IrrigationEvent)
        .where(
            IrrigationEvent.sector_id == sector_id,
            IrrigationEvent.start_time >= since,
        )
        .order_by(IrrigationEvent.start_time.desc())
    )
    events = result.scalars().all()

    summaries = [
        IrrigationEventSummary(
            event_id=e.id,
            start_time=e.start_time,
            applied_mm=e.applied_mm or 0.0,
        )
        for e in events
    ]

    total_7d = sum(s.applied_mm for s in summaries)
    last_at = events[0].start_time if events else None

    return RecentIrrigationContext(
        sector_id=sector_id,
        events_7d=summaries,
        last_irrigation_at=last_at,
        total_applied_7d_mm=total_7d,
        has_log=bool(events),
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

_stress_projector = StressProjector()


class RecommendationPipeline:
    """Runs the full agronomic recommendation for one sector."""

    async def run(
        self,
        sector_id: str,
        target_date: date,
        db: AsyncSession,
        farm_id: str | None = None,
    ) -> EngineRecommendation:
        log: list[str] = []
        now = datetime.now(UTC)

        # Step 0: Check for active sector-level override
        from app.models.sector_override import SectorOverride
        override_result = await db.execute(
            select(SectorOverride).where(
                SectorOverride.sector_id == sector_id,
                SectorOverride.is_active.is_(True),
            ).limit(1)
        )
        active_override = override_result.scalar_one_or_none()

        # Step 1: Load context from user-configured DB records
        ctx = await build_sector_context(sector_id, db)
        log.append(f"Sector: {ctx.sector_name} [{ctx.crop_type}], stage={ctx.phenological_stage or 'NOT SET'}")
        log.append(f"Kc={ctx.kc:.2f} ({ctx.kc_source}), MAD={ctx.mad}, root_depth={ctx.root_depth_m}m")
        if ctx.defaults_used:
            log.append(f"Defaults applied: {'; '.join(ctx.defaults_used)}")
        if ctx.missing_config:
            log.append(f"Missing config: {'; '.join(ctx.missing_config)}")

        # Step 2: Resolve farm_id (needed for weather) and sector plot_id.
        # Always load the sector so we can pass its plot_id to build_weather_context.
        sector = await db.get(Sector, sector_id)
        if farm_id is None:
            plot = await db.get(Plot, sector.plot_id) if sector else None
            farm_id = plot.farm_id if plot else None

        # Step 2.5: GDD-based Kc fallback (when phenological stage is not set)
        if ctx.phenological_stage is None and farm_id:
            try:
                from app.engine.gdd_tracker import GDDTracker
                gdd_status = await GDDTracker().compute_accumulated_gdd(sector_id, db)
                if gdd_status and gdd_status.suggested_stage and gdd_status.suggested_kc is not None:
                    # Use GDD-estimated stage as Kc source (avoids -0.10 "stage not set" penalty,
                    # gets -0.05 via defaults_used instead)
                    ctx.kc = gdd_status.suggested_kc
                    ctx.phenological_stage = gdd_status.suggested_stage
                    ctx.kc_source = (
                        f"GDD-estimated stage ({gdd_status.suggested_stage}, "
                        f"{gdd_status.accumulated_gdd:.0f} GDD)"
                    )
                    ctx.defaults_used.append(ctx.kc_source)
                    log.append(f"GDD fallback: stage={gdd_status.suggested_stage} Kc={ctx.kc:.2f}")
            except Exception as exc:
                logger.debug("GDD fallback skipped for sector %s: %s", sector_id, exc)

        # Step 3: Load weather (prefer plot-scoped rows, fall back to farm-level)
        weather: WeatherContext | None = None
        if farm_id:
            sector_plot_id = sector.plot_id if sector else None
            weather = await build_weather_context(farm_id, db, plot_id=sector_plot_id)
            log.append(f"Weather: ET0={weather.today.et0_mm}, forecast days={len(weather.forecast)}")
        else:
            weather = WeatherContext(
                farm_id="",
                lat=None,
                lon=None,
                elevation_m=0.0,
                today=DailyWeather(date=target_date),
                forecast=[],
                hours_since_observation=None,
                has_forecast=False,
            )

        # Step 4: ET0
        et0_val, et0_method = et0.compute_et0(weather.today, weather.lat or 38.57, weather.elevation_m)
        log.append(f"ET0={et0_val} mm/day ({et0_method})")

        # Step 5: ETc = ET0 × Kc
        etc_val = crop_demand.compute_etc(et0_val, ctx.kc) if et0_val is not None else None
        log.append(f"ETc={etc_val} mm/day (Kc={ctx.kc:.2f})")

        # Step 6: Probe interpretation → rootzone SWC
        probes: ProbeSnapshot = await probe_interpreter.interpret_probes(ctx, db)
        log.append(
            f"Probe: SWC={probes.rootzone.swc_current}, "
            f"source={probes.rootzone.swc_source}, "
            f"anomalies={len(probes.anomalies_detected)}"
        )

        # Step 7: Water balance
        swc_source = probes.rootzone.swc_source
        swc_model_result = None
        swc_for_wb = probes.rootzone.swc_current
        if swc_for_wb is None and farm_id:
            from app.engine.soil_water_data import load_daily_inputs
            from app.engine.soil_water_model import model_soil_water
            from app.models import Flowmeter

            flowmeter = (await db.execute(
                select(Flowmeter).where(
                    Flowmeter.sector_id == sector_id,
                    Flowmeter.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if flowmeter is not None:
                # Optional, best-effort: a bad sector config (e.g. root_depth_m<=0) or a
                # transient DB error must not crash the whole recommendation run — fall
                # back to the default-SWC path, mirroring the GDD fallback above.
                try:
                    daily = await load_daily_inputs(
                        sector_id=sector_id,
                        farm_id=farm_id,
                        flowmeter_id=flowmeter.id,
                        today=target_date,
                        db=db,
                    )
                    swc_model_result = model_soil_water(
                        fc=ctx.field_capacity,
                        pwp=ctx.wilting_point,
                        root_depth_m=ctx.root_depth_m,
                        kc=ctx.kc,
                        rainfall_effectiveness=ctx.rainfall_effectiveness,
                        application_efficiency=ctx.irrigation_efficiency,
                        daily=daily,
                        today=target_date,
                    )
                    swc_for_wb = swc_model_result.swc_current
                    swc_source = "water_balance_model"
                    log.append(
                        f"SoilWaterModel: SWC={swc_for_wb}, source={swc_model_result.seed_kind}, "
                        f"days_since_anchor={swc_model_result.days_since_anchor}, "
                        f"conf={swc_model_result.confidence_factor}"
                    )
                except Exception:
                    logger.warning(
                        "SoilWaterModel skipped for sector %s (falling back to default SWC)",
                        sector_id, exc_info=True,
                    )
                    swc_model_result = None

        # Fell through to build_water_balance's static seed (no probe, no usable model).
        if swc_for_wb is None:
            swc_source = "default_estimate"

        # A probe-authoritative SWC combined with calibrated soil bounds is the case
        # that fixes the "always 100%" pinning — surface it as its own source label.
        if swc_source == "probe_weighted" and ctx.field_capacity_source == "probe_calibrated":
            swc_source = "probe_calibrated"

        wb = water_balance.build_water_balance(ctx, swc_for_wb)
        rain_effective, rain_eff_note = compute_effective_rainfall(
            rainfall_mm=weather.today.rainfall_mm or 0.0,
            soil_texture=ctx.soil_texture,
            user_correction=ctx.rainfall_effectiveness,
        )
        log.append(rain_eff_note)
        log.append(
            f"WB: SWC={wb.swc_current}, Dr={wb.depletion_mm}mm, "
            f"TAW={wb.taw_mm}mm, RAW={wb.raw_mm}mm"
        )

        # Step 8: Forecast impact
        fc_impact = forecast_impact.compute_forecast_impact(weather)
        log.append(f"Forecast: rain_48h={fc_impact['rain_next_48h_mm']}mm, rain_skip={fc_impact['rain_skip_recommended']}")

        # Step 9: Trigger
        do_irrigate, trigger_reason = trigger.should_irrigate(
            wb, ctx, fc_impact["rain_next_48h_mm"]
        )
        log.append(f"Trigger: {'IRRIGATE' if do_irrigate else 'SKIP'} — {trigger_reason}")

        # Step 10: Dosage (if irrigating)
        dose: dosage.DosageResult | None = None
        if do_irrigate:
            dose = dosage.compute_dosage(wb, ctx)
            log.append(
                f"Dosage: net={dose.irrigation_net_mm}mm, gross={dose.irrigation_gross_mm}mm, "
                f"runtime={dose.runtime_min}min"
            )

        # Step 11: Confidence
        conf: ConfidenceResult = confidence.score(
            ctx, probes, weather, probes.anomalies_detected,
            swc_model_confidence=(swc_model_result.confidence_factor if swc_model_result else None),
        )
        log.append(f"Confidence: {conf.score:.2f} ({conf.level})")

        # Step 11.5: 48-72h stress projection
        stress_proj_dict: dict | None = None
        try:
            stress = _stress_projector.project(
                current_depletion_mm=wb.depletion_mm,
                taw_mm=wb.taw_mm,
                mad=ctx.mad,
                forecast_et0=[w.et0_mm for w in weather.forecast[:3]],
                kc=ctx.kc,
                forecast_rain=[
                    (w.rainfall_mm or 0.0, w.rainfall_probability_pct or 0.0)
                    for w in weather.forecast[:3]
                ],
                rainfall_effectiveness=ctx.rainfall_effectiveness,
                sector_id=sector_id,
                today=target_date,
            )
            stress_proj_dict = {
                "current_depletion_pct": stress.current_depletion_pct,
                "hours_to_stress": stress.hours_to_stress,
                "stress_date": stress.stress_date.isoformat() if stress.stress_date else None,
                "urgency": stress.urgency,
                "message_pt": stress.message_pt,
                "message_en": stress.message_en,
                "projections": [
                    {
                        "date": p.date.isoformat(),
                        "projected_etc_mm": p.projected_etc_mm,
                        "projected_rain_mm": p.projected_rain_mm,
                        "projected_depletion_mm": p.projected_depletion_mm,
                        "projected_depletion_pct": p.projected_depletion_pct,
                        "stress_triggered": p.stress_triggered,
                    }
                    for p in stress.projections
                ],
            }
            log.append(f"Stress projection: urgency={stress.urgency}, hours_to_stress={stress.hours_to_stress}")
        except Exception as exc:
            logger.debug("Stress projection failed for sector %s: %s", sector_id, exc)

        # Step 12: Build reasons list
        reasons = _build_reasons(ctx, wb, et0_val, etc_val, trigger_reason, fc_impact, conf, dose)

        # Step 13: Assemble recommendation
        action = "irrigate" if do_irrigate else "skip"
        if fc_impact["rain_skip_recommended"] and not do_irrigate:
            action = "defer"

        eng_rec = EngineRecommendation(
            sector_id=sector_id,
            target_date=target_date,
            generated_at=now,
            action=action,
            irrigation_depth_mm=dose.irrigation_gross_mm if dose else None,
            irrigation_runtime_min=dose.runtime_min if dose else None,
            suggested_start_time="06:00" if do_irrigate else None,
            confidence=conf,
            reasons=reasons,
            et0_mm=et0_val,
            etc_mm=etc_val,
            kc=ctx.kc,
            swc_current=wb.swc_current,
            swc_source=swc_source,
            swc_model=(
                {
                    "seed_kind": swc_model_result.seed_kind,
                    "last_anchor_date": (
                        swc_model_result.last_anchor_date.isoformat()
                        if swc_model_result.last_anchor_date else None
                    ),
                    "days_since_anchor": swc_model_result.days_since_anchor,
                    "n_gap_days": swc_model_result.n_gap_days,
                    "confidence_factor": swc_model_result.confidence_factor,
                }
                if swc_model_result is not None else None
            ),
            fc_calibration=ctx.fc_calibration,
            depletion_mm=wb.depletion_mm,
            raw_mm=wb.raw_mm,
            taw_mm=wb.taw_mm,
            rain_effective_mm=rain_effective,
            forecast_rain_next_48h=fc_impact["rain_next_48h_mm"],
            defaults_used=ctx.defaults_used,
            missing_config=ctx.missing_config,
            stress_projection=stress_proj_dict,
            computation_log={
                "log": log,
                "kc_source": ctx.kc_source,
                "et0_method": et0_method,
                "trigger_reason": trigger_reason,
                "forecast_impact": fc_impact,
                "confidence_penalties": conf.penalties,
            },
        )

        # Apply active sector override (engine output still logged, values replaced)
        if active_override:
            log.append(f"OVERRIDE ACTIVE: type={active_override.override_type}, value={active_override.value}")
            if active_override.override_type == "skip":
                eng_rec.action = "skip"
                eng_rec.irrigation_depth_mm = None
                eng_rec.irrigation_runtime_min = None
            elif active_override.override_type == "force_irrigate":
                eng_rec.action = "irrigate"
            elif active_override.override_type == "fixed_depth" and active_override.value is not None:
                eng_rec.action = "irrigate"
                eng_rec.irrigation_depth_mm = active_override.value
            eng_rec.defaults_used = eng_rec.defaults_used + [
                f"sector override: {active_override.override_type} (reason: {active_override.reason[:60]})"
            ]

        return eng_rec

    async def run_all_sectors(
        self,
        farm_id: str,
        target_date: date,
        db: AsyncSession,
    ) -> list[EngineRecommendation]:
        """Run pipeline for all sectors of a farm. Continues past individual failures."""
        from app.models import Farm, Plot

        farm = await db.get(Farm, farm_id)
        if farm is None:
            return []

        plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
        plots = plots_result.scalars().all()

        results: list[EngineRecommendation] = []
        for plot in plots:
            sectors_result = await db.execute(
                select(Sector).where(Sector.plot_id == plot.id)
            )
            sectors = sectors_result.scalars().all()
            for sector in sectors:
                try:
                    async with db.begin_nested():
                        rec = await self.run(sector.id, target_date, db, farm_id=farm_id)
                    results.append(rec)
                except Exception as exc:
                    logger.exception("Engine failed for sector %s: %s", sector.id, exc)

        return results


def _build_reasons(
    ctx: SectorContext,
    wb: water_balance.WaterBalanceResult,
    et0_val: float | None,
    etc_val: float | None,
    trigger_reason: str,
    fc_impact: dict,
    conf: ConfidenceResult,
    dose: dosage.DosageResult | None,
) -> list[ReasonEntry]:
    reasons: list[ReasonEntry] = []
    i = 0

    def next_order() -> int:
        nonlocal i
        i += 1
        return i

    depletion_pct = round(wb.depletion_mm / wb.taw_mm * 100) if wb.taw_mm > 0 else 0
    remaining_pct = 100 - depletion_pct
    reasons.append(ReasonEntry(
        order=next_order(),
        category="water_balance",
        message_pt=f"O solo tem {remaining_pct}% da água disponível — faltam {wb.depletion_mm:.1f} mm para reabastecer (capacidade total {wb.taw_mm:.0f} mm)",
        message_en=f"Soil has {remaining_pct}% of available water — {wb.depletion_mm:.1f} mm deficit to refill (total capacity {wb.taw_mm:.0f} mm)",
        data_key="depletion_mm",
        data_value=str(wb.depletion_mm),
    ))

    if et0_val is not None:
        reasons.append(ReasonEntry(
            order=next_order(),
            category="evapotranspiration",
            message_pt=f"A cultura está a consumir cerca de {etc_val:.1f} mm de água por dia (condições atmosféricas hoje: {et0_val:.1f} mm)",
            message_en=f"Crop is using about {etc_val:.1f} mm of water per day (atmospheric demand today: {et0_val:.1f} mm)",
            data_key="etc_mm",
            data_value=str(etc_val),
        ))

    if fc_impact["rain_next_48h_mm"] > 0:
        reasons.append(ReasonEntry(
            order=next_order(),
            category="forecast",
            message_pt=f"Previsão de {fc_impact['rain_next_48h_mm']:.0f} mm de chuva nas próximas 48 horas",
            message_en=f"{fc_impact['rain_next_48h_mm']:.0f} mm of rain forecast in the next 48 hours",
            data_key="forecast_rain_48h_mm",
            data_value=str(fc_impact["rain_next_48h_mm"]),
        ))

    reasons.append(ReasonEntry(
        order=next_order(),
        category="trigger",
        message_pt=trigger_reason,
        message_en=trigger_reason,
    ))

    if dose and dose.capped:
        cap_pt = dose.cap_reason or ""
        cap_pt = cap_pt.replace("Below minimum", "abaixo do mínimo configurado").replace(
            "Capped at maximum", "limitada ao máximo configurado").replace(
            "Capped at max runtime", "limitada ao tempo máximo de rega")
        reasons.append(ReasonEntry(
            order=next_order(),
            category="dosage",
            message_pt=f"Dose ajustada — {cap_pt}",
            message_en=f"Dose adjusted — {dose.cap_reason}",
        ))

    if ctx.defaults_used:
        defaults_pt = _format_engine_notes_pt(ctx.defaults_used)
        defaults_en = _format_engine_notes_en(ctx.defaults_used)
        reasons.append(ReasonEntry(
            order=next_order(),
            category="config",
            message_pt=f"Alguns parâmetros foram inferidos pelo motor (revê a configuração para maior precisão): {'; '.join(defaults_pt)}",
            message_en=f"Some parameters were inferred by the engine (review configuration for better accuracy): {'; '.join(defaults_en)}",
        ))

    if ctx.missing_config:
        missing_pt = _format_engine_notes_pt(ctx.missing_config)
        missing_en = _format_engine_notes_en(ctx.missing_config)
        reasons.append(ReasonEntry(
            order=next_order(),
            category="config",
            message_pt=f"Configuração incompleta — a recomendação pode ser menos precisa: {'; '.join(missing_pt)}",
            message_en=f"Incomplete configuration — recommendation may be less accurate: {'; '.join(missing_en)}",
        ))

    conf_label = {"high": "alta", "medium": "média", "low": "baixa"}.get(conf.level, conf.level)
    conf_hint = {
        "high": "todos os dados estão configurados e actualizados",
        "medium": "alguns parâmetros foram estimados",
        "low": "faltam dados importantes — configure o sector para melhorar",
    }.get(conf.level, "")
    reasons.append(ReasonEntry(
        order=next_order(),
        category="confidence",
        message_pt=f"Fiabilidade da análise: {conf_label} ({conf.score:.0%}) — {conf_hint}",
        message_en=f"Analysis reliability: {conf.level} ({conf.score:.0%})",
        data_key="confidence_score",
        data_value=str(conf.score),
    ))

    return reasons


def _format_engine_notes_pt(notes: list[str]) -> list[str]:
    """Render internal engine note tokens as user-facing Portuguese."""
    return [_format_engine_note_pt(note) for note in notes]


def _format_engine_notes_en(notes: list[str]) -> list[str]:
    """Keep English API text readable when internal notes are terse tokens."""
    return [_format_engine_note_en(note) for note in notes]


def _format_engine_note_pt(note: str) -> str:
    if note == "soil FC/PWP (not configured, using clay-loam defaults)":
        return "CC/PMP do solo não configurados; usados valores por defeito de solo franco-argiloso"
    if note == "Kc/MAD/root_depth (no crop profile found)":
        return "Kc, MAD e profundidade radicular estimados porque não há perfil de cultura"
    if note == "crop profile not created":
        return "perfil de cultura não criado"
    if note == "irrigation system not configured":
        return "sistema de rega não configurado"

    calib_match = re.fullmatch(
        r"FC/refill calibrated from probe envelope \((?P<method>[^,]+), FC=(?P<fc>[^)]+)\)",
        note,
    )
    if calib_match:
        method = {
            "cycles": "ciclos",
            "envelope": "envolvente",
        }.get(calib_match.group("method"), calib_match.group("method"))
        return (
            "CC e linha de recarga efectiva calibradas pela sonda "
            f"(método: {method}, CC={calib_match.group('fc')})"
        )

    kc_match = re.fullmatch(r"Kc=(?P<kc>[0-9.]+) \((?P<source>.+)\)", note)
    if kc_match:
        return f"Kc={kc_match.group('kc')} ({_translate_note_fragment_pt(kc_match.group('source'))})"

    root_match = re.fullmatch(
        r"root_depth=(?P<depth>[0-9.]+)m \(young tree, age (?P<age>[0-9]+)yr\)",
        note,
    )
    if root_match:
        return (
            f"profundidade radicular={root_match.group('depth')} m "
            f"(árvore jovem, {root_match.group('age')} anos)"
        )

    gdd_match = re.fullmatch(
        r"GDD-estimated stage \((?P<stage>[^,]+), (?P<gdd>[0-9.]+) GDD\)",
        note,
    )
    if gdd_match:
        return (
            f"fase estimada por GDD ({gdd_match.group('stage')}, "
            f"{gdd_match.group('gdd')} GDD)"
        )

    return _translate_note_fragment_pt(note)


def _format_engine_note_en(note: str) -> str:
    if note.startswith("FC/refill calibrated from probe envelope"):
        return note.replace("FC/refill", "FC/effective refill line", 1)
    return note


def _translate_note_fragment_pt(text: str) -> str:
    replacements = {
        "default": "valor por defeito",
        "stage not set": "fase não definida",
        "using highest Kc as mid-season proxy": "usado o Kc mais alto como aproximação de meia estação",
        "no crop profile": "sem perfil de cultura",
        "check sector setup": "verifica a configuração do sector",
        "profile stage": "fase do perfil",
        "stage average": "média da fase",
        "irrigation system": "sistema de rega",
        "not configured": "não configurado",
        "crop profile": "perfil de cultura",
        "created": "criado",
    }
    translated = text
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated
