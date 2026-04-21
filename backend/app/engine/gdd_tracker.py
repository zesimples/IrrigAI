"""GDD (Growing Degree Days) phenological stage tracker.

Accumulates daily GDD since a reference date and suggests phenological stage
transitions based on thresholds stored in SectorCropProfile.stages JSONB.

GDD = max(0, (Tmax + Tmin) / 2 - Tbase)
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class GDDStatus:
    sector_id: str
    sector_name: str
    crop_type: str
    reference_date: date
    accumulated_gdd: float
    tbase_c: float

    current_stage: str | None
    suggested_stage: str | None
    suggested_stage_name_pt: str | None
    suggested_stage_name_en: str | None
    suggested_kc: float | None          # Kc of the suggested stage (for pipeline fallback)
    stage_changed: bool

    days_in_current_stage: int | None
    next_stage: str | None
    next_stage_name_pt: str | None
    gdd_to_next_stage: float | None

    confidence: str                     # "high" | "low"
    missing_weather_days: int

    suggestion_pt: str | None
    suggestion_en: str | None


class GDDTracker:

    async def compute_accumulated_gdd(
        self, sector_id: str, db: AsyncSession, scp_stages: list[dict] | None = None
    ) -> GDDStatus | None:
        from app.models import Plot, Sector, SectorCropProfile, WeatherObservation

        sector = await db.get(Sector, sector_id)
        if sector is None:
            return None

        plot = await db.get(Plot, sector.plot_id)
        if plot is None:
            return None

        farm_id = plot.farm_id

        # Load crop profile stages
        if scp_stages is None:
            scp_result = await db.execute(
                select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
            )
            scp = scp_result.scalar_one_or_none()
            stages = scp.stages if scp else []
        else:
            stages = scp_stages

        if not stages:
            return None

        # Determine tbase from stages
        tbase = 10.0
        for s in stages:
            if s.get("tbase_c") is not None:
                tbase = float(s["tbase_c"])
                break

        # Determine reference date
        if sector.crop_type == "maize":
            if sector.sowing_date is None:
                return None
            ref_date = sector.sowing_date
        else:
            # Perennials: Feb 1 of current year
            ref_date = date(datetime.now(UTC).year, 2, 1)

        # Load weather observations since ref_date
        ref_dt = datetime(ref_date.year, ref_date.month, ref_date.day, tzinfo=UTC)
        obs_result = await db.execute(
            select(WeatherObservation)
            .where(
                WeatherObservation.farm_id == farm_id,
                WeatherObservation.timestamp >= ref_dt,
            )
            .order_by(WeatherObservation.timestamp)
        )
        observations = obs_result.scalars().all()

        # De-duplicate by date (take best record per day)
        daily: dict[date, WeatherObservation] = {}
        for obs in observations:
            obs_date = obs.timestamp.date()
            if obs_date not in daily:
                daily[obs_date] = obs
            elif obs.temperature_max_c is not None and daily[obs_date].temperature_max_c is None:
                daily[obs_date] = obs

        # Accumulate GDD
        total_gdd = 0.0
        missing_days = 0
        today = datetime.now(UTC).date()
        expected_days = (today - ref_date).days

        for d in (ref_date + timedelta(n) for n in range(expected_days)):
            obs = daily.get(d)
            if obs is None or obs.temperature_max_c is None or obs.temperature_min_c is None:
                missing_days += 1
                continue
            gdd = max(0.0, (obs.temperature_max_c + obs.temperature_min_c) / 2.0 - tbase)
            total_gdd += gdd

        # Find suggested stage from GDD thresholds
        stages_with_gdd = [s for s in stages if s.get("gdd_min") is not None and s.get("gdd_max") is not None]

        suggested_stage: str | None = None
        suggested_stage_name_pt: str | None = None
        suggested_stage_name_en: str | None = None
        suggested_kc: float | None = None
        next_stage: str | None = None
        next_stage_name_pt: str | None = None
        gdd_to_next_stage: float | None = None

        if stages_with_gdd:
            # Sort by gdd_min
            sorted_stages = sorted(stages_with_gdd, key=lambda s: s["gdd_min"])

            for i, s in enumerate(sorted_stages):
                if total_gdd >= s["gdd_min"]:
                    suggested_stage = s["key"]
                    suggested_stage_name_pt = s.get("name_pt") or s.get("key")
                    suggested_stage_name_en = s.get("name_en") or s.get("key")
                    suggested_kc = float(s.get("kc", 0.8))
                    # Next stage
                    if i + 1 < len(sorted_stages):
                        ns = sorted_stages[i + 1]
                        next_stage = ns["key"]
                        next_stage_name_pt = ns.get("name_pt")
                        gdd_to_next_stage = round(ns["gdd_min"] - total_gdd, 1)

        current_stage = sector.current_phenological_stage
        stage_changed = (
            suggested_stage is not None
            and current_stage != suggested_stage
        )

        # Days in current stage (rough estimate from GDD velocity)
        days_in_current_stage: int | None = None
        if current_stage and daily:
            # Count days since accumulated GDD crossed into current stage
            stage_dict = next((s for s in stages_with_gdd if s["key"] == current_stage), None)
            if stage_dict:
                gdd_entry = float(stage_dict.get("gdd_min", 0))
                running = 0.0
                for d in (ref_date + timedelta(n) for n in range(expected_days)):
                    obs = daily.get(d)
                    if obs and obs.temperature_max_c and obs.temperature_min_c:
                        running += max(0.0, (obs.temperature_max_c + obs.temperature_min_c) / 2.0 - tbase)
                    if running >= gdd_entry:
                        days_in_current_stage = (today - d).days
                        break

        confidence = "low" if missing_days > 10 else "high"

        suggestion_pt, suggestion_en = _build_suggestion(
            stage_changed, current_stage, suggested_stage_name_pt, suggested_stage_name_en,
            round(total_gdd, 0), ref_date
        )

        return GDDStatus(
            sector_id=sector_id,
            sector_name=sector.name,
            crop_type=sector.crop_type,
            reference_date=ref_date,
            accumulated_gdd=round(total_gdd, 1),
            tbase_c=tbase,
            current_stage=current_stage,
            suggested_stage=suggested_stage,
            suggested_stage_name_pt=suggested_stage_name_pt,
            suggested_stage_name_en=suggested_stage_name_en,
            suggested_kc=suggested_kc,
            stage_changed=stage_changed,
            days_in_current_stage=days_in_current_stage,
            next_stage=next_stage,
            next_stage_name_pt=next_stage_name_pt,
            gdd_to_next_stage=gdd_to_next_stage,
            confidence=confidence,
            missing_weather_days=missing_days,
            suggestion_pt=suggestion_pt,
            suggestion_en=suggestion_en,
        )

    async def compute_gdd_for_all_sectors(
        self, farm_id: str, db: AsyncSession
    ) -> list[GDDStatus]:
        from app.models import Plot, Sector

        plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
        plots = plots_result.scalars().all()

        results: list[GDDStatus] = []
        for plot in plots:
            sectors_result = await db.execute(select(Sector).where(Sector.plot_id == plot.id))
            sectors = sectors_result.scalars().all()
            for sector in sectors:
                try:
                    status = await self.compute_accumulated_gdd(sector.id, db)
                    if status is not None:
                        results.append(status)
                except Exception:
                    logger.exception("GDD computation failed for sector %s", sector.id)
        return results


def _build_suggestion(
    stage_changed: bool,
    current_stage: str | None,
    suggested_name_pt: str | None,
    suggested_name_en: str | None,
    gdd: float,
    ref_date: date,
) -> tuple[str | None, str | None]:
    if not stage_changed or suggested_name_pt is None:
        return None, None

    ref_str = ref_date.strftime("%-d %b")
    pt = (
        f"Com base em {gdd:.0f} GDD acumulados desde {ref_str}, "
        f"a cultura deverá estar em '{suggested_name_pt}'."
    )
    en = (
        f"Based on {gdd:.0f} GDD accumulated since {ref_str}, "
        f"the crop is likely at '{suggested_name_en}' stage."
    )
    return pt, en
