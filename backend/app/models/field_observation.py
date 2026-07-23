"""User-authored field observations available to the grounded AI context."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class FieldObservation(Base, TimestampMixin):
    __tablename__ = "field_observation"
    __table_args__ = (Index("ix_field_observation_sector_observed", "sector_id", "observed_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("sector.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    observation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    structured_value: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified_by_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
