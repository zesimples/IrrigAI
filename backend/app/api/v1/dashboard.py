"""Dashboard aggregation endpoint.

Returns a complete farm snapshot: weather, sector summaries, alerts, and missing-data prompts.
All data is read from DB — no engine is re-run here.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Access
from app.database import get_db
from app.engine.et0 import compute_et0
from app.engine.types import DailyWeather
from app.models import (
    Alert,
    Flowmeter,
    IrrigationEvent,
    Plot,
    Probe,
    ProviderSyncLog,
    Recommendation,
    Sector,
    WeatherForecast,
    WeatherObservation,
)
from app.schemas.dashboard import (
    AlertCounts,
    DashboardResponse,
    FarmOut,
    SectorSummary,
    SyncStatusEntry,
    WeatherToday,
)

router = APIRouter(tags=["dashboard"])


def _build_weather_today(
    farm_lat: float | None,
    latest_obs: WeatherObservation | None,
    forecasts: list[WeatherForecast],
    today,
) -> WeatherToday:
    """Assemble a WeatherToday card from one observation + up-to-2 forecast rows.

    Observation-less inputs (a plot with no station, e.g. a forecast-only polo)
    fall back to the nearest forecast row for temperature/humidity/wind so the
    card shows that plot's own forecast rather than another station's readings.
    """
    rain_48h = sum((f.rainfall_mm or 0.0) for f in forecasts[:2])
    rain_prob = forecasts[0].rainfall_probability_pct if forecasts else None

    # ET₀ resolution order:
    # 1. Today's observed value from the weather station (end-of-day aggregate)
    # 2. Today's forecast value (referenceevapotranspiration_fao)
    # 3. Any near-future forecast value (API may not include today)
    # 4. Computed from observed Tmax/Tmin via Hargreaves (needs only temperature)
    et0_today = latest_obs.et0_mm if latest_obs else None

    if et0_today is None and forecasts:
        # Try any forecast within the next 2 days that has ET₀
        for fc in forecasts[:2]:
            if fc.et0_mm is not None:
                et0_today = fc.et0_mm
                break

    if et0_today is None and latest_obs and latest_obs.temperature_max_c and latest_obs.temperature_min_c:
        # Last resort: Hargreaves estimate from today's observed temperatures
        dw = DailyWeather(
            date=today,
            t_max=latest_obs.temperature_max_c,
            t_min=latest_obs.temperature_min_c,
            t_mean=latest_obs.temperature_mean_c,
            humidity_pct=latest_obs.humidity_pct,
            wind_ms=latest_obs.wind_speed_ms,
            solar_mjm2=latest_obs.solar_radiation_mjm2,
        )
        et0_today, _ = compute_et0(dw, farm_lat or 38.5)  # Alentejo default lat

    fc0 = forecasts[0] if latest_obs is None and forecasts else None
    t_max = latest_obs.temperature_max_c if latest_obs else (fc0.temperature_max_c if fc0 else None)
    t_min = latest_obs.temperature_min_c if latest_obs else (fc0.temperature_min_c if fc0 else None)
    humidity = latest_obs.humidity_pct if latest_obs else (fc0.humidity_pct if fc0 else None)
    wind_ms = latest_obs.wind_speed_ms if latest_obs else (fc0.wind_speed_ms if fc0 else None)

    return WeatherToday(
        et0_mm=et0_today,
        temperature_max_c=t_max,
        temperature_min_c=t_min,
        rainfall_mm=latest_obs.rainfall_mm if latest_obs else None,
        forecast_rain_next_48h_mm=rain_48h,
        forecast_rain_probability=rain_prob,
        humidity_pct=humidity,
        wind_speed_kmh=round(wind_ms * 3.6, 1) if wind_ms else None,
    )


@router.get("/farms/{farm_id}/dashboard", response_model=DashboardResponse)
async def get_dashboard(farm_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    farm = await access.farm(farm_id)

    today = datetime.now(UTC).date()

    # --- Weather (farm-level: latest row regardless of plot scope) ---
    latest_obs = (
        await db.execute(
            select(WeatherObservation)
            .where(WeatherObservation.farm_id == farm_id)
            .order_by(WeatherObservation.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    forecasts = (
        await db.execute(
            select(WeatherForecast)
            .where(WeatherForecast.farm_id == farm_id)
            .order_by(WeatherForecast.forecast_date)
            .limit(2)
        )
    ).scalars().all()

    weather_today = _build_weather_today(farm.location_lat, latest_obs, list(forecasts), today)

    # --- Per-plot weather (plots with their own station/forecast, e.g. Innoliva) ---
    plot_ids_with_weather = {
        pid
        for pid in (
            await db.execute(
                select(WeatherObservation.plot_id)
                .where(
                    WeatherObservation.farm_id == farm_id,
                    WeatherObservation.plot_id.is_not(None),
                )
                .distinct()
            )
        ).scalars()
    } | {
        pid
        for pid in (
            await db.execute(
                select(WeatherForecast.plot_id)
                .where(
                    WeatherForecast.farm_id == farm_id,
                    WeatherForecast.plot_id.is_not(None),
                )
                .distinct()
            )
        ).scalars()
    }

    weather_by_plot: dict[str, WeatherToday] = {}
    for pid in plot_ids_with_weather:
        obs_p = (
            await db.execute(
                select(WeatherObservation)
                .where(
                    WeatherObservation.farm_id == farm_id,
                    WeatherObservation.plot_id == pid,
                )
                .order_by(WeatherObservation.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        forecasts_p = (
            await db.execute(
                select(WeatherForecast)
                .where(
                    WeatherForecast.farm_id == farm_id,
                    WeatherForecast.plot_id == pid,
                )
                .order_by(WeatherForecast.forecast_date)
                .limit(2)
            )
        ).scalars().all()
        weather_by_plot[pid] = _build_weather_today(
            farm.location_lat, obs_p, list(forecasts_p), today
        )

    # --- Load all sectors for this farm ---
    from app.active_records import active_plots_stmt

    plots = (await db.execute(active_plots_stmt(farm_id))).scalars().all()

    plot_name_by_id: dict[str, str] = {p.id: p.name for p in plots}
    plot_ids = [p.id for p in plots]
    # Only include sectors that have at least one soil probe — flowmeter-only
    # sectors belong on the Caudalímetros page, not in Recomendações.
    sectors: list[Sector] = []
    if plot_ids:
        sectors = (
            await db.execute(
                select(Sector)
                .where(
                    Sector.plot_id.in_(plot_ids),
                    Sector.is_archived.is_(False),
                    exists().where(Probe.sector_id == Sector.id),
                )
            )
        ).scalars().all()

    # --- Per-sector aggregation ---
    sector_summaries: list[SectorSummary] = []
    all_alerts_critical = all_alerts_warning = all_alerts_info = 0
    missing_prompts: list[str] = []

    for sector in sectors:
        sid = sector.id

        # Latest recommendation
        latest_rec = (
            await db.execute(
                select(Recommendation)
                .where(Recommendation.sector_id == sid)
                .order_by(Recommendation.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        # Active alerts for this sector
        sec_alerts = (
            await db.execute(
                select(Alert).where(Alert.sector_id == sid, Alert.is_active.is_(True))
            )
        ).scalars().all()
        crit = sum(1 for a in sec_alerts if a.severity == "critical")
        warn = sum(1 for a in sec_alerts if a.severity == "warning")
        info = sum(1 for a in sec_alerts if a.severity == "info")
        all_alerts_critical += crit
        all_alerts_warning += warn
        all_alerts_info += info

        # Last irrigation event
        last_event = (
            await db.execute(
                select(IrrigationEvent)
                .where(IrrigationEvent.sector_id == sid)
                .order_by(IrrigationEvent.start_time.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        # Probe health
        probes = (
            await db.execute(select(Probe).where(Probe.sector_id == sid))
        ).scalars().all()

        has_probe_readings = any(p.last_reading_at is not None for p in probes)

        if not probes:
            probe_health = "no_probes"
        elif not has_probe_readings:
            probe_health = "no_readings"
        elif any(p.health_status in ("error", "offline") for p in probes):
            probe_health = "error"
        elif any(p.health_status == "warning" for p in probes):
            probe_health = "warning"
        else:
            probe_health = "ok"

        # Rootzone status from snapshot
        rootzone_status = "unknown"
        depletion_pct: float | None = None
        if latest_rec and latest_rec.inputs_snapshot:
            snap = latest_rec.inputs_snapshot
            taw_mm = snap.get("taw_mm")
            depletion_mm = snap.get("depletion_mm")
            if taw_mm and depletion_mm is not None and taw_mm > 0:
                pct = depletion_mm / taw_mm * 100
                depletion_pct = round(pct, 1)
                if pct < 20:
                    rootzone_status = "wet"
                elif pct < 60:
                    rootzone_status = "optimal"
                elif pct < 85:
                    rootzone_status = "dry"
                else:
                    rootzone_status = "critical"

        rec_snap = (latest_rec.inputs_snapshot or {}) if latest_rec else {}
        rec_dose_pres = rec_snap.get("dose_presentation") or {}

        sector_summaries.append(SectorSummary(
            sector_id=sid,
            sector_name=sector.name,
            crop_type=sector.crop_type,
            plot_id=sector.plot_id,
            plot_name=plot_name_by_id.get(sector.plot_id, ""),
            current_stage=sector.current_phenological_stage,
            action=latest_rec.action if latest_rec else None,
            irrigation_depth_mm=latest_rec.irrigation_depth_mm if latest_rec else None,
            runtime_min=latest_rec.irrigation_runtime_min if latest_rec else None,
            # Upgrade stored "low" → "medium" only when probes have actual readings.
            confidence_level=(
                "medium"
                if latest_rec and latest_rec.confidence_level == "low" and has_probe_readings
                else (latest_rec.confidence_level if latest_rec else None)
            ),
            confidence_score=latest_rec.confidence_score if latest_rec else None,
            rootzone_status=rootzone_status,
            depletion_pct=depletion_pct,
            active_alerts=crit + warn + info,
            probe_health=probe_health,
            last_irrigated=last_event.start_time.date() if last_event else None,
            last_irrigated_mm=last_event.applied_mm if last_event else None,
            recommendation_generated_at=latest_rec.generated_at if latest_rec else None,
            source_confidence=(
                (latest_rec.inputs_snapshot or {}).get("source_confidence")
                if latest_rec else None
            ),
            dose_band=rec_snap.get("dose_band"),
            dose_source=rec_snap.get("dose_source"),
            habitual_factor=rec_dose_pres.get("habitual_factor"),
            estimated_runtime_min=rec_dose_pres.get("estimated_runtime_min"),
        ))

        # Missing data prompts (Portuguese, shown to user)
        if not latest_rec:
            missing_prompts.append(
                f"O setor '{sector.name}' não tem recomendação gerada. "
                f"Clique em 'Gerar' para obter a recomendação de hoje."
            )
        elif sector.current_phenological_stage is None:
            missing_prompts.append(
                f"O estádio fenológico do '{sector.name}' não está definido. "
                f"Defina-o para melhorar as recomendações."
            )

    # --- Provider sync status ---
    sync_log_rows = (
        await db.execute(
            select(ProviderSyncLog).where(ProviderSyncLog.farm_id == farm_id)
        )
    ).scalars().all()
    sync_status = [
        SyncStatusEntry(
            provider=row.provider,
            last_success_at=row.last_success_at,
            last_error_at=row.last_error_at,
            last_error_msg=row.last_error_msg,
            last_latency_ms=row.last_latency_ms,
            last_records_inserted=row.last_records_inserted,
            consecutive_failures=row.consecutive_failures,
        )
        for row in sync_log_rows
    ]

    # Check if this farm has any active flowmeters
    has_flowmeters_result = await db.execute(
        select(
            exists().where(
                Flowmeter.is_active.is_(True),
                Flowmeter.sector_id == Sector.id,
                Sector.plot_id == Plot.id,
                Plot.farm_id == farm_id,
            )
        )
    )
    has_flowmeters = bool(has_flowmeters_result.scalar())

    return DashboardResponse(
        farm=FarmOut(id=farm.id, name=farm.name, region=farm.region),
        date=today,
        weather_today=weather_today,
        weather_by_plot=weather_by_plot,
        sectors_summary=sector_summaries,
        active_alerts_count=AlertCounts(
            critical=all_alerts_critical,
            warning=all_alerts_warning,
            info=all_alerts_info,
        ),
        missing_data_prompts=missing_prompts,
        sync_status=sync_status,
        has_flowmeters=has_flowmeters,
    )
