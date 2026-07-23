"""Thumbs feedback for chat messages and other AI response surfaces."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class AIResponseFeedback(Base, TimestampMixin):
    __tablename__ = "ai_response_feedback"
    __table_args__ = (
        CheckConstraint("rating IN (-1, 1)", name="ck_ai_response_feedback_rating"),
        Index("ix_ai_response_feedback_surface_created", "surface", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    farm_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("farm.id", ondelete="CASCADE"),
        nullable=True,
    )
    chat_message_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_message.id", ondelete="CASCADE"),
        nullable=True,
    )
    surface: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
