"""Persisted user and assistant turns for a chat conversation."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_message"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_chat_message_role",
        ),
        CheckConstraint(
            "status IN ('complete', 'interrupted', 'failed')",
            name="ck_chat_message_status",
        ),
        Index("ix_chat_message_conversation_created", "conversation_id", "created_at"),
        # A retried send must resume the same turn rather than append a second one.
        Index(
            "uq_chat_message_client_id",
            "conversation_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # An interrupted answer is not a completed one: reopening a conversation must
    # show what actually happened rather than a truncated reply presented as final.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="complete", server_default="complete"
    )
    # Server-resolved citations for this turn, plus the provenance a later turn
    # needs to tell a current answer from a historical one.
    evidence: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    context_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("recommendation.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Which AI surface produced the turn ("chat", "farm_summary", ...), so quick
    # actions live in the same conversation lifecycle as chat replies.
    surface: Mapped[str | None] = mapped_column(String(40), nullable=True)
    client_message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reply_to_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_message.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    response_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
