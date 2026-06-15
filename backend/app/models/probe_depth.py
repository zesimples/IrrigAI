from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class ProbeDepth(Base, TimestampMixin):
    __tablename__ = "probe_depth"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    probe_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("probe.id"), nullable=False, index=True)
    depth_cm: Mapped[int] = mapped_column(Integer, nullable=False)
    sensor_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    calibration_offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calibration_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Per-depth freshness / sync state — populated by the ingestion service
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_quality_flag: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    readings_count_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_gap_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown",
    )

    # Relationships
    probe: Mapped["Probe"] = relationship("Probe", back_populates="depths")  # noqa: F821
    readings: Mapped[list["ProbeReading"]] = relationship(  # noqa: F821
        "ProbeReading", back_populates="probe_depth", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ProbeDepth {self.depth_cm}cm [{self.sensor_type}]>"
