"""Sector-level override CRUD endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Sector
from app.models.sector_override import SectorOverride
from app.services.audit_service import OVERRIDE_CREATED, OVERRIDE_REMOVED, audit

router = APIRouter(tags=["overrides"])


class OverrideCreateRequest(BaseModel):
    override_type: str          # "fixed_depth", "fixed_runtime", "skip", "force_irrigate"
    value: float | None = None
    reason: str
    valid_until: date | None = None
    override_strategy: str = "one_time"


class SectorOverrideOut(BaseModel):
    id: str
    sector_id: str
    override_type: str
    value: float | None
    reason: str
    override_strategy: str
    valid_until: date | None
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: SectorOverride) -> "SectorOverrideOut":
        return cls(
            id=obj.id,
            sector_id=obj.sector_id,
            override_type=obj.override_type,
            value=obj.value,
            reason=obj.reason,
            override_strategy=obj.override_strategy,
            valid_until=obj.valid_until,
            is_active=obj.is_active,
            created_at=obj.created_at.isoformat(),
        )


@router.get("/sectors/{sector_id}/overrides", response_model=list[SectorOverrideOut])
async def list_sector_overrides(
    sector_id: str,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    q = select(SectorOverride).where(SectorOverride.sector_id == sector_id)
    if active_only:
        q = q.where(SectorOverride.is_active.is_(True))
    q = q.order_by(SectorOverride.created_at.desc())

    result = await db.execute(q)
    overrides = result.scalars().all()
    return [SectorOverrideOut.from_orm(o) for o in overrides]


@router.post("/sectors/{sector_id}/overrides", response_model=SectorOverrideOut, status_code=201)
async def create_sector_override(
    sector_id: str,
    body: OverrideCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    override = SectorOverride(
        sector_id=sector_id,
        override_type=body.override_type,
        value=body.value,
        reason=body.reason,
        valid_until=body.valid_until,
        override_strategy=body.override_strategy,
        is_active=True,
    )
    db.add(override)
    await db.flush()

    await audit.log(
        OVERRIDE_CREATED, "sector_override", override.id, db,
        after_data={
            "sector_id": sector_id,
            "type": body.override_type,
            "value": body.value,
            "reason": body.reason,
        },
    )
    await db.commit()
    await db.refresh(override)
    return SectorOverrideOut.from_orm(override)


@router.delete("/overrides/{override_id}", status_code=204)
async def remove_sector_override(override_id: str, db: AsyncSession = Depends(get_db)):
    override = await db.get(SectorOverride, override_id)
    if not override:
        raise HTTPException(404, detail="Override not found")

    before = {"is_active": override.is_active}
    override.is_active = False

    await audit.log(
        OVERRIDE_REMOVED, "sector_override", override_id, db,
        before_data=before, after_data={"is_active": False},
    )
    await db.commit()
