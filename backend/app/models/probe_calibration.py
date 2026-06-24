from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class ProbeCalibration(Base, TimestampMixin):
    """Per-sector soil reference points calibrated from the probe's own VWC envelope.

    Replaces generic soil-texture preset FC/PWP for sectors whose VWC sensors read on
    an absolute scale far above the preset values (the "always 100%" pinning bug).
    """

    __tablename__ = "probe_calibration"
    __table_args__ = (
        UniqueConstraint("sector_id", name="uq_probe_calibration_sector"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    observed_fc: Mapped[float] = mapped_column(Float, nullable=False)        # m³/m³, drained upper limit
    observed_refill: Mapped[float] = mapped_column(Float, nullable=False)    # m³/m³, refill / lower bound
    method: Mapped[str] = mapped_column(String(20), nullable=False)          # "cycles" | "envelope"
    num_cycles: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consistency: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sector: Mapped["Sector"] = relationship("Sector")  # noqa: F821
