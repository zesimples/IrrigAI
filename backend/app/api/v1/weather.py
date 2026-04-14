from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Farm, WeatherForecast, WeatherObservation
from app.schemas.common import MessageResponse
from app.schemas.weather import Et0Point, Et0Response, WeatherForecastOut, WeatherObservationOut

router = APIRouter(tags=["weather"])


@router.get("/farms/{farm_id}/weather/observations", response_model=list[WeatherObservationOut])
async def get_observations(
    farm_id: str,
    limit: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")
    rows = (
        await db.execute(
            select(WeatherObservation)
            .where(WeatherObservation.farm_id == farm_id)
            .order_by(WeatherObservation.timestamp.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [WeatherObservationOut.model_validate(r) for r in rows]


@router.get("/farms/{farm_id}/weather/forecast", response_model=list[WeatherForecastOut])
async def get_forecast(farm_id: str, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")
    rows = (
        await db.execute(
            select(WeatherForecast)
            .where(WeatherForecast.farm_id == farm_id)
            .order_by(WeatherForecast.forecast_date)
        )
    ).scalars().all()
    return [WeatherForecastOut.model_validate(r) for r in rows]


@router.get("/farms/{farm_id}/weather/et0", response_model=Et0Response)
async def get_et0(
    farm_id: str,
    limit: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")
    rows = (
        await db.execute(
            select(WeatherObservation)
            .where(WeatherObservation.farm_id == farm_id)
            .order_by(WeatherObservation.timestamp.desc())
            .limit(limit)
        )
    ).scalars().all()
    points = [
        Et0Point(date=r.timestamp.date(), et0_mm=r.et0_mm)
        for r in reversed(rows)
    ]
    return Et0Response(farm_id=farm_id, points=points)


@router.post("/farms/{farm_id}/weather/trigger-fetch", response_model=MessageResponse)
async def trigger_weather_fetch(farm_id: str, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")
    from app.services.ingestion import ingest_farm
    result = await ingest_farm(farm_id, db)
    return MessageResponse(
        message=f"Weather fetch complete for farm {farm_id}: "
                f"weather_inserted={result.get('weather_inserted', 0)}, "
                f"probes_inserted={result.get('probes_inserted', 0)}"
    )
