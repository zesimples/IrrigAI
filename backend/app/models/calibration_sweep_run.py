"""One row per farm calibration sweep — queued, running or finished.

The sweep takes minutes on real data (4.9–9.6 min measured on Herdade do
Esporão), so it runs in the worker and the UI polls this row. Blocked sectors
persist nothing of their own, so `outcomes` is the only durable record of what
the sweep saw and why it withheld a change.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import new_uuid


class CalibrationSweepRun(Base):
    """Telemetry + result for one sweep. Mirrors ProviderIngestionRun's shape.

    `status` is one of queued | running | success | partial | failure | stale.
    Everything except queued/running is TERMINAL, which matters: the partial
    unique index below only covers the non-terminal pair, so a dead run drops
    out of it and can never lock a farm out of being swept again.
    """

    __tablename__ = "calibration_sweep_run"
    __table_args__ = (
        # At most one active run per farm. This is what makes the API's 409
        # race-proof across the 4 uvicorn worker processes — a pre-check alone
        # would let two simultaneous clicks both pass.
        Index(
            "uq_calibration_sweep_run_active",
            "farm_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_calibration_sweep_run_farm_queued", "farm_id", "queued_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("farm.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL when a sweep was not triggered by a person.
    triggered_by_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    # The farm's flag as captured at queue time, so the result explains itself
    # even if someone toggles the farm mid-sweep.
    auto_apply: Mapped[bool] = mapped_column(Boolean, nullable=False)

    sectors_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sectors_done: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    no_candidate: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # The SectorSweepOutcome list, written once when the sweep finishes.
    outcomes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bumped on every sector. A non-terminal row with a cold heartbeat (or a
    # cold queued_at, if never picked up) is presumed dead — see
    # calibration_sweep_service.SWEEP_STALE_MINUTES.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<CalibrationSweepRun farm={self.farm_id} {self.status}>"
