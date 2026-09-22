"""Durable lifecycle for AI-proposed actions: propose → confirm → result.

The AI never writes. It proposes, and a proposal is a row (``ChatAction``) with a
server-side identity, so:

* confirming twice cannot execute the write twice — the status transition is the
  idempotency guard, not a client-supplied token that a retry may lose;
* permission, scope, and recommendation freshness are re-checked **at confirmation
  time**, because the proposal was made against a world that may have moved;
* a failure stays a failure. Reopening a conversation shows what actually happened
  instead of re-offering a completed action as if it were pending.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AccessController
from app.models import ChatAction, ChatConversation, Recommendation
from app.schemas.ai import ProposedAction
from app.services.chat_memory import add_chat_message

logger = logging.getLogger(__name__)

# Proposals that pin a specific recommendation must be revalidated against the
# sector's current one; the other two act on the sector as it stands.
_RECOMMENDATION_SCOPED = {
    "accept_recommendation",
    "reject_recommendation",
    "override_recommendation",
}

_RESULT_MESSAGE_PT = {
    "accept_recommendation": "Feito — recomendação aceite.",
    "reject_recommendation": "Feito — recomendação rejeitada.",
    "override_recommendation": "Feito — recomendação substituída.",
    "regenerate_recommendation": "Feito — nova recomendação gerada.",
    "run_calibration": "Feito — calibração inteligente concluída.",
}


class ActionConflict(Exception):
    """The action cannot run in its current state; the caller reports it as 409."""

    def __init__(self, action: ChatAction, detail: str) -> None:
        super().__init__(detail)
        self.action = action
        self.detail = detail


async def record_proposal(
    *,
    conversation: ChatConversation,
    chat_message_id: str,
    user_id: str,
    proposed: ProposedAction,
    idempotency_key: str,
    db: AsyncSession,
) -> ChatAction:
    """Persist a proposal so its outcome survives the conversation being reopened."""
    existing = (
        await db.execute(
            select(ChatAction).where(
                ChatAction.user_id == user_id,
                ChatAction.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    action = ChatAction(
        conversation_id=conversation.id,
        chat_message_id=chat_message_id,
        user_id=user_id,
        farm_id=conversation.farm_id,
        sector_id=proposed.sector_id or conversation.sector_id,
        recommendation_id=proposed.recommendation_id,
        action_type=proposed.type,
        summary=proposed.summary,
        params=proposed.params or {},
        status="pending",
        idempotency_key=idempotency_key,
    )
    db.add(action)
    await db.flush()
    return action


async def get_owned_action(
    action_id: str,
    *,
    farm_id: str,
    user_id: str,
    db: AsyncSession,
) -> ChatAction:
    action = (
        await db.execute(
            select(ChatAction).where(
                ChatAction.id == action_id,
                ChatAction.farm_id == farm_id,
                ChatAction.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if action is None:
        # Missing and cross-tenant are the same answer: no existence leak.
        raise HTTPException(404, detail="Proposed action not found")
    return action


async def actions_for_conversation(conversation_id: str, db: AsyncSession) -> dict[str, ChatAction]:
    """Map ``chat_message_id`` → action so a reopened transcript shows real status."""
    rows = (
        (await db.execute(select(ChatAction).where(ChatAction.conversation_id == conversation_id)))
        .scalars()
        .all()
    )
    return {row.chat_message_id: row for row in rows if row.chat_message_id}


async def cancel_action(action: ChatAction, db: AsyncSession) -> ChatAction:
    await db.execute(
        update(ChatAction)
        .where(ChatAction.id == action.id, ChatAction.status.in_(("pending", "failed")))
        .values(status="cancelled", completed_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await db.refresh(action)
    if action.status != "cancelled":
        raise ActionConflict(action, "Esta acção já está a ser executada ou terminou.")
    return action


async def confirm_action(
    action: ChatAction,
    *,
    access: AccessController,
    db: AsyncSession,
) -> ChatAction:
    """Revalidate, execute once, and persist the real outcome."""
    if action.status == "succeeded":
        # Idempotent replay: a lost response must not become a second write.
        return action
    if action.status in ("cancelled", "invalidated"):
        raise ActionConflict(
            action,
            "Esta proposta já não está válida. Pede uma nova ao assistente.",
        )
    if action.status == "confirmed":
        raise ActionConflict(action, "Esta acção já está a ser executada.")

    # Read the identity BEFORE any rollback: a rolled-back session expires every
    # loaded attribute, and touching one afterwards attempts sync IO (MissingGreenlet).
    action_id = action.id
    action_type = action.action_type

    # Claim the action atomically: two concurrent confirmations race here, and only
    # the one that moves pending/failed → confirmed proceeds to the write.
    claimed = await db.execute(
        update(ChatAction)
        .where(ChatAction.id == action.id, ChatAction.status.in_(("pending", "failed")))
        .values(status="confirmed", confirmed_at=datetime.now(UTC))
        .returning(ChatAction.id)
    )
    if claimed.scalar_one_or_none() is None:
        await db.refresh(action)
        if action.status == "succeeded":
            return action
        raise ActionConflict(action, "Esta acção já está a ser executada.")
    await db.refresh(action)

    try:
        await _revalidate(action, access=access, db=db)
        result = await _execute(action, access=access, db=db)
        action.status = "succeeded"
        action.result = result
        action.completed_at = datetime.now(UTC)
        action.error_detail = None
        await _record_result_event(action, db)
        await db.flush()
    except ActionConflict:
        raise
    except Exception as exc:  # noqa: BLE001 - the failure is the product here
        logger.exception(
            "Chat action execution failed",
            extra={"action_type": action_type, "error_type": type(exc).__name__},
        )
        await db.rollback()
        # A rolled-back session lost the in-memory action; re-read and mark it
        # failed on a clean transaction so the record survives the failure.
        failed = await db.get(ChatAction, action_id)
        if failed is not None:
            detail = (
                str(exc.detail)
                if isinstance(exc, HTTPException)
                else "Não foi possível executar a acção. Tenta novamente."
            )[:2000]
            await db.execute(
                update(ChatAction)
                .where(ChatAction.id == action_id, ChatAction.status.in_(("pending", "failed")))
                .values(status="failed", error_detail=detail, completed_at=datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            await db.refresh(failed)
            return failed
        raise

    return action


async def _revalidate(action: ChatAction, *, access: AccessController, db: AsyncSession) -> None:
    """Permissions, scope, and recommendation freshness, as they are right now."""
    await access.farm(action.farm_id)
    if action.sector_id:
        await access.sector_in_farm(action.sector_id, action.farm_id)
    if action.recommendation_id and action.action_type in _RECOMMENDATION_SCOPED:
        recommendation = await access.recommendation(action.recommendation_id)
        await access.sector_in_farm(recommendation.sector_id, action.farm_id)
        if action.sector_id and recommendation.sector_id != action.sector_id:
            raise HTTPException(404, detail="Recommendation not found")
        latest_id = (
            await db.execute(
                select(Recommendation.id)
                .where(Recommendation.sector_id == recommendation.sector_id)
                .order_by(Recommendation.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_id and latest_id != action.recommendation_id:
            action.status = "invalidated"
            action.error_detail = "recommendation_superseded"
            action.completed_at = datetime.now(UTC)
            await db.flush()
            await db.commit()
            raise ActionConflict(
                action,
                (
                    "Entretanto foi gerada uma recomendação mais recente para este "
                    "setor. Pede uma nova proposta ao assistente."
                ),
            )


async def _execute(action: ChatAction, *, access: AccessController, db: AsyncSession) -> dict:
    from app.services.audit_service import (
        RECOMMENDATION_ACCEPTED,
        RECOMMENDATION_OVERRIDDEN,
        RECOMMENDATION_REJECTED,
        audit,
    )

    params = action.params or {}
    if action.action_type == "accept_recommendation":
        rec = await access.recommendation(action.recommendation_id)
        before = {"is_accepted": rec.is_accepted}
        rec.is_accepted = True
        rec.accepted_at = datetime.now(UTC)
        await audit.log(
            RECOMMENDATION_ACCEPTED,
            "recommendation",
            rec.id,
            db,
            before_data=before,
            after_data={"is_accepted": True, "source": "ai_chat_action"},
        )
        return {"recommendation_id": rec.id, "is_accepted": True}

    if action.action_type == "reject_recommendation":
        rec = await access.recommendation(action.recommendation_id)
        before = {"is_accepted": rec.is_accepted}
        notes = params.get("notes")
        rec.is_accepted = False
        if notes:
            rec.override_notes = str(notes)[:2000]
        await audit.log(
            RECOMMENDATION_REJECTED,
            "recommendation",
            rec.id,
            db,
            before_data=before,
            after_data={"is_accepted": False, "source": "ai_chat_action"},
        )
        return {"recommendation_id": rec.id, "is_accepted": False}

    if action.action_type == "override_recommendation":
        rec = await access.recommendation(action.recommendation_id)
        before = {
            "irrigation_depth_mm": rec.irrigation_depth_mm,
            "override_notes": rec.override_notes,
        }
        depth = params.get("custom_depth_mm")
        if depth is not None:
            rec.irrigation_depth_mm = float(depth)
        rec.override_notes = str(params.get("override_reason") or "Ajuste via assistente")[:2000]
        rec.is_accepted = True
        rec.accepted_at = datetime.now(UTC)
        await audit.log(
            RECOMMENDATION_OVERRIDDEN,
            "recommendation",
            rec.id,
            db,
            before_data=before,
            after_data={
                "irrigation_depth_mm": rec.irrigation_depth_mm,
                "override_notes": rec.override_notes,
                "source": "ai_chat_action",
            },
        )
        return {
            "recommendation_id": rec.id,
            "irrigation_depth_mm": rec.irrigation_depth_mm,
        }

    if action.action_type == "regenerate_recommendation":
        from app.services.recommendation_service import generate_recommendation

        rec, _ = await generate_recommendation(action.sector_id, db, commit=False)
        return {
            "recommendation_id": rec.id,
            "action": rec.action.value if hasattr(rec.action, "value") else str(rec.action),
        }

    if action.action_type == "run_calibration":
        from app.services.probe_calibration_service import ProbeCalibrationService

        service = ProbeCalibrationService()
        payload = await service.run_manual(action.sector_id, db, user_id=action.user_id)
        return {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in payload.items()
        }

    raise ValueError(f"unsupported_action_type:{action.action_type}")


async def _record_result_event(action: ChatAction, db: AsyncSession) -> None:
    """Persist the outcome as a conversation turn the next question can see."""
    conversation = await db.get(ChatConversation, action.conversation_id)
    if conversation is None:  # pragma: no cover - FK guarantees it
        return
    await add_chat_message(
        conversation,
        role="assistant",
        content=_RESULT_MESSAGE_PT.get(action.action_type, "Acção concluída."),
        db=db,
        surface="action_result",
    )
