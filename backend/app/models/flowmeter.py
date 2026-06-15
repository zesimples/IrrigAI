from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Flowmeter(Base, TimestampMixin):
    __tablename__ = "flowmeter"
    __table_args__ = (
        Index("ix_flowmeter_external_device_id", "external_device_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id"), nullable=False, index=True, unique=True
    )
    external_device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sector: Mapped["Sector"] = relationship("Sector", back_populates="flowmeter")  # noqa: F821
    readings: Mapped[list["FlowmeterReading"]] = relationship(  # noqa: F821
        "FlowmeterReading", back_populates="flowmeter", cascade="all, delete-orphan"
    )
    detected_events: Mapped[list["IrrigationEventDetected"]] = relationship(  # noqa: F821
        "IrrigationEventDetected", back_populates="flowmeter", cascade="all, delete-orphan"
    )
