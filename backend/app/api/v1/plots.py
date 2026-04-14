from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Farm, Plot, Sector
from app.schemas.common import PaginatedResponse
from app.schemas.plot import PlotCreate, PlotDetail, PlotOut, PlotUpdate

router = APIRouter(tags=["plots"])


@router.get("/farms/{farm_id}/plots", response_model=PaginatedResponse[PlotOut])
async def list_plots(
    farm_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")

    offset = (page - 1) * page_size
    total = (
        await db.execute(
            select(func.count()).select_from(Plot).where(Plot.farm_id == farm_id)
        )
    ).scalar_one()
    plots = (
        await db.execute(select(Plot).where(Plot.farm_id == farm_id).offset(offset).limit(page_size))
    ).scalars().all()
    return PaginatedResponse(
        items=[PlotOut.model_validate(p) for p in plots],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/plots/{plot_id}", response_model=PlotDetail)
async def get_plot(plot_id: str, db: AsyncSession = Depends(get_db)):
    plot = await db.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, detail="Plot not found")
    sector_count = (
        await db.execute(
            select(func.count()).select_from(Sector).where(Sector.plot_id == plot_id)
        )
    ).scalar_one()
    return PlotDetail(**PlotOut.model_validate(plot).model_dump(), sector_count=sector_count)


@router.post("/farms/{farm_id}/plots", response_model=PlotOut, status_code=201)
async def create_plot(farm_id: str, body: PlotCreate, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")
    plot = Plot(farm_id=farm_id, **body.model_dump())
    db.add(plot)
    await db.commit()
    await db.refresh(plot)
    return PlotOut.model_validate(plot)


@router.put("/plots/{plot_id}", response_model=PlotOut)
async def update_plot(plot_id: str, body: PlotUpdate, db: AsyncSession = Depends(get_db)):
    plot = await db.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, detail="Plot not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(plot, k, v)
    await db.commit()
    await db.refresh(plot)
    return PlotOut.model_validate(plot)
