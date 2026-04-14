from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import new_uuid


class ProbeReading(Base):
    """Time-series probe readings.

    TimescaleDB hypertable on `timestamp` (applied post-migration).
    Composite index on (probe_depth_id, timestamp) for time-range queries.
    No TimestampMixin — timestamp IS the time dimension here.
    """

    __tablename__ = "probe_reading"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    probe_depth_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("probe_depth.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_value: Mapped[float] = mapped_column(Float, nullable=False)
    calibrated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="'vwc_m3m3', 'raw_counts', 'celsius', 'dS_m'"
    )
    quality_flag: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")

    __table_args__ = (
        Index("ix_probe_reading_depth_time", "probe_depth_id", "timestamp"),
    )

    # Relationships
    probe_depth: Mapped["ProbeDepth"] = relationship("ProbeDepth", back_populates="readings")  # noqa: F821

    def __repr__(self) -> str:
        return f"<ProbeReading depth={self.probe_depth_id} t={self.timestamp}>"
