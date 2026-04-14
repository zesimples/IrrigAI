from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class RecommendationReason(Base, TimestampMixin):
    __tablename__ = "recommendation_reason"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    recommendation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommendation.id"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    message_pt: Mapped[str] = mapped_column(Text, nullable=False)
    message_en: Mapped[str] = mapped_column(Text, nullable=False)
    data_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_value: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    recommendation: Mapped["Recommendation"] = relationship(  # noqa: F821
        "Recommendation", back_populates="reasons"
    )

    def __repr__(self) -> str:
        return f"<RecommendationReason [{self.category}] #{self.order}>"
