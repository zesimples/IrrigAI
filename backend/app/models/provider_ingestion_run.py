"""Per-run ingestion telemetry.

One row per call to ingest_probe_readings()/ingest_weather_observations().  Stored
in addition to ProviderSyncLog (which keeps a single rolling row per
farm+provider) so we get a full audit trail of every provider request including
which rows were skipped and why.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import new_uuid


class ProviderIngestionRun(Base):
    """A single ingestion run against an external data provider.

    Captures requested window, raw provider response stats, deduplication
    outcomes and quality-flag counts so operators can diagnose missing data
    without re-running the ingestion.
    """

    __tablename__ = "provider_ingestion_run"
    __table_args__ = (
        Index("ix_provider_ingestion_run_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("farm.id", ondelete="CASCADE"), nullable=False, index=True
    )
    probe_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("probe.id", ondelete="SET NULL"), nullable=True, index=True
    )
    probe_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    requested_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_first_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    provider_records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    provider_records_parsed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_null: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_sentinel: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_unknown_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    flagged_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    flagged_suspect: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata_json", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ProviderIngestionRun {self.provider}:{self.source_type} "
            f"farm={self.farm_id} status={self.status} inserted={self.inserted}>"
        )
