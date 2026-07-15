from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class RecommendationOutcome(Base, TimestampMixin):
    """Deterministic comparison of a recommendation with observed execution."""

    __tablename__ = "recommendation_outcome"
    __table_args__ = (
        UniqueConstraint("recommendation_id", name="uq_recommendation_outcome_recommendation"),
        Index("ix_recommendation_outcome_sector_time", "sector_id", "evaluated_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    recommendation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommendation.id", ondelete="CASCADE"), nullable=False
    )
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id", ondelete="CASCADE"), nullable=False
    )
    irrigation_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("irrigation_event.id", ondelete="SET NULL"), nullable=True
    )
    detected_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("irrigation_event_detected.id", ondelete="SET NULL"), nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    recommended_depth_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_applied_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    dose_error_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    dose_error_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pre_irrigation_vwc: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_irrigation_vwc: Mapped[float | None] = mapped_column(Float, nullable=True)
    probe_response_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
