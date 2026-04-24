from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Sector(Base, TimestampMixin):
    __tablename__ = "sector"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    plot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("plot.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Crop identification (string, not enum — extensible)
    crop_type: Mapped[str] = mapped_column(String(50), nullable=False)
    variety: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planting_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sowing_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="For annuals like maize")

    # Physical parameters
    tree_spacing_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    row_spacing_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    trees_per_ha: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Auto-calibration state
    auto_calibration_dismissed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="If set, auto-calibration suggestions are suppressed until this datetime"
    )

    # Agronomic management
    current_phenological_stage: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="References a stage key from the sector's SectorCropProfile.stages",
    )
    irrigation_strategy: Mapped[str] = mapped_column(String(50), nullable=False, default="full_etc")
    deficit_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    rainfall_effectiveness: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    plot: Mapped["Plot"] = relationship("Plot", back_populates="sectors")  # noqa: F821
    crop_profile: Mapped["SectorCropProfile | None"] = relationship(  # noqa: F821
        "SectorCropProfile", back_populates="sector", uselist=False, cascade="all, delete-orphan"
    )
    irrigation_system: Mapped["IrrigationSystem | None"] = relationship(  # noqa: F821
        "IrrigationSystem", back_populates="sector", uselist=False, cascade="all, delete-orphan"
    )
    probes: Mapped[list["Probe"]] = relationship(  # noqa: F821
        "Probe", back_populates="sector", cascade="all, delete-orphan"
    )
    irrigation_events: Mapped[list["IrrigationEvent"]] = relationship(  # noqa: F821
        "IrrigationEvent", back_populates="sector", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(  # noqa: F821
        "Recommendation", back_populates="sector", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="sector")  # noqa: F821
    overrides: Mapped[list["SectorOverride"]] = relationship(  # noqa: F821
        "SectorOverride", back_populates="sector", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Sector '{self.name}' [{self.crop_type}]>"
