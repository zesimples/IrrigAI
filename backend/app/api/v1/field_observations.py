"""CRUD endpoints for field observations used as explicit AI memory."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Access
from app.database import get_db
from app.models import FieldObservation
from app.schemas.field_observation import (
    FieldObservationCreate,
    FieldObservationOut,
    FieldObservationVerify,
)
from app.services.field_observation_service import get_active_field_observations

router = APIRouter(tags=["field-observations"])


@router.get(
    "/sectors/{sector_id}/field-observations",
    response_model=list[FieldObservationOut],
)
async def list_field_observations(
    sector_id: str,
    access: Access,
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)
    rows = await get_active_field_observations(sector_id, db, active_only=active_only, limit=100)
    return [FieldObservationOut.model_validate(row) for row in rows]


@router.post(
    "/sectors/{sector_id}/field-observations",
    response_model=FieldObservationOut,
    status_code=201,
)
async def create_field_observation(
    sector_id: str,
    body: FieldObservationCreate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)
    row = FieldObservation(
        sector_id=sector_id,
        author_id=access.current_user.id,
        **body.model_dump(),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await db.commit()
    return FieldObservationOut.model_validate(row)


@router.patch(
    "/field-observations/{observation_id}/verification",
    response_model=FieldObservationOut,
)
async def verify_field_observation(
    observation_id: str,
    body: FieldObservationVerify,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(FieldObservation, observation_id)
    if row is None:
        raise HTTPException(404, detail="Field observation not found")
    await access.sector(row.sector_id)
    row.is_verified = body.is_verified
    row.verified_by_id = access.current_user.id if body.is_verified else None
    row.verified_at = datetime.now(UTC) if body.is_verified else None
    await db.flush()
    await db.refresh(row)
    await db.commit()
    return FieldObservationOut.model_validate(row)


@router.delete("/field-observations/{observation_id}", status_code=204)
async def delete_field_observation(
    observation_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.get(FieldObservation, observation_id)
    if row is None:
        raise HTTPException(404, detail="Field observation not found")
    await access.sector(row.sector_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
