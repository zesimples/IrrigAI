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
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func as sql_func
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.adapters.base import ProbeDataProvider, WeatherDataProvider
from app.adapters.dto import (
    IngestionSummary,
    ProbeReadingDTO,
    WeatherForecastDTO,
    WeatherObservationDTO,
)
from app.models import Probe, ProbeDepth, ProbeReading, ProviderSyncLog, WeatherForecast, WeatherObservation

logger = logging.getLogger(__name__)

# Adaptive lookback — cap gap-fill at 7 days to avoid unbounded API requests
MAX_ADAPTIVE_LOOKBACK_HOURS = 168


def _adaptive_since(last_ts: datetime | None, default_lookback_hours: int, now: datetime) -> datetime:
    """Return the fetch window start, extending back to cover any gap.

    If the last known record is within the default window, return the normal
    default_since.  If a gap is detected (e.g. after a worker restart), extend
    back to just before the last known record, capped at MAX_ADAPTIVE_LOOKBACK_HOURS.
    """
    default_since = now - timedelta(hours=default_lookback_hours)
    if last_ts is None:
        return default_since
    ts = last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=UTC)
    if ts >= default_since:
        return default_since
    gap_hours = (now - ts).total_seconds() / 3600
    adaptive = max(ts - timedelta(minutes=5), now - timedelta(hours=MAX_ADAPTIVE_LOOKBACK_HOURS))
    logger.info(
        "Adaptive lookback: last record %s is %.1fh ago — extending window to %s",
        ts.isoformat(), gap_hours, adaptive.isoformat(),
    )
    return adaptive


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
# Sync-log upsert
# ---------------------------------------------------------------------------

async def _upsert_sync_log(
    db: AsyncSession,
    farm_id: str,
    provider: str,
    error_msg: str | None,
    latency_ms: int,
    records_inserted: int,
) -> None:
    """Upsert a provider_sync_log row for the given farm+provider.

    On success (error_msg is None): update last_success_at and reset consecutive_failures.
    On failure: update last_error_at/msg and increment consecutive_failures.
    """
    now = datetime.now(UTC)
    if error_msg is None:
        update_fields = {
            "last_success_at": now,
            "last_error_msg": None,
            "last_latency_ms": latency_ms,
            "last_records_inserted": records_inserted,
            "consecutive_failures": 0,
            "updated_at": now,
        }
    else:
        update_fields = {
            "last_error_at": now,
            "last_error_msg": error_msg[:500],
            "last_latency_ms": latency_ms,
            "last_records_inserted": records_inserted,
            "consecutive_failures": ProviderSyncLog.consecutive_failures + 1,
            "updated_at": now,
        }

    stmt = (
        pg_insert(ProviderSyncLog)
        .values(
            id=str(uuid.uuid4()),
            farm_id=farm_id,
            provider=provider,
            last_success_at=now if error_msg is None else None,
            last_error_at=now if error_msg is not None else None,
            last_error_msg=error_msg[:500] if error_msg else None,
            last_latency_ms=latency_ms,
            last_records_inserted=records_inserted,
            consecutive_failures=0 if error_msg is None else 1,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_provider_sync_log_farm_provider",
            set_=update_fields,
        )
    )
    await db.execute(stmt)


# ---------------------------------------------------------------------------
# Farm-level ingestion wrapper (used by scheduler)
# ---------------------------------------------------------------------------

async def ingest_farm(farm_id: str, db: AsyncSession, lookback_hours: int = 2) -> dict:
    """Run probe + weather ingestion for all probes of a farm.

    Returns counts of inserted records.
    lookback_hours: how far back to fetch probe readings (default 2h for scheduler,
                    use a larger value for initial backfill).
    """
    from datetime import timedelta
    from app.adapters.factory import get_probe_provider, get_weather_provider
    from app.config import get_settings
    from app.models import Farm, FarmCredentials, Plot, Probe, Sector
    from sqlalchemy.orm import selectinload

    settings = get_settings()
    farm_result = await db.execute(
        select(Farm).where(Farm.id == farm_id).options(selectinload(Farm.credentials))
    )
    farm = farm_result.scalar_one_or_none()
    if farm is None:
        return {}

    probe_provider = get_probe_provider(settings, farm=farm)
    weather_provider = get_weather_provider(settings, farm=farm)
    now = datetime.now(UTC)

    # ── Probe ingestion ───────────────────────────────────────────────────────
    probe_total = 0
    probe_error: str | None = None
    probe_t0 = time.monotonic()
    try:
        plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
        for plot in plots_result.scalars().all():
            sectors_result = await db.execute(select(Sector).where(Sector.plot_id == plot.id))
            for sector in sectors_result.scalars().all():
                probes_result = await db.execute(select(Probe).where(Probe.sector_id == sector.id))
                for probe in probes_result.scalars().all():
                    probe_since = _adaptive_since(probe.last_reading_at, lookback_hours, now)
                    try:
                        summary = await ingest_probe_readings(
                            db, probe_provider, probe.external_id, probe_since, now
                        )
                        probe_total += summary.inserted
                    except Exception as exc:
                        probe_error = str(exc)
                        logger.exception("Ingestion failed for probe %s", probe.external_id)
    except Exception as exc:
        probe_error = str(exc)
        logger.exception("Probe ingestion batch failed for farm %s", farm_id)
    probe_latency_ms = int((time.monotonic() - probe_t0) * 1000)

    # ── Weather ingestion ─────────────────────────────────────────────────────
    weather_total = 0
    weather_error: str | None = None
    weather_t0 = time.monotonic()
    if farm.location_lat and farm.location_lon:
        try:
            latest_obs_result = await db.execute(
                select(sql_func.max(WeatherObservation.timestamp)).where(
                    WeatherObservation.farm_id == farm_id
                )
            )
            latest_obs_ts = latest_obs_result.scalar_one_or_none()
            # Weather is daily; default 48h window ensures the current day is always captured
            weather_since = _adaptive_since(latest_obs_ts, 48, now)
            weather_total = await ingest_weather_observations(
                db, weather_provider, farm_id, farm.location_lat, farm.location_lon,
                weather_since, now, source=settings.WEATHER_PROVIDER,
            )
            await ingest_weather_forecasts(
                db, weather_provider, farm_id, farm.location_lat, farm.location_lon,
                days=7, source=settings.WEATHER_PROVIDER,
            )
        except Exception as exc:
            weather_error = str(exc)
            logger.exception("Weather ingestion failed for farm %s", farm_id)
    weather_latency_ms = int((time.monotonic() - weather_t0) * 1000)

    # ── Sync log upsert ───────────────────────────────────────────────────────
    await _upsert_sync_log(
        db, farm_id,
        f"{settings.PROBE_PROVIDER}:probes",
        probe_error, probe_latency_ms, probe_total,
    )
    if farm.location_lat and farm.location_lon:
        await _upsert_sync_log(
            db, farm_id,
            f"{settings.WEATHER_PROVIDER}:weather",
            weather_error, weather_latency_ms, weather_total,
        )

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
