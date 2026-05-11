"""Persistent water-event detections.

Mirrors the in-memory ProbeDetectedEvent shape from the engine but lives in the
DB so the LLM, dashboard and agronomist UI can read prior detections, attach
confirmations / rejections and avoid recomputing on every request.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import new_uuid


class DetectedWaterEvent(Base):
    __tablename__ = "detected_water_event"
    __table_args__ = (
        UniqueConstraint("probe_id", "timestamp", "kind", name="uq_detected_water_event"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    probe_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("probe.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sector_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sector.id", ondelete="CASCADE"), nullable=False, index=True
    )
    farm_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("farm.id", ondelete="CASCADE"), nullable=True, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    probability_irrigation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    probability_rain: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    probability_unlogged: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    depth_sequence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    signal_strength_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sensor_quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    depths_cm: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    delta_vwc: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    irrigation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)

    matched_irrigation_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("irrigation_event.id", ondelete="SET NULL"), nullable=True
    )
    matched_weather_observation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("weather_observation.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    confirmed_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<DetectedWaterEvent probe={self.probe_id} t={self.timestamp} kind={self.kind}>"
