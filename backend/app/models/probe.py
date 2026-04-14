from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ProbeHealthStatus
from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Probe(Base, TimestampMixin):
    __tablename__ = "probe"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("sector.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, comment="Provider's probe identifier")
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    health_status: Mapped[ProbeHealthStatus] = mapped_column(
        String(20), nullable=False, default=ProbeHealthStatus.OK
    )
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    sector: Mapped["Sector"] = relationship("Sector", back_populates="probes")  # noqa: F821
    depths: Mapped[list["ProbeDepth"]] = relationship(  # noqa: F821
        "ProbeDepth", back_populates="probe", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Probe {self.external_id} sector={self.sector_id}>"
