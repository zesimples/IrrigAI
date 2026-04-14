from sqlalchemy import Boolean, Float, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class SoilPreset(Base, TimestampMixin):
    """System-provided soil texture presets.

    Users select a preset when configuring a plot, or enter custom FC/PWP values.
    Selecting a preset copies values into the Plot record (plots track which preset
    was used via soil_preset_id for provenance).
    """

    __tablename__ = "soil_preset"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name_pt: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    texture: Mapped[str] = mapped_column(String(50), nullable=False)
    field_capacity: Mapped[float] = mapped_column(Float, nullable=False, comment="m³/m³")
    wilting_point: Mapped[float] = mapped_column(Float, nullable=False, comment="m³/m³")
    taw_mm_per_m: Mapped[float] = mapped_column(Float, nullable=False, comment="(FC-PWP)*1000 mm/m, for display")
    is_system_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    plots: Mapped[list["Plot"]] = relationship("Plot", back_populates="soil_preset")  # noqa: F821

    def __repr__(self) -> str:
        return f"<SoilPreset {self.texture} FC={self.field_capacity}>"
