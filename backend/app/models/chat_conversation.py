"""Server-side chat conversations scoped to one user and farm."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class ChatConversation(Base, TimestampMixin):
    __tablename__ = "chat_conversation"
    __table_args__ = (
        Index(
            "ix_chat_conversation_user_farm_activity",
            "user_id",
            "farm_id",
            "last_message_at",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("farm.id", ondelete="CASCADE"),
        nullable=False,
    )
    sector_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("sector.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
