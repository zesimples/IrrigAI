"""Audit log read endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.common import PaginatedResponse

router = APIRouter(tags=["audit"])


class AuditLogOut(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    user_id: str | None
    before_data: dict | None
    after_data: dict | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/audit-log", response_model=PaginatedResponse[AuditLogOut])
async def list_audit_log(
    entity_type: str | None = Query(None),
    action: str | None = Query(None),
    entity_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog)
    count_q = select(func.count()).select_from(AuditLog)

    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
        count_q = count_q.where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
        count_q = count_q.where(AuditLog.action == action)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
        count_q = count_q.where(AuditLog.entity_id == entity_id)

    total = (await db.execute(count_q)).scalar_one()
    offset = (page - 1) * page_size
    rows = (
        await db.execute(q.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size))
    ).scalars().all()

    return PaginatedResponse(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
