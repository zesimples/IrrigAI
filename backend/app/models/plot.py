from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Plot(Base, TimestampMixin):
    __tablename__ = "plot"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("farm.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Soil — either from a preset (soil_preset_id tracks provenance) or user-entered custom values
    soil_texture: Mapped[str | None] = mapped_column(String(50), nullable=True)
    field_capacity: Mapped[float | None] = mapped_column(Float, nullable=True, comment="m³/m³")
    wilting_point: Mapped[float | None] = mapped_column(Float, nullable=True, comment="m³/m³")
    stone_content_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_preset_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("soil_preset.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    farm: Mapped["Farm"] = relationship("Farm", back_populates="plots")  # noqa: F821
    soil_preset: Mapped["SoilPreset | None"] = relationship("SoilPreset", back_populates="plots")  # noqa: F821
    sectors: Mapped[list["Sector"]] = relationship(  # noqa: F821
        "Sector", back_populates="plot", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Plot '{self.name}'>"
