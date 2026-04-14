from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class CropProfileTemplate(Base, TimestampMixin):
    """System-provided crop profile defaults.

    When a user creates a sector and picks a crop type, a copy of this template
    is created as their SectorCropProfile. The user/agronomist can then customize
    any parameter without affecting the template.
    """

    __tablename__ = "crop_profile_template"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    crop_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name_pt: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    is_system_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Agronomic parameters — editable on the sector copy
    mad: Mapped[float] = mapped_column(Float, nullable=False, comment="Management allowable depletion 0-1")
    root_depth_mature_m: Mapped[float] = mapped_column(Float, nullable=False)
    root_depth_young_m: Mapped[float] = mapped_column(Float, nullable=False)
    maturity_age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Stages as JSONB — array of stage objects (see project brief for schema)
    stages: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Catch-all for crop-specific config (RDI rules, harvest windows, etc.)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    sector_crop_profiles: Mapped[list["SectorCropProfile"]] = relationship(  # noqa: F821
        "SectorCropProfile", back_populates="source_template"
    )

    def __repr__(self) -> str:
        return f"<CropProfileTemplate {self.crop_type} '{self.name_en}'>"
