from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AlertSeverity, AlertType
from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Alert(Base, TimestampMixin):
    __tablename__ = "alert"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    sector_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("sector.id"), nullable=True, index=True)
    farm_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("farm.id"), nullable=False, index=True)

    alert_type: Mapped[AlertType] = mapped_column(String(50), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(String(20), nullable=False)

    title_pt: Mapped[str] = mapped_column(String(500), nullable=False)
    title_en: Mapped[str] = mapped_column(String(500), nullable=False)
    description_pt: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("user.id"), nullable=True)

    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    sector: Mapped["Sector | None"] = relationship("Sector", back_populates="alerts")  # noqa: F821
    farm: Mapped["Farm"] = relationship("Farm", back_populates="alerts")  # noqa: F821
    acknowledged_by: Mapped["User | None"] = relationship("User", back_populates="acknowledged_alerts")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Alert {self.alert_type} [{self.severity}] active={self.is_active}>"
