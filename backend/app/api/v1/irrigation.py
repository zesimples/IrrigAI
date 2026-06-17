from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Access
from app.database import get_db
from app.models import IrrigationEvent
from app.schemas.common import PaginatedResponse
from app.schemas.irrigation import IrrigationEventCreate, IrrigationEventOut, IrrigationEventUpdate

router = APIRouter(tags=["irrigation"])


@router.get("/sectors/{sector_id}/irrigation-events", response_model=PaginatedResponse[IrrigationEventOut])
async def list_irrigation_events(
    sector_id: str,
    access: Access,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)

    offset = (page - 1) * page_size
    total = (
        await db.execute(
            select(func.count()).select_from(IrrigationEvent).where(
                IrrigationEvent.sector_id == sector_id
            )
        )
    ).scalar_one()
    events = (
        await db.execute(
            select(IrrigationEvent)
            .where(IrrigationEvent.sector_id == sector_id)
            .order_by(IrrigationEvent.start_time.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    return PaginatedResponse(
        items=[IrrigationEventOut.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/sectors/{sector_id}/irrigation-events", response_model=IrrigationEventOut, status_code=201)
async def log_irrigation_event(
    sector_id: str,
    body: IrrigationEventCreate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)
    event = IrrigationEvent(sector_id=sector_id, **body.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return IrrigationEventOut.model_validate(event)


@router.put("/irrigation-events/{event_id}", response_model=IrrigationEventOut)
async def update_irrigation_event(
    event_id: str,
    body: IrrigationEventUpdate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    event = await access.irrigation_event(event_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(event, k, v)
    await db.commit()
    await db.refresh(event)
    return IrrigationEventOut.model_validate(event)


@router.delete("/irrigation-events/{event_id}", status_code=204)
async def delete_irrigation_event(
    event_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    event = await access.irrigation_event(event_id)
    await db.delete(event)
    await db.commit()
