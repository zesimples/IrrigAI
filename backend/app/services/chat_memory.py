"""Persistence helpers for user-scoped AI chat conversations."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatConversation, ChatMessage
from app.schemas.ai import ChatTurn, ProposedAction


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
) -> list[ChatTurn]:
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at.desc())
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


async def add_chat_message(
    conversation: ChatConversation,
    *,
    role: str,
    content: str,
    proposed_action: ProposedAction | None = None,
    degraded: bool = False,
    model_name: str | None = None,
    db: AsyncSession,
) -> ChatMessage:
    message = ChatMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        proposed_action=proposed_action.model_dump() if proposed_action else None,
        degraded=degraded,
        model_name=model_name,
    )
    db.add(message)
    conversation.last_message_at = datetime.now(UTC)
    await db.flush()
    return message


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
