from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class IrrigationEvent(Base, TimestampMixin):
    __tablename__ = "irrigation_event"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("sector.id"), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    applied_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="'manual_log', 'controller', 'recommendation_accepted'"
    )
    recommendation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommendation.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    sector: Mapped["Sector"] = relationship("Sector", back_populates="irrigation_events")  # noqa: F821
    recommendation: Mapped["Recommendation | None"] = relationship(  # noqa: F821
        "Recommendation", back_populates="irrigation_event"
    )

    def __repr__(self) -> str:
        return f"<IrrigationEvent sector={self.sector_id} start={self.start_time}>"
