from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class ProbeCalibrationRun(Base, TimestampMixin):
    """Immutable calibration computation; promotion is recorded via status."""

    __tablename__ = "probe_calibration_run"
    __table_args__ = (
        Index("ix_probe_calibration_run_sector_time", "sector_id", "computed_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id", ondelete="CASCADE"), nullable=False
    )
    observed_fc: Mapped[float] = mapped_column(Float, nullable=False)
    observed_refill: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    num_cycles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consistency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # manual | scheduled
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # candidate | applied | superseded
    previous_fc: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_refill: Mapped[float | None] = mapped_column(Float, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
