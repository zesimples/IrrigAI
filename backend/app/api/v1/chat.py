"""Chat and explanation endpoints for the AI assistant layer."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, StreamingResponse

from app.access import Access
from app.ai.assistant import IrrigationAssistant
from app.ai.chat_agent import ChatAgent, ChatResult
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import get_chat_client
from app.config import get_settings
from app.database import get_db
from app.limiter import limiter
from app.metrics import (
    ai_chat_stage_seconds,
    ai_chat_turns_total,
    ai_degraded_responses_total,
    ai_response_feedback_total,
)
from app.models import AIResponseFeedback, ChatConversation, ChatMessage
from app.schemas.ai import AgronomicInterpretation
from app.schemas.chat import (
    AIResponseFeedbackCreate,
    AIResponseFeedbackOut,
    AnalysisProvenance,
    ChatActionOut,
    ChatConversationDetail,
    ChatConversationOut,
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ProposedActionOut,
    QuickActionRequest,
)
from app.services.ai_provenance import sector_analysis_provenance
from app.services.ai_runtime import (
    CONTRACT_VERSION,
    consume_daily_ai_quota,
    context_digest,
    get_cached_interpretation,
    set_cached_interpretation,
)
from app.services.chat_actions import (
    ActionConflict,
    actions_for_conversation,
    cancel_action,
    confirm_action,
    get_owned_action,
    record_proposal,
)
from app.services.chat_memory import (
    add_chat_message,
    conversation_evidence,
    conversation_history,
    find_message_by_client_id,
    owned_conversation,
    resolve_conversation,
)

# A turn that has not produced a validated answer within this budget is reported as
# interrupted rather than held open behind a proxy that will drop it anyway.
CHAT_TURN_TIMEOUT_SECONDS = 120.0

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency — instantiate assistant per request (lightweight, no state)
# ---------------------------------------------------------------------------


def get_assistant() -> IrrigationAssistant:
    settings = get_settings()
    client = get_chat_client(settings)
    builder = AssistantContextBuilder()
    return IrrigationAssistant(
        context_builder=builder,
        client=client,
        language=settings.DEFAULT_LANGUAGE,
    )


def get_chat_agent() -> ChatAgent:
    settings = get_settings()
    client = get_chat_client(settings)
    builder = AssistantContextBuilder()
    return ChatAgent(client=client, context_builder=builder, language=settings.DEFAULT_LANGUAGE)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    user_notes: str | None = Field(default=None, max_length=4000)


class ExplainResponse(BaseModel):
    explanation: str
    structured: AgronomicInterpretation | None = None
    provenance: AnalysisProvenance | None = None


class SummaryResponse(BaseModel):
    summary: str
    structured: AgronomicInterpretation | None = None
    provenance: AnalysisProvenance | None = None


class QuestionsResponse(BaseModel):
    questions: list[str]


class DiagnosisResponse(BaseModel):
    diagnosis: str
    structured: AgronomicInterpretation | None = None
    provenance: AnalysisProvenance | None = None


class InterpretationResponse(BaseModel):
    interpretation: str
    structured: AgronomicInterpretation | None = None
    provenance: AnalysisProvenance | None = None


class ChangeAnalysisRequest(BaseModel):
    window_hours: int = Field(default=72, ge=1, le=720)


class ChangeAnalysisResponse(BaseModel):
    analysis: str
    structured: AgronomicInterpretation
    provenance: AnalysisProvenance | None = None


class EffectivenessAnalysisResponse(BaseModel):
    analysis: str
    structured: AgronomicInterpretation
    provenance: AnalysisProvenance | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/farms/{farm_id}/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def farm_chat(
    request: Request,
    farm_id: str,
    body: ChatRequest,
    access: Access,
    db: AsyncSession = Depends(get_db),
    agent: ChatAgent = Depends(get_chat_agent),
):
    """Conversational chat with memory + tools about the farm or a specific sector."""
    await consume_daily_ai_quota(access.current_user.id)
    try:
        return await _run_persisted_chat(
            farm_id=farm_id,
            body=body,
            access=access,
            db=db,
            agent=agent,
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Erro ao processar o pedido de chat.") from exc


@router.post("/farms/{farm_id}/chat/stream")
@limiter.limit("30/minute")
async def stream_farm_chat(
    request: Request,
    farm_id: str,
    body: ChatRequest,
    access: Access,
    db: AsyncSession = Depends(get_db),
    agent: ChatAgent = Depends(get_chat_agent),
) -> StreamingResponse:
    """SSE transport driven by the agent's own events.

    Progress reaches the client while the work is happening; answer content only
    after the grounding checks pass. Nothing here streams raw model tokens — that
    would put unchecked agronomic claims on screen to buy perceived speed.
    """
    await consume_daily_ai_quota(access.current_user.id)
    await access.farm(farm_id)
    if body.sector_id:
        await access.sector_in_farm(body.sector_id, farm_id)

    async def events() -> AsyncIterator[str]:
        started = time.monotonic()
        first_progress_seen = False
        first_answer_seen = False
        conversation = None
        assistant_message = None
        result: ChatResult | None = None
        try:
            conversation, resumed = await _open_turn(
                farm_id=farm_id, body=body, access=access, db=db
            )
            if resumed.status == "complete":
                # A retry of a turn the server already completed: replay it rather
                # than run a second one.
                yield _sse(
                    "conversation",
                    {"conversation_id": conversation.id, "message_id": resumed.id},
                )
                yield _sse("delta", {"text": resumed.content})
                actions = await actions_for_conversation(conversation.id, db)
                yield _sse("done", _done_payload_from_message(resumed, actions.get(resumed.id)))
                return

            assistant_message = resumed
            assistant_message_id = resumed.id
            history = await conversation_history(
                conversation.id, db, exclude_message_id=resumed.reply_to_id
            )
            prior_evidence = await conversation_evidence(conversation.id, db)
            yield _sse(
                "conversation",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                },
            )

            async with asyncio.timeout(CHAT_TURN_TIMEOUT_SECONDS):
                async for event in agent.run_events(
                    farm_id=farm_id,
                    sector_id=conversation.sector_id,
                    message=body.message,
                    history=history,
                    access=access,
                    db=db,
                    prior_evidence=prior_evidence,
                ):
                    if event.type == "progress":
                        if not first_progress_seen:
                            first_progress_seen = True
                            ai_chat_stage_seconds.labels("chat", "first_progress").observe(
                                time.monotonic() - started
                            )
                        yield _sse("progress", event.payload)
                    elif event.type == "answer":
                        if not first_answer_seen:
                            first_answer_seen = True
                            ai_chat_stage_seconds.labels("chat", "first_answer").observe(
                                time.monotonic() - started
                            )
                        yield _sse("delta", {"text": event.payload["text"] + " "})
                    elif event.type == "done":
                        result = event.payload["result"]

            assert result is not None
            action = await _finalise_turn(
                conversation=conversation,
                assistant_message=assistant_message,
                result=result,
                access=access,
                db=db,
            )
            await db.commit()
            ai_chat_stage_seconds.labels("chat", "complete").observe(time.monotonic() - started)
            ai_chat_turns_total.labels("chat", result.validation_status).inc()
            yield _sse("done", _done_payload(result, action))
        except (asyncio.CancelledError, TimeoutError):
            # Client went away, or the turn outran its budget. The interrupted row
            # written above is already the truth; just record it and stop.
            ai_chat_turns_total.labels("chat", "interrupted").inc()
            await db.rollback()
            raise
        except Exception:
            logger.exception("Streaming chat turn failed")
            ai_chat_turns_total.labels("chat", "failed").inc()
            await db.rollback()
            if assistant_message is not None:
                await _mark_message_failed(assistant_message_id, db)
            yield _sse("error", {"detail": "Erro ao processar o pedido de chat."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/farms/{farm_id}/chat/conversations",
    response_model=list[ChatConversationOut],
)
async def list_chat_conversations(
    farm_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.farm(farm_id)
    rows = (
        (
            await db.execute(
                select(ChatConversation)
                .where(
                    ChatConversation.farm_id == farm_id,
                    ChatConversation.user_id == access.current_user.id,
                )
                .order_by(ChatConversation.last_message_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [ChatConversationOut.model_validate(row) for row in rows]


@router.get(
    "/farms/{farm_id}/chat/conversations/{conversation_id}",
    response_model=ChatConversationDetail,
)
async def get_chat_conversation(
    farm_id: str,
    conversation_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.farm(farm_id)
    conversation = await owned_conversation(
        conversation_id,
        farm_id=farm_id,
        user_id=access.current_user.id,
        db=db,
    )
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.created_at)
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    actions = await actions_for_conversation(conversation.id, db)
    messages = [
        ChatMessageOut(
            id=row.id,
            role=row.role,
            content=row.content,
            proposed_action=_proposed_action_out(row.proposed_action, actions.get(row.id)),
            degraded=row.degraded,
            model_name=row.model_name,
            created_at=row.created_at,
            evidence=row.evidence or [],
            context_version=row.context_version,
            contract_version=(row.response_metadata or {}).get("contract_version", ""),
            validation_status=(row.response_metadata or {}).get("validation_status", "fallback"),
            recommendation_id=row.recommendation_id,
            surface=row.surface,
            status=row.status,
        )
        for row in rows
    ]
    return ChatConversationDetail(
        **ChatConversationOut.model_validate(conversation).model_dump(),
        messages=messages,
    )


@router.delete(
    "/farms/{farm_id}/chat/conversations/{conversation_id}",
    status_code=204,
)
async def delete_chat_conversation(
    farm_id: str,
    conversation_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await access.farm(farm_id)
    conversation = await owned_conversation(
        conversation_id,
        farm_id=farm_id,
        user_id=access.current_user.id,
        db=db,
    )
    await db.delete(conversation)
    await db.commit()
    return Response(status_code=204)


async def _open_turn(
    *,
    farm_id: str,
    body: ChatRequest,
    access: Access,
    db: AsyncSession,
    scope_prechecked: bool = False,
) -> tuple[ChatConversation, ChatMessage]:
    """Resolve the conversation and detect a retry of an already-answered turn."""
    if not scope_prechecked:
        await access.farm(farm_id)
        if body.sector_id:
            await access.sector_in_farm(body.sector_id, farm_id)

    # Serialize discovery/creation, including retries whose first response was lost
    # before the client learned the conversation ID. This lock is transaction-local.
    if body.client_message_id:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"chat:{access.current_user.id}:{farm_id}:{body.client_message_id}"},
        )
        if body.conversation_id is None:
            previous = (
                await db.execute(
                    select(ChatConversation)
                    .join(ChatMessage, ChatMessage.conversation_id == ChatConversation.id)
                    .where(
                        ChatConversation.user_id == access.current_user.id,
                        ChatConversation.farm_id == farm_id,
                        ChatMessage.client_message_id == body.client_message_id,
                    )
                )
            ).scalar_one_or_none()
            if previous is not None:
                if previous.sector_id != body.sector_id:
                    raise HTTPException(
                        409, detail="A identidade da pergunta pertence a outro âmbito."
                    )
                body = body.model_copy(update={"conversation_id": previous.id})
    conversation = await resolve_conversation(
        conversation_id=body.conversation_id,
        farm_id=farm_id,
        sector_id=body.sector_id,
        user_id=access.current_user.id,
        first_message=body.message,
        db=db,
    )
    existing = None
    if body.client_message_id:
        existing = await find_message_by_client_id(conversation.id, body.client_message_id, db)
    if existing is not None and existing.content != body.message:
        raise HTTPException(409, detail="A identidade da pergunta já foi usada para outro texto.")
    if existing is None:
        existing = await add_chat_message(
            conversation,
            role="user",
            content=body.message,
            db=db,
            client_message_id=body.client_message_id,
        )
    answer = (
        await db.execute(select(ChatMessage).where(ChatMessage.reply_to_id == existing.id))
    ).scalar_one_or_none()
    if answer is None:
        answer = await add_chat_message(
            conversation,
            role="assistant",
            content="",
            status="interrupted",
            surface="chat",
            reply_to_id=existing.id,
            db=db,
        )
    user_id = existing.id
    await db.commit()  # The placeholder survives a disconnect or process crash.
    if answer.status != "complete":
        try:
            # Held until finalisation/rollback. Only one runner may own this question.
            await db.execute(
                select(ChatMessage.id).where(ChatMessage.id == user_id).with_for_update(nowait=True)
            )
        except DBAPIError as exc:
            await db.rollback()
            raise HTTPException(409, detail="Esta pergunta ainda está a ser processada.") from exc
        await db.refresh(answer)
    return conversation, answer


async def _finalise_turn(
    *,
    conversation: ChatConversation,
    assistant_message: ChatMessage,
    result: ChatResult,
    access: Access,
    db: AsyncSession,
):
    """Write the validated answer, its provenance, and any durable proposal."""
    assistant_message.content = result.reply
    assistant_message.status = "complete"
    assistant_message.degraded = result.degraded
    assistant_message.model_name = result.model_name
    assistant_message.evidence = [item.model_dump() for item in result.evidence]
    assistant_message.context_version = result.context_version
    assistant_message.recommendation_id = result.recommendation_id
    assistant_message.proposed_action = (
        result.proposed_action.model_dump() if result.proposed_action else None
    )
    assistant_message.response_metadata = {
        "contract_version": result.contract_version,
        "validation_status": result.validation_status,
        "data_timestamps": result.data_timestamps,
    }
    conversation.last_message_at = datetime.now(UTC)
    await db.flush()

    if result.proposed_action is None:
        return None
    return await record_proposal(
        conversation=conversation,
        chat_message_id=assistant_message.id,
        user_id=access.current_user.id,
        proposed=result.proposed_action,
        # The assistant turn IS the proposal's identity: a retried confirmation of
        # the same message can never become a second action row.
        idempotency_key=f"msg:{assistant_message.id}",
        db=db,
    )


async def _mark_message_failed(message_id: str, db: AsyncSession) -> None:
    message = await db.get(ChatMessage, message_id)
    if message is None:
        return
    message.status = "failed"
    message.content = message.content or ("O assistente não conseguiu concluir esta resposta.")
    await db.commit()


async def _safe_commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except Exception:  # pragma: no cover - best effort on an aborted turn
        await db.rollback()


def _proposed_action_out(
    proposed: dict | None,
    action,
) -> ProposedActionOut | None:
    """Merge the stored proposal with its durable lifecycle state.

    A proposal with no action row predates the action table. Its outcome was never
    recorded, so it is reported as ``legacy`` — never as pending, which would invite
    a second execution of something that may already have run.
    """
    if not proposed:
        return None
    payload = dict(proposed)
    payload.pop("action_id", None)
    payload.pop("status", None)
    payload.pop("error_detail", None)
    if action is None:
        return ProposedActionOut(**payload, status="legacy")
    return ProposedActionOut(
        **payload,
        action_id=action.id,
        status=action.status,
        error_detail=action.error_detail,
    )


def _done_payload(result: ChatResult, action) -> dict:
    return {
        "proposed_action": (
            _proposed_action_out(
                result.proposed_action.model_dump() if result.proposed_action else None,
                action,
            ).model_dump()
            if result.proposed_action
            else None
        ),
        "degraded": result.degraded,
        "model_name": result.model_name,
        "evidence": [item.model_dump() for item in result.evidence],
        "context_version": result.context_version,
        "contract_version": result.contract_version,
        "recommendation_id": result.recommendation_id,
        "validation_status": result.validation_status,
        "data_timestamps": result.data_timestamps,
        "status": "complete",
    }


def _done_payload_from_message(message: ChatMessage, action=None) -> dict:
    proposal = _proposed_action_out(message.proposed_action, action)
    return {
        "proposed_action": proposal.model_dump() if proposal else None,
        "degraded": message.degraded,
        "model_name": message.model_name,
        "evidence": message.evidence or [],
        "context_version": message.context_version or "",
        "contract_version": (message.response_metadata or {}).get("contract_version", ""),
        "recommendation_id": message.recommendation_id,
        "validation_status": (message.response_metadata or {}).get("validation_status", "fallback"),
        "data_timestamps": (message.response_metadata or {}).get("data_timestamps", {}),
        "status": message.status,
        "resumed": True,
    }


async def _run_persisted_chat(
    *,
    farm_id: str,
    body: ChatRequest,
    access: Access,
    db: AsyncSession,
    agent: ChatAgent,
    scope_prechecked: bool = False,
) -> ChatResponse:
    started = time.monotonic()
    conversation, resumed = await _open_turn(
        farm_id=farm_id,
        body=body,
        access=access,
        db=db,
        scope_prechecked=scope_prechecked,
    )
    if resumed.status == "complete":
        actions = await actions_for_conversation(conversation.id, db)
        return ChatResponse(
            reply=resumed.content,
            conversation_id=conversation.id,
            message_id=resumed.id,
            proposed_action=_proposed_action_out(resumed.proposed_action, actions.get(resumed.id)),
            degraded=resumed.degraded,
            model_name=resumed.model_name,
            evidence=resumed.evidence or [],
            context_version=resumed.context_version or "",
            contract_version=(resumed.response_metadata or {}).get("contract_version", ""),
            validation_status=(resumed.response_metadata or {}).get(
                "validation_status", "fallback"
            ),
            data_timestamps=(resumed.response_metadata or {}).get("data_timestamps", {}),
            recommendation_id=resumed.recommendation_id,
            status=resumed.status,
        )

    history = await conversation_history(
        conversation.id, db, exclude_message_id=resumed.reply_to_id
    )
    prior_evidence = await conversation_evidence(conversation.id, db)
    history = history or body.history
    try:
        async with asyncio.timeout(CHAT_TURN_TIMEOUT_SECONDS):
            result = await agent.run(
                farm_id=farm_id,
                sector_id=conversation.sector_id,
                message=body.message,
                history=history,
                access=access,
                db=db,
                prior_evidence=prior_evidence,
            )
    except Exception as exc:
        logger.exception(
            "Chat completion failed; returning explicit degraded response",
            extra={"error_type": type(exc).__name__},
        )
        ai_degraded_responses_total.labels("chat", type(exc).__name__).inc()
        ai_chat_turns_total.labels("chat", "failed").inc()
        result = ChatResult(
            reply=(
                "O assistente está temporariamente indisponível. "
                "As recomendações determinísticas e os dados de monitorização "
                "continuam disponíveis na página do sector."
            ),
            degraded=True,
            model_name=getattr(agent.client, "last_model", None),
            validation_status="fallback",
        )
    else:
        ai_chat_turns_total.labels("chat", result.validation_status).inc()

    assistant_message = resumed
    action = await _finalise_turn(
        conversation=conversation,
        assistant_message=assistant_message,
        result=result,
        access=access,
        db=db,
    )
    await db.commit()
    ai_chat_stage_seconds.labels("chat", "complete").observe(time.monotonic() - started)
    return ChatResponse(
        reply=result.reply,
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        proposed_action=_proposed_action_out(
            result.proposed_action.model_dump() if result.proposed_action else None,
            action,
        ),
        degraded=result.degraded,
        model_name=result.model_name,
        evidence=result.evidence,
        context_version=result.context_version,
        contract_version=result.contract_version,
        recommendation_id=result.recommendation_id,
        validation_status=result.validation_status,
        data_timestamps=result.data_timestamps,
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Proposed-action lifecycle
# ---------------------------------------------------------------------------


@router.get(
    "/farms/{farm_id}/chat/actions/{action_id}",
    response_model=ChatActionOut,
)
async def get_chat_action(
    farm_id: str,
    action_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.farm(farm_id)
    action = await get_owned_action(
        action_id, farm_id=farm_id, user_id=access.current_user.id, db=db
    )
    return ChatActionOut.model_validate(action)


@router.post(
    "/farms/{farm_id}/chat/actions/{action_id}/confirm",
    response_model=ChatActionOut,
)
@limiter.limit("30/minute")
async def confirm_chat_action(
    request: Request,
    farm_id: str,
    action_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    """Execute a proposal the user has explicitly confirmed.

    Permission, scope, and recommendation freshness are re-checked here, not at
    proposal time: the world may have moved since the assistant offered it.
    """
    from app.metrics import ai_chat_actions_total

    await access.farm(farm_id)
    action = await get_owned_action(
        action_id, farm_id=farm_id, user_id=access.current_user.id, db=db
    )
    try:
        action = await confirm_action(action, access=access, db=db)
    except ActionConflict as conflict:
        ai_chat_actions_total.labels(conflict.action.action_type, conflict.action.status).inc()
        return JSONResponse(
            status_code=409,
            content={
                **json.loads(ChatActionOut.model_validate(conflict.action).model_dump_json()),
                "detail": conflict.detail,
            },
        )
    await db.commit()
    await db.refresh(action)
    ai_chat_actions_total.labels(action.action_type, action.status).inc()
    payload = ChatActionOut.model_validate(action)
    if action.status == "failed":
        return JSONResponse(
            status_code=422,
            content=json.loads(payload.model_dump_json()),
        )
    return payload


@router.post(
    "/farms/{farm_id}/chat/actions/{action_id}/cancel",
    response_model=ChatActionOut,
)
async def cancel_chat_action(
    farm_id: str,
    action_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    from app.metrics import ai_chat_actions_total

    await access.farm(farm_id)
    action = await get_owned_action(
        action_id, farm_id=farm_id, user_id=access.current_user.id, db=db
    )
    try:
        action = await cancel_action(action, db)
    except ActionConflict as conflict:
        return JSONResponse(
            status_code=409,
            content={
                **json.loads(ChatActionOut.model_validate(conflict.action).model_dump_json()),
                "detail": conflict.detail,
            },
        )
    await db.commit()
    await db.refresh(action)
    ai_chat_actions_total.labels(action.action_type, "cancelled").inc()
    return ChatActionOut.model_validate(action)


# ---------------------------------------------------------------------------
# Quick actions — card surfaces persisted in the conversation lifecycle
# ---------------------------------------------------------------------------


_QUICK_ACTION_PROMPTS_PT = {
    "farm_summary": "Resumo do dia",
    "explain_sector": "Explicar a recomendação deste sector",
    "missing_data": "O que devo configurar a seguir?",
}


@router.post("/farms/{farm_id}/chat/quick-action", response_model=ChatResponse)
@limiter.limit("10/minute")
async def run_quick_action(
    request: Request,
    farm_id: str,
    body: QuickActionRequest,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Run a card surface and persist it as a conversation turn.

    Quick-action results used to exist only in browser state: their context,
    degraded status, and feedback were lost on reload, and the next chat turn had
    no idea the user had just read a farm summary.
    """
    await access.farm(farm_id)
    if body.sector_id:
        await access.sector_in_farm(body.sector_id, farm_id)
    if body.kind == "explain_sector" and not body.sector_id:
        raise HTTPException(422, detail="sector_id is required for explain_sector")
    await consume_daily_ai_quota(access.current_user.id)

    prompt = _QUICK_ACTION_PROMPTS_PT[body.kind]
    conversation = await resolve_conversation(
        conversation_id=body.conversation_id,
        farm_id=farm_id,
        sector_id=body.sector_id,
        user_id=access.current_user.id,
        first_message=prompt,
        db=db,
    )
    await add_chat_message(conversation, role="user", content=prompt, db=db)

    degraded = False
    structured = None
    try:
        if body.kind == "farm_summary":
            structured = await assistant.summarize_farm_structured(farm_id=farm_id, db=db)
            text = assistant.render_structured(structured)
        elif body.kind == "explain_sector":
            structured = await assistant.explain_recommendation_structured(
                sector_id=body.sector_id, db=db
            )
            text = assistant.render_structured(structured)
        else:
            questions = await assistant.generate_missing_data_questions(farm_id=farm_id, db=db)
            text = (
                "\n".join(f"{index}. {question}" for index, question in enumerate(questions, 1))
                if questions
                else "A configuração está completa."
            )
    except Exception as exc:
        logger.exception(
            "Quick action failed; persisting explicit degraded turn",
            extra={"kind": body.kind, "error_type": type(exc).__name__},
        )
        ai_degraded_responses_total.labels(body.kind, type(exc).__name__).inc()
        degraded = True
        text = (
            "O assistente está temporariamente indisponível. As recomendações "
            "determinísticas continuam disponíveis na página do sector."
        )

    message = await add_chat_message(
        conversation,
        role="assistant",
        content=text,
        db=db,
        degraded=degraded or bool(structured and structured.degraded),
        surface=body.kind,
        evidence=([item.model_dump() for item in structured.evidence] if structured else None),
    )
    await db.commit()
    return ChatResponse(
        reply=text,
        conversation_id=conversation.id,
        message_id=message.id,
        degraded=message.degraded,
        evidence=structured.evidence if structured else [],
        contract_version=CONTRACT_VERSION,
        validation_status="fallback" if message.degraded else "validated",
    )


@router.post(
    "/ai/feedback",
    response_model=AIResponseFeedbackOut,
    status_code=201,
)
@limiter.limit("30/minute")
async def create_ai_feedback(
    request: Request,
    response: Response,
    body: AIResponseFeedbackCreate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    farm_id = body.farm_id
    if body.chat_message_id:
        message = (
            await db.execute(
                select(ChatMessage, ChatConversation.farm_id)
                .join(
                    ChatConversation,
                    ChatMessage.conversation_id == ChatConversation.id,
                )
                .where(
                    ChatMessage.id == body.chat_message_id,
                    ChatMessage.role == "assistant",
                    ChatConversation.user_id == access.current_user.id,
                )
            )
        ).one_or_none()
        if message is None:
            raise HTTPException(404, detail="AI response not found")
        farm_id = message[1]
    if farm_id:
        await access.farm(farm_id)

    # One mutable vote per user per chat message — reloading the UI updates the
    # existing row instead of stacking duplicates (guarded by a partial unique
    # index for concurrent writes).
    row = None
    if body.chat_message_id:
        row = (
            await db.execute(
                select(AIResponseFeedback).where(
                    AIResponseFeedback.user_id == access.current_user.id,
                    AIResponseFeedback.chat_message_id == body.chat_message_id,
                )
            )
        ).scalar_one_or_none()

    if row is None:
        row = AIResponseFeedback(
            user_id=access.current_user.id,
            farm_id=farm_id,
            chat_message_id=body.chat_message_id,
            surface=body.surface,
            entity_id=body.entity_id,
            rating=body.rating,
            comment=body.comment,
            details=body.details,
            reason=body.reason,
            context_version=body.context_version,
            contract_version=body.contract_version or CONTRACT_VERSION,
        )
        db.add(row)
    else:
        row.rating = body.rating
        row.comment = body.comment
        row.details = body.details
        row.reason = body.reason
        row.context_version = body.context_version
        row.contract_version = body.contract_version or CONTRACT_VERSION
        response.status_code = 200
    await db.flush()
    await db.refresh(row)
    await db.commit()
    # The reason label is a fixed short vocabulary, so it stays bounded.
    ai_response_feedback_total.labels(
        body.surface, body.reason or "unspecified", str(body.rating)
    ).inc()
    return AIResponseFeedbackOut.model_validate(row)


async def _sector_provenance(
    sector_id: str,
    db: AsyncSession,
    before: AnalysisProvenance | None = None,
) -> AnalysisProvenance:
    data = await sector_analysis_provenance(sector_id, db)
    if before is not None:
        if before.context_version != data.context_version:
            return before.model_copy(
                update={"context_version": f"changed:{before.context_version}"}
            )
        return before
    return AnalysisProvenance(
        recommendation_id=data.recommendation_id,
        context_version=data.context_version,
        contract_version=data.contract_version,
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/sectors/{sector_id}/ai-analysis-version",
    response_model=AnalysisProvenance,
)
async def get_sector_analysis_version(
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    """Current provenance for a sector, so a client can tell a stored analysis apart
    from a current one without paying for a new model call."""
    await access.sector(sector_id)
    data = await sector_analysis_provenance(sector_id, db)
    return AnalysisProvenance(
        recommendation_id=data.recommendation_id,
        context_version=data.context_version,
        contract_version=data.contract_version,
    )


@router.post("/sectors/{sector_id}/explain", response_model=ExplainResponse)
@limiter.limit("20/minute")
async def explain_sector_recommendation(
    request: Request,
    sector_id: str,
    access: Access,
    body: ExplainRequest = ExplainRequest(),
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain the latest recommendation for a sector in natural language.

    Optionally accepts `user_notes` — field observations or agronomist context
    that will be incorporated into the AI analysis.
    """
    await access.sector(sector_id)
    await consume_daily_ai_quota(access.current_user.id)
    provenance = await _sector_provenance(sector_id, db)
    try:
        structured = await assistant.explain_recommendation_structured(
            sector_id=sector_id, db=db, user_notes=body.user_notes
        )
        explanation = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ExplainResponse(
        explanation=explanation,
        structured=structured,
        provenance=await _sector_provenance(sector_id, db, provenance),
    )


@router.post("/farms/{farm_id}/summary", response_model=SummaryResponse)
@limiter.limit("10/minute")
async def farm_daily_summary(
    request: Request,
    farm_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Produce a natural-language daily status summary for the farm."""
    await access.farm(farm_id)
    await consume_daily_ai_quota(access.current_user.id)
    try:
        context = await assistant.context_builder.build_farm_context(farm_id, db)
        context_payload = json.loads(assistant.context_builder.to_json(context))
        digest = context_digest(context_payload)
        structured = await get_cached_interpretation(
            surface="farm_summary",
            entity_id=farm_id,
            digest=digest,
        )
        if structured is None:
            structured = await assistant.summarize_farm_structured(
                farm_id=farm_id,
                db=db,
                context=context,
            )
            await set_cached_interpretation(
                surface="farm_summary",
                entity_id=farm_id,
                digest=digest,
                interpretation=structured,
            )
        summary = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SummaryResponse(summary=summary, structured=structured)


@router.post("/farms/{farm_id}/questions", response_model=QuestionsResponse)
@limiter.limit("10/minute")
async def missing_data_questions(
    request: Request,
    farm_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Return prioritised configuration questions to improve recommendation confidence."""
    await access.farm(farm_id)
    await consume_daily_ai_quota(access.current_user.id)
    try:
        questions = await assistant.generate_missing_data_questions(farm_id=farm_id, db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return QuestionsResponse(questions=questions)


@router.post("/sectors/{sector_id}/diagnosis", response_model=DiagnosisResponse)
@limiter.limit("20/minute")
async def diagnose_sector(
    request: Request,
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Root-cause diagnosis: explain WHY a sector is in its current hydric state."""
    await access.sector(sector_id)
    await consume_daily_ai_quota(access.current_user.id)
    provenance = await _sector_provenance(sector_id, db)
    try:
        structured = await assistant.diagnose_sector_structured(sector_id=sector_id, db=db)
        diagnosis = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DiagnosisResponse(
        diagnosis=diagnosis,
        structured=structured,
        provenance=await _sector_provenance(sector_id, db, provenance),
    )


@router.post("/probes/{probe_id}/interpret", response_model=InterpretationResponse)
@limiter.limit("20/minute")
async def interpret_probe(
    request: Request,
    probe_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Interpret time-series probe signal patterns (flatline, drainage, etc.)."""
    await access.probe(probe_id)
    await consume_daily_ai_quota(access.current_user.id)
    try:
        structured = await assistant.interpret_probe_patterns_structured(probe_id=probe_id, db=db)
        interpretation = assistant.render_probe_interpretation(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return InterpretationResponse(interpretation=interpretation, structured=structured)


@router.post("/sectors/{sector_id}/change-analysis", response_model=ChangeAnalysisResponse)
@limiter.limit("20/minute")
async def sector_change_analysis(
    request: Request,
    sector_id: str,
    access: Access,
    body: ChangeAnalysisRequest = ChangeAnalysisRequest(),
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain what changed in a sector over the selected recent window."""
    await access.sector(sector_id)
    await consume_daily_ai_quota(access.current_user.id)
    provenance = await _sector_provenance(sector_id, db)
    try:
        structured = await assistant.analyze_sector_changes(
            sector_id=sector_id,
            db=db,
            window_hours=body.window_hours,
        )
        analysis = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChangeAnalysisResponse(
        analysis=analysis,
        structured=structured,
        provenance=await _sector_provenance(sector_id, db, provenance),
    )


@router.post("/alerts/{alert_id}/explain", response_model=ExplainResponse)
@limiter.limit("20/minute")
async def explain_alert(
    request: Request,
    alert_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain an active alert in natural language."""
    await access.alert(alert_id)
    await consume_daily_ai_quota(access.current_user.id)
    try:
        structured = await assistant.explain_anomaly_structured(alert_id=alert_id, db=db)
        explanation = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # An alert explanation is not sector-scoped, so it carries no sector provenance.
    return ExplainResponse(explanation=explanation, structured=structured)


@router.post(
    "/sectors/{sector_id}/effectiveness-analysis",
    response_model=EffectivenessAnalysisResponse,
)
@limiter.limit("10/minute")
async def irrigation_effectiveness_analysis(
    request: Request,
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    await access.sector(sector_id)
    await consume_daily_ai_quota(access.current_user.id)
    provenance = await _sector_provenance(sector_id, db)
    try:
        structured = await assistant.analyze_irrigation_effectiveness(
            sector_id,
            db,
        )
        analysis = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return EffectivenessAnalysisResponse(
        analysis=analysis,
        structured=structured,
        provenance=await _sector_provenance(sector_id, db, provenance),
    )
