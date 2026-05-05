from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import new_uuid


class ProviderSyncLog(Base):
    """One row per (farm, provider) — upserted after every ingestion run.

    provider values: "<adapter>:probes" or "<adapter>:weather"
    e.g. "myirrigation:probes", "myirrigation:weather"
    """

    __tablename__ = "provider_sync_log"
    __table_args__ = (UniqueConstraint("farm_id", "provider", name="uq_provider_sync_log_farm_provider"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("farm.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)

    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
