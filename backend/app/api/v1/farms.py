from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Farm, Plot, Sector
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.farm import FarmCreate, FarmDetail, FarmOut, FarmUpdate

router = APIRouter(prefix="/farms", tags=["farms"])

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=PaginatedResponse[FarmOut])
async def list_farms(
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    base = select(Farm).where(Farm.owner_id == current_user.id, Farm.is_archived == False)  # noqa: E712
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    farms = (await db.execute(base.offset(offset).limit(page_size))).scalars().all()
    return PaginatedResponse(
        items=[FarmOut.model_validate(f) for f in farms],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{farm_id}", response_model=FarmDetail)
async def get_farm(farm_id: str, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or farm.owner_id != current_user.id:
        raise HTTPException(404, detail="Farm not found")

    plots = (await db.execute(select(Plot).where(Plot.farm_id == farm_id))).scalars().all()
    plot_ids = [p.id for p in plots]

    sector_count = 0
    if plot_ids:
        sector_count = (
            await db.execute(
                select(func.count()).select_from(Sector).where(Sector.plot_id.in_(plot_ids))
            )
        ).scalar_one()

    return FarmDetail(
        **FarmOut.model_validate(farm).model_dump(),
        plot_count=len(plots),
        sector_count=sector_count,
    )


@router.post("", response_model=FarmOut, status_code=201)
async def create_farm(body: FarmCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    data["owner_id"] = current_user.id
    farm = Farm(**data)
    db.add(farm)
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)


@router.put("/{farm_id}", response_model=FarmOut)
async def update_farm(farm_id: str, body: FarmUpdate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or farm.owner_id != current_user.id:
        raise HTTPException(404, detail="Farm not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(farm, k, v)
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)


@router.post("/{farm_id}/archive", response_model=FarmOut)
async def archive_farm(farm_id: str, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or farm.owner_id != current_user.id:
        raise HTTPException(404, detail="Farm not found")
    farm.is_archived = True
    farm.archived_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)


@router.post("/{farm_id}/unarchive", response_model=FarmOut)
async def unarchive_farm(farm_id: str, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or farm.owner_id != current_user.id:
        raise HTTPException(404, detail="Farm not found")
    farm.is_archived = False
    farm.archived_at = None
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)
