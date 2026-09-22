"""Shared read helper for user-authored field observations.

The chat read tool, the canonical AI context, and the REST list endpoint must all
apply the same expiry rule; a note that has expired is not a current fact and must
not reappear through a second query that forgot the filter.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FieldObservation


async def get_active_field_observations(
    sector_id: str,
    db: AsyncSession,
    *,
    active_only: bool = True,
    limit: int = 20,
) -> list[FieldObservation]:
    stmt = select(FieldObservation).where(FieldObservation.sector_id == sector_id)
    if active_only:
        now = datetime.now(UTC)
        stmt = stmt.where(
            or_(
                FieldObservation.expires_at.is_(None),
                FieldObservation.expires_at > now,
            )
        )
    rows = (
        (await db.execute(stmt.order_by(FieldObservation.observed_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return list(rows)


def serialize_observation(row: FieldObservation) -> dict:
    """Bounded, provenance-carrying shape handed to the model.

    ``verified`` travels with every note precisely so an unconfirmed farmer claim
    can never be read back as a measurement.
    """
    return {
        "id": row.id,
        "type": row.observation_type,
        "text": row.text,
        "structured_value": row.structured_value,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "verified": bool(row.is_verified),
        "source": "user_field_observation",
    }
