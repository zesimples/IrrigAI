"""Persistence helpers for user-scoped AI chat conversations."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatConversation, ChatMessage
from app.schemas.ai import ChatTurn, ProposedAction

# A question and its answer are written in one transaction, and Postgres now() is the
# transaction start, so they share created_at. Within a tie the question comes first;
# without this a reopened transcript, and the history sent to the model, could show
# the answer before the question.
_USER_FIRST = case((ChatMessage.role == "user", 0), else_=1)
MESSAGE_ORDER = (ChatMessage.created_at, _USER_FIRST)
MESSAGE_ORDER_DESC = (ChatMessage.created_at.desc(), _USER_FIRST.desc())


async def resolve_conversation(
    *,
    conversation_id: str | None,
    farm_id: str,
    sector_id: str | None,
    user_id: str,
    first_message: str,
    db: AsyncSession,
) -> ChatConversation:
    if conversation_id:
        conversation = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.farm_id == farm_id,
                    ChatConversation.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise HTTPException(404, detail="Chat conversation not found")
        if sector_id and conversation.sector_id != sector_id:
            raise HTTPException(409, detail="Chat conversation sector scope does not match")
        return conversation

    now = datetime.now(UTC)
    conversation = ChatConversation(
        farm_id=farm_id,
        sector_id=sector_id,
        user_id=user_id,
        title=_conversation_title(first_message),
        last_message_at=now,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def conversation_history(
    conversation_id: str,
    db: AsyncSession,
    *,
    limit: int = 8,
    exclude_message_id: str | None = None,
) -> list[ChatTurn]:
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    # An interrupted turn is not something the model actually said.
                    ChatMessage.status == "complete",
                    ChatMessage.id != exclude_message_id if exclude_message_id else True,
                )
                .order_by(*MESSAGE_ORDER_DESC)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        ChatTurn(role=row.role, content=row.content)  # type: ignore[arg-type]
        for row in reversed(rows)
    ]


async def conversation_evidence(
    conversation_id: str,
    db: AsyncSession,
    *,
    limit: int = 8,
) -> list[dict]:
    """Server-resolved evidence from earlier assistant turns in this conversation.

    A value verified one turn ago does not become invented because the model did
    not re-read it to answer a follow-up.
    """
    rows = (
        (
            await db.execute(
                select(ChatMessage.evidence)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.status == "complete",
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [item for row in rows if isinstance(row, list) for item in row if isinstance(item, dict)]


async def add_chat_message(
    conversation: ChatConversation,
    *,
    role: str,
    content: str,
    proposed_action: ProposedAction | None = None,
    degraded: bool = False,
    model_name: str | None = None,
    db: AsyncSession,
    status: str = "complete",
    evidence: list[dict] | None = None,
    context_version: str | None = None,
    recommendation_id: str | None = None,
    surface: str | None = None,
    client_message_id: str | None = None,
    reply_to_id: str | None = None,
) -> ChatMessage:
    message = ChatMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        proposed_action=proposed_action.model_dump() if proposed_action else None,
        degraded=degraded,
        model_name=model_name,
        status=status,
        evidence=evidence,
        context_version=context_version,
        recommendation_id=recommendation_id,
        surface=surface,
        client_message_id=client_message_id,
        reply_to_id=reply_to_id,
    )
    db.add(message)
    conversation.last_message_at = datetime.now(UTC)
    await db.flush()
    return message


async def find_message_by_client_id(
    conversation_id: str,
    client_message_id: str,
    db: AsyncSession,
) -> ChatMessage | None:
    """Resume a retried send instead of appending a duplicate turn."""
    return (
        await db.execute(
            select(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.client_message_id == client_message_id,
            )
        )
    ).scalar_one_or_none()


async def owned_conversation(
    conversation_id: str,
    *,
    farm_id: str,
    user_id: str,
    db: AsyncSession,
) -> ChatConversation:
    conversation = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.farm_id == farm_id,
                ChatConversation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(404, detail="Chat conversation not found")
    return conversation


def _conversation_title(message: str) -> str:
    clean = " ".join(message.split())
    return clean[:157] + "..." if len(clean) > 160 else clean
