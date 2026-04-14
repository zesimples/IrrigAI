from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class SectorOverride(Base, TimestampMixin):
    """Sector-level agronomist override — respected by the engine until removed."""

    __tablename__ = "sector_override"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id"), nullable=False, index=True
    )
    override_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="e.g. forced depth mm")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("user.id"), nullable=True
    )
    valid_until: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="None = until manually removed"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    override_strategy: Mapped[str] = mapped_column(
        String(50), nullable=False, default="one_time"
    )

    # Relationships
    sector: Mapped["Sector"] = relationship("Sector", back_populates="overrides")  # noqa: F821
    created_by: Mapped["User | None"] = relationship("User")  # noqa: F821

    def __repr__(self) -> str:
        return f"<SectorOverride {self.override_type} sector={self.sector_id} active={self.is_active}>"
