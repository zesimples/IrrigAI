from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class FlowmeterReference(Base, TimestampMixin):
    __tablename__ = "flowmeter_reference"
    __table_args__ = (
        UniqueConstraint("flowmeter_id", name="uq_flowmeter_reference_flowmeter"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    flowmeter_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("flowmeter.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reference_rate_m3_ha: Mapped[float] = mapped_column(Float, nullable=False)
    tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0, server_default="5.0")
    upper_limit_m3_ha: Mapped[float] = mapped_column(Float, nullable=False)
    lower_limit_m3_ha: Mapped[float] = mapped_column(Float, nullable=False)
    num_events_analyzed: Mapped[int] = mapped_column(Integer, nullable=False)
    std_dev: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    # "established" = 5+ events, "provisional" = 3-4 events, "insufficient" = < 3
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Timestamp of the most recent event checked for flow-rate alerts.
    # Only events with start_time > last_alert_check_at are re-evaluated.
    last_alert_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    flowmeter: Mapped["Flowmeter"] = relationship("Flowmeter")  # noqa: F821
