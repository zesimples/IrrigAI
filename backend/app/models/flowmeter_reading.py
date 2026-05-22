from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import new_uuid


class FlowmeterReading(Base):
    __tablename__ = "flowmeter_reading"
    __table_args__ = (
        UniqueConstraint("flowmeter_id", "timestamp", name="uq_flowmeter_reading_device_ts"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    flowmeter_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("flowmeter.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value_m3_ha: Mapped[float] = mapped_column(Float, nullable=False)

    flowmeter: Mapped["Flowmeter"] = relationship("Flowmeter", back_populates="readings")  # noqa: F821
