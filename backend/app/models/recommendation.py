from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ConfidenceLevel, RecommendationAction
from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Recommendation(Base, TimestampMixin):
    __tablename__ = "recommendation"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("sector.id"), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)

    action: Mapped[RecommendationAction] = mapped_column(String(50), nullable=False)
    irrigation_depth_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    irrigation_runtime_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_start_time: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="HH:MM")

    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(String(20), nullable=False)

    is_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accepted_by_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("user.id"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    engine_version: Mapped[str] = mapped_column(String(50), nullable=False, default="0.1.0")
    inputs_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computation_log: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Relationships
    sector: Mapped["Sector"] = relationship("Sector", back_populates="recommendations")  # noqa: F821
    accepted_by: Mapped["User | None"] = relationship("User", back_populates="accepted_recommendations")  # noqa: F821
    reasons: Mapped[list["RecommendationReason"]] = relationship(  # noqa: F821
        "RecommendationReason", back_populates="recommendation", cascade="all, delete-orphan",
        order_by="RecommendationReason.order"
    )
    irrigation_event: Mapped["IrrigationEvent | None"] = relationship(  # noqa: F821
        "IrrigationEvent", back_populates="recommendation", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Recommendation sector={self.sector_id} action={self.action} conf={self.confidence_score:.2f}>"
