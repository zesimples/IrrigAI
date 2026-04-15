"""Data ingestion service.

Fetches from adapters, applies calibration, deduplicates, flags quality issues,
and persists to the database.

Quality flags:
  "ok"      — value within plausible range, no anomaly
  "invalid" — value outside physically possible range
  "suspect" — value passed but something is unusual (rapid change)

Supported units:
  "vwc_m3m3"         — volumetric water content, valid range 0–0.60
  "soil_tension_cbar" — Watermark suction in cBar, valid range 0–200
                        negative values → "invalid" (sensor error / saturation flag)
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.adapters.base import ProbeDataProvider, WeatherDataProvider
from app.adapters.dto import (
    IngestionSummary,
    ProbeReadingDTO,
    WeatherForecastDTO,
    WeatherObservationDTO,
)
from app.models import Probe, ProbeDepth, ProbeReading, WeatherForecast, WeatherObservation

logger = logging.getLogger(__name__)

# Quality thresholds — VWC
VWC_MIN = 0.0
VWC_MAX = 0.60
VWC_JUMP_MAX_PER_HOUR = 0.15  # m³/m³ — above this in one hour → suspect

# Quality thresholds — soil tension (Watermark cBar)
TENSION_MIN = 0.0       # 0 = saturated / ponded
TENSION_MAX = 200.0     # Watermark 200SS upper limit; >200 means extremely dry
TENSION_JUMP_MAX = 50.0 # cBar jump per reading → suspect (rapid drainage artifact)


def _quality_flag(value: float, unit: str, prev_value: float | None) -> str:
    if unit == "vwc_m3m3":
        if value < VWC_MIN or value > VWC_MAX:
            return "invalid"
        if prev_value is not None and abs(value - prev_value) > VWC_JUMP_MAX_PER_HOUR:
            return "suspect"
    elif unit == "soil_tension_cbar":
        if value < TENSION_MIN:
            return "invalid"  # negative = sensor error / hardware fault
        if value > TENSION_MAX:
            return "suspect"  # above measurable range — extremely dry or disconnected
        if prev_value is not None and abs(value - prev_value) > TENSION_JUMP_MAX:
            return "suspect"
    return "ok"


# ---------------------------------------------------------------------------
# Probe ingestion
# ---------------------------------------------------------------------------

async def ingest_probe_readings(
    session: AsyncSession,
    provider: ProbeDataProvider,
    probe_external_id: str,
    since: datetime,
    until: datetime,
) -> IngestionSummary:
    """Fetch readings for a probe and persist new ones to probe_reading.

    Deduplication: skips any (probe_depth_id, timestamp) pair that already exists.
    Calibration: applies ProbeDepth.calibration_offset and calibration_factor.
    """
    summary = IngestionSummary(probe_external_id=probe_external_id)

    await provider.authenticate()
    readings: list[ProbeReadingDTO] = await provider.fetch_readings(
        probe_external_id=probe_external_id,
        since=since,
        until=until,
    )

    if not readings:
        return summary

    # Load the probe and its depth records
    probe_result = await session.execute(
        select(Probe).where(Probe.external_id == probe_external_id)
    )
    probe = probe_result.scalar_one_or_none()
    if probe is None:
        logger.warning("Probe external_id=%s not found in DB — skipping", probe_external_id)
        summary.errors += len(readings)
        return summary

    depth_records_result = await session.execute(
        select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)
    )
    depth_map: dict[int, ProbeDepth] = {
        pd.depth_cm: pd for pd in depth_records_result.scalars().all()
    }

    # Group readings by depth to track prev_value for jump detection
    by_depth: dict[int, list[ProbeReadingDTO]] = {}
    for r in readings:
        by_depth.setdefault(r.depth_cm, []).append(r)
    for depth_readings in by_depth.values():
        depth_readings.sort(key=lambda x: x.timestamp)

    # Load existing timestamps per depth for dedup (query once per depth)
    existing_per_depth: dict[str, set[datetime]] = {}
    for depth_cm, pd_record in depth_map.items():
        result = await session.execute(
            select(ProbeReading.timestamp).where(
                ProbeReading.probe_depth_id == pd_record.id,
                ProbeReading.timestamp >= since,
                ProbeReading.timestamp <= until,
            )
        )
        existing_per_depth[pd_record.id] = {row[0] for row in result.fetchall()}

    # Insert new readings
    to_insert: list[ProbeReading] = []
    for depth_cm, depth_readings in by_depth.items():
        pd_record = depth_map.get(depth_cm)
        if pd_record is None:
            logger.debug("No ProbeDepth record for depth=%dcm probe=%s — skipping", depth_cm, probe_external_id)
            summary.skipped_duplicate += len(depth_readings)
            continue

        existing_ts = existing_per_depth.get(pd_record.id, set())
        prev_value: float | None = None

        for r in depth_readings:
            # Normalise to UTC-aware
            ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=UTC)

            # Dedup
            if ts in existing_ts:
                summary.skipped_duplicate += 1
                continue

            # Calibrated value
            calibrated = (r.raw_value * pd_record.calibration_factor) + pd_record.calibration_offset

            # Quality flag
            flag = _quality_flag(calibrated, r.unit, prev_value)
            if r.unit == "vwc_m3m3":
                prev_value = calibrated

            if flag == "invalid":
                summary.flagged_invalid += 1
            elif flag == "suspect":
                summary.flagged_suspect += 1

            to_insert.append(
                ProbeReading(
                    id=str(uuid.uuid4()),
                    probe_depth_id=pd_record.id,
                    timestamp=ts,
                    raw_value=r.raw_value,
                    calibrated_value=calibrated,
                    unit=r.unit,
                    quality_flag=flag,
                )
            )
            existing_ts.add(ts)
            summary.inserted += 1

    if to_insert:
        session.add_all(to_insert)
        await session.flush()

        # Update probe.last_reading_at
        latest_ts = max(r.timestamp for r in to_insert)
        probe.last_reading_at = latest_ts

    logger.info(
        "Probe %s: inserted=%d skipped=%d invalid=%d suspect=%d",
        probe_external_id,
        summary.inserted,
        summary.skipped_duplicate,
        summary.flagged_invalid,
        summary.flagged_suspect,
    )
    return summary


# ---------------------------------------------------------------------------
# Weather ingestion
# ---------------------------------------------------------------------------

async def ingest_weather_observations(
    session: AsyncSession,
    provider: WeatherDataProvider,
    farm_id: str,
    lat: float,
    lon: float,
    since: datetime,
    until: datetime,
    source: str = "unknown",
) -> int:
    """Fetch weather observations and persist new ones. Returns count inserted."""
    await provider.authenticate()
    obs_list: list[WeatherObservationDTO] = await provider.fetch_observations(
        lat=lat, lon=lon, since=since, until=until
    )

    # Load existing timestamps for dedup
    existing_result = await session.execute(
        select(WeatherObservation.timestamp).where(
            WeatherObservation.farm_id == farm_id,
            WeatherObservation.timestamp >= since,
            WeatherObservation.timestamp <= until,
        )
    )
    existing_ts: set[datetime] = {row[0] for row in existing_result.fetchall()}

    inserted = 0
    for obs in obs_list:
        ts = obs.timestamp if obs.timestamp.tzinfo else obs.timestamp.replace(tzinfo=UTC)
        if ts in existing_ts:
            continue
        session.add(
            WeatherObservation(
                id=str(uuid.uuid4()),
                farm_id=farm_id,
                timestamp=ts,
                temperature_max_c=obs.temperature_max_c,
                temperature_min_c=obs.temperature_min_c,
                temperature_mean_c=obs.temperature_mean_c,
                humidity_pct=obs.humidity_pct,
                wind_speed_ms=obs.wind_speed_ms,
                solar_radiation_mjm2=obs.solar_radiation_mjm2,
                rainfall_mm=obs.rainfall_mm,
                et0_mm=obs.et0_mm,
                source=source,
            )
        )
        existing_ts.add(ts)
        inserted += 1

    if inserted:
        await session.flush()

    logger.info("Weather observations for farm %s: inserted=%d", farm_id, inserted)
    return inserted


async def ingest_weather_forecasts(
    session: AsyncSession,
    provider: WeatherDataProvider,
    farm_id: str,
    lat: float,
    lon: float,
    days: int = 5,
    source: str = "unknown",
) -> int:
    """Fetch forecast and upsert (replace today's forecast with latest issued)."""
    await provider.authenticate()
    now = datetime.now(UTC)
    forecasts: list[WeatherForecastDTO] = await provider.fetch_forecast(lat=lat, lon=lon, days=days)

    # Delete existing forecasts for these dates (replaced by fresh run)
    forecast_dates = [f.forecast_date for f in forecasts]
    if forecast_dates:
        await session.execute(
            text("DELETE FROM weather_forecast WHERE farm_id = :farm_id AND forecast_date = ANY(:dates)"),
            {"farm_id": farm_id, "dates": forecast_dates},
        )

    for fc in forecasts:
        session.add(
            WeatherForecast(
                id=str(uuid.uuid4()),
                farm_id=farm_id,
                forecast_date=fc.forecast_date,
                issued_at=now,
                temperature_max_c=fc.temperature_max_c,
                temperature_min_c=fc.temperature_min_c,
                humidity_pct=fc.humidity_pct,
                wind_speed_ms=fc.wind_speed_ms,
                rainfall_mm=fc.rainfall_mm,
                rainfall_probability_pct=fc.rainfall_probability_pct,
                et0_mm=fc.et0_mm,
                source=source,
            )
        )

    if forecasts:
        await session.flush()

    logger.info("Weather forecast for farm %s: upserted=%d days", farm_id, len(forecasts))
    return len(forecasts)


# ---------------------------------------------------------------------------
# Farm-level ingestion wrapper (used by scheduler)
# ---------------------------------------------------------------------------

async def ingest_farm(farm_id: str, db: AsyncSession) -> dict:
    """Run probe + weather ingestion for all probes of a farm.

    Returns counts of inserted records.
    """
    from datetime import timedelta
    from app.adapters.factory import get_probe_provider, get_weather_provider
    from app.config import get_settings
    from app.models import Farm, Plot, Probe, Sector

    settings = get_settings()
    farm = await db.get(Farm, farm_id)
    if farm is None:
        return {}

    probe_provider = get_probe_provider(settings, farm=farm)
    weather_provider = get_weather_provider(settings, farm=farm)
    now = datetime.now(UTC)
    since = now - timedelta(hours=2)

    probe_total = 0
    plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
    for plot in plots_result.scalars().all():
        sectors_result = await db.execute(select(Sector).where(Sector.plot_id == plot.id))
        for sector in sectors_result.scalars().all():
            probes_result = await db.execute(select(Probe).where(Probe.sector_id == sector.id))
            for probe in probes_result.scalars().all():
                try:
                    summary = await ingest_probe_readings(
                        db, probe_provider, probe.external_id, since, now
                    )
                    probe_total += summary.inserted
                except Exception:
                    logger.exception("Ingestion failed for probe %s", probe.external_id)

    weather_total = 0
    if farm.location_lat and farm.location_lon:
        try:
            # Weather data is daily — look back 48 h so we always capture the latest daily record
            weather_since = now - timedelta(hours=48)
            weather_total = await ingest_weather_observations(
                db, weather_provider, farm_id, farm.location_lat, farm.location_lon,
                weather_since, now, source=settings.WEATHER_PROVIDER,
            )
            await ingest_weather_forecasts(
                db, weather_provider, farm_id, farm.location_lat, farm.location_lon,
                days=7, source=settings.WEATHER_PROVIDER,
            )
        except Exception:
            logger.exception("Weather ingestion failed for farm %s", farm_id)

    await db.commit()
    return {"probes_inserted": probe_total, "weather_inserted": weather_total}


# ---------------------------------------------------------------------------
# Synchronous wrappers (for seed script / scheduler use)
# ---------------------------------------------------------------------------

def ingest_probe_readings_sync(
    session: Session,
    provider: ProbeDataProvider,
    probe_external_id: str,
    since: datetime,
    until: datetime,
) -> IngestionSummary:
    """Synchronous version using a sync SQLAlchemy session."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    # Run synchronously via a thread-local event loop
    loop = asyncio.new_event_loop()
    try:
        # We can't reuse the sync session as async — delegate to sync SQL directly
        summary = IngestionSummary(probe_external_id=probe_external_id)

        import asyncio as _asyncio

        readings: list[ProbeReadingDTO] = loop.run_until_complete(
            provider.fetch_readings(probe_external_id, since, until)
        )

        from sqlalchemy import select as _select

        probe = session.execute(
            _select(Probe).where(Probe.external_id == probe_external_id)
        ).scalar_one_or_none()

        if probe is None:
            summary.errors += len(readings)
            return summary

        depth_map = {
            pd.depth_cm: pd
            for pd in session.execute(
                _select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)
            ).scalars().all()
        }

        by_depth: dict[int, list[ProbeReadingDTO]] = {}
        for r in readings:
            by_depth.setdefault(r.depth_cm, []).append(r)
        for dr in by_depth.values():
            dr.sort(key=lambda x: x.timestamp)

        existing_per_depth: dict[str, set[datetime]] = {}
        for depth_cm, pd_record in depth_map.items():
            result = session.execute(
                _select(ProbeReading.timestamp).where(
                    ProbeReading.probe_depth_id == pd_record.id,
                    ProbeReading.timestamp >= since,
                    ProbeReading.timestamp <= until,
                )
            )
            existing_per_depth[pd_record.id] = {row[0] for row in result.fetchall()}

        to_insert = []
        for depth_cm, depth_readings in by_depth.items():
            pd_record = depth_map.get(depth_cm)
            if pd_record is None:
                summary.skipped_duplicate += len(depth_readings)
                continue

            existing_ts = existing_per_depth.get(pd_record.id, set())
            prev_value: float | None = None

            for r in depth_readings:
                ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=UTC)
                if ts in existing_ts:
                    summary.skipped_duplicate += 1
                    continue

                calibrated = (r.raw_value * pd_record.calibration_factor) + pd_record.calibration_offset
                flag = _quality_flag(calibrated, r.unit, prev_value)
                if r.unit == "vwc_m3m3":
                    prev_value = calibrated

                if flag == "invalid":
                    summary.flagged_invalid += 1
                elif flag == "suspect":
                    summary.flagged_suspect += 1

                to_insert.append(
                    ProbeReading(
                        id=str(uuid.uuid4()),
                        probe_depth_id=pd_record.id,
                        timestamp=ts,
                        raw_value=r.raw_value,
                        calibrated_value=calibrated,
                        unit=r.unit,
                        quality_flag=flag,
                    )
                )
                existing_ts.add(ts)
                summary.inserted += 1

        if to_insert:
            session.add_all(to_insert)
            session.flush()
            probe.last_reading_at = max(r.timestamp for r in to_insert)

        return summary
    finally:
        loop.close()
