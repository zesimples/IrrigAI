from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class IrrigationFingerprint(Base, TimestampMixin):
    """Per-sector habitual irrigation dose learned from probe-detected events.

    Powers the "probe_learned" tier of the dose-do-dia presentation for
    sectors without a configured irrigation system. Deterministic — computed
    by engine/irrigation_fingerprint.py, refreshed weekly by the scheduler.
    """

    __tablename__ = "irrigation_fingerprint"
    __table_args__ = (
        UniqueConstraint("sector_id", name="uq_irrigation_fingerprint_sector"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    typical_event_net_mm: Mapped[float] = mapped_column(Float, nullable=False)
    typical_event_duration_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_events: Mapped[int] = mapped_column(Integer, nullable=False)
    consistency: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)   # "medium" | "high"
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sector: Mapped["Sector"] = relationship("Sector")  # noqa: F821
