from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import IrrigationSystemType
from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class IrrigationSystem(Base, TimestampMixin):
    __tablename__ = "irrigation_system"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id"), unique=True, nullable=False, index=True
    )
    system_type: Mapped[IrrigationSystemType] = mapped_column(String(50), nullable=False)
    emitter_flow_lph: Mapped[float | None] = mapped_column(Float, nullable=True, comment="L/h per emitter")
    emitter_spacing_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines_per_row: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    application_rate_mm_h: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Computed or overridden by user"
    )
    efficiency: Mapped[float] = mapped_column(Float, nullable=False, default=0.90)
    distribution_uniformity: Mapped[float] = mapped_column(Float, nullable=False, default=0.90, comment="Fraction 0–1; how evenly water is distributed across the field")
    max_runtime_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_irrigation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_irrigation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    sector: Mapped["Sector"] = relationship("Sector", back_populates="irrigation_system")  # noqa: F821

    def __repr__(self) -> str:
        return f"<IrrigationSystem {self.system_type} sector={self.sector_id}>"
