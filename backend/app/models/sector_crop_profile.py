from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class SectorCropProfile(Base, TimestampMixin):
    """The actual crop profile for a specific sector.

    Created by copying a CropProfileTemplate when a sector is set up.
    Users and agronomists can then edit any parameter freely —
    changes here never affect the source template.

    This is what the agronomic engine reads.
    """

    __tablename__ = "sector_crop_profile"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id"), unique=True, nullable=False, index=True
    )
    source_template_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crop_profile_template.id"),
        nullable=True,
        comment="Tracks origin template for reference; null if manually created",
    )

    # Agronomic parameters — fully editable
    crop_type: Mapped[str] = mapped_column(String(50), nullable=False)
    mad: Mapped[float] = mapped_column(Float, nullable=False)
    root_depth_mature_m: Mapped[float] = mapped_column(Float, nullable=False)
    root_depth_young_m: Mapped[float] = mapped_column(Float, nullable=False)
    maturity_age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Per-sector soil overrides — when set, take precedence over the plot's soil values
    field_capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    wilting_point: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_preset_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Stages — copied from template, then freely editable
    stages: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Tracks whether the user has customized this profile from the template
    is_customized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    sector: Mapped["Sector"] = relationship("Sector", back_populates="crop_profile")  # noqa: F821
    source_template: Mapped["CropProfileTemplate | None"] = relationship(  # noqa: F821
        "CropProfileTemplate", back_populates="sector_crop_profiles"
    )

    def __repr__(self) -> str:
        return f"<SectorCropProfile sector={self.sector_id} crop={self.crop_type}>"
