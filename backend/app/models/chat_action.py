"""Durable lifecycle for AI-proposed actions.

A proposed action used to live only inside one assistant message's JSON. Reopening
the conversation re-offered it as if nothing had happened, a second confirmation
executed the write twice, and a failure was indistinguishable from a success. The
row below is the server-side identity of a proposal: it records what was proposed,
whether the user confirmed it, and what actually happened.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid

# pending    — proposed, awaiting the user
# confirmed  — the user confirmed; execution is in flight
# succeeded  — the write completed; `result` carries what changed
# failed     — the write raised; retryable
# cancelled  — the user declined
# invalidated— scope, permission, or recommendation freshness no longer holds
CHAT_ACTION_STATUSES = (
    "pending",
    "confirmed",
    "succeeded",
    "failed",
    "cancelled",
    "invalidated",
)
TERMINAL_CHAT_ACTION_STATUSES = ("succeeded", "cancelled", "invalidated")


class ChatAction(Base, TimestampMixin):
    __tablename__ = "chat_action"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'succeeded', 'failed', 'cancelled', 'invalidated')",
            name="ck_chat_action_status",
        ),
        # One server identity per proposal: a retried confirmation of the same
        # logical action can never become a second write.
        UniqueConstraint("user_id", "idempotency_key", name="uq_chat_action_idempotency"),
        Index("ix_chat_action_conversation", "conversation_id", "created_at"),
        Index("ix_chat_action_message", "chat_message_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_message_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_message.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    recommendation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("recommendation.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
