from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class IrrigationEventDetected(Base, TimestampMixin):
    __tablename__ = "irrigation_event_detected"
    __table_args__ = (
        UniqueConstraint(
            "flowmeter_id", "start_time", name="uq_irrigation_event_detected_device_start"
        ),
        Index("ix_irrigation_event_detected_fm_start", "flowmeter_id", "start_time"),
        Index("ix_irrigation_event_detected_sector_start", "sector_id", "start_time"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    flowmeter_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("flowmeter.id"), nullable=False
    )
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    total_m3_ha: Mapped[float] = mapped_column(Float, nullable=False)
    peak_m3_ha: Mapped[float] = mapped_column(Float, nullable=False)
    num_readings: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    flowmeter: Mapped["Flowmeter"] = relationship("Flowmeter", back_populates="detected_events")  # noqa: F821
    sector: Mapped["Sector"] = relationship("Sector")  # noqa: F821
