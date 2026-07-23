"""Chat and explanation endpoints for the AI assistant layer."""

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.access import Access
from app.ai.assistant import IrrigationAssistant
from app.ai.chat_agent import ChatAgent, ChatResult
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import get_chat_client
from app.config import get_settings
from app.database import get_db
from app.limiter import limiter
from app.metrics import ai_degraded_responses_total, ai_response_feedback_total
from app.models import AIResponseFeedback, ChatConversation, ChatMessage
from app.schemas.ai import AgronomicInterpretation
from app.schemas.chat import (
    AIResponseFeedbackCreate,
    AIResponseFeedbackOut,
    ChatConversationDetail,
    ChatConversationOut,
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
)
from app.services.ai_runtime import (
    consume_daily_ai_quota,
    context_digest,
    get_cached_interpretation,
    set_cached_interpretation,
)
from app.services.chat_memory import (
    add_chat_message,
    conversation_history,
    owned_conversation,
    resolve_conversation,
)

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


class SummaryResponse(BaseModel):
    summary: str
    structured: AgronomicInterpretation | None = None


class QuestionsResponse(BaseModel):
    questions: list[str]


class DiagnosisResponse(BaseModel):
    diagnosis: str
    structured: AgronomicInterpretation | None = None


class InterpretationResponse(BaseModel):
    interpretation: str
    structured: AgronomicInterpretation | None = None


class ChangeAnalysisRequest(BaseModel):
    window_hours: int = Field(default=72, ge=1, le=720)


class ChangeAnalysisResponse(BaseModel):
    analysis: str
    structured: AgronomicInterpretation


class EffectivenessAnalysisResponse(BaseModel):
    analysis: str
    structured: AgronomicInterpretation


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
    """SSE transport for chat, including persisted conversation/message identity."""
    await consume_daily_ai_quota(access.current_user.id)
    await access.farm(farm_id)
    if body.sector_id:
        await access.sector_in_farm(body.sector_id, farm_id)

    async def events() -> AsyncIterator[str]:
        try:
            response = await _run_persisted_chat(
                farm_id=farm_id,
                body=body,
                access=access,
                db=db,
                agent=agent,
                scope_prechecked=True,
            )
            yield _sse(
                "conversation",
                {
                    "conversation_id": response.conversation_id,
                    "message_id": response.message_id,
                },
            )
            for chunk in _reply_chunks(response.reply):
                yield _sse("delta", {"text": chunk})
            yield _sse(
                "done",
                {
                    "proposed_action": (
                        response.proposed_action.model_dump() if response.proposed_action else None
                    ),
                    "degraded": response.degraded,
                    "model_name": response.model_name,
                },
            )
            await db.commit()
        except Exception:
            await db.rollback()
            yield _sse(
                "error",
                {"detail": "Erro ao processar o pedido de chat."},
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
    messages = [
        ChatMessageOut(
            id=row.id,
            role=row.role,
            content=row.content,
            proposed_action=row.proposed_action,
            degraded=row.degraded,
            model_name=row.model_name,
            created_at=row.created_at,
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


async def _run_persisted_chat(
    *,
    farm_id: str,
    body: ChatRequest,
    access: Access,
    db: AsyncSession,
    agent: ChatAgent,
    scope_prechecked: bool = False,
) -> ChatResponse:
    if not scope_prechecked:
        await access.farm(farm_id)
        if body.sector_id:
            await access.sector_in_farm(body.sector_id, farm_id)

    conversation = await resolve_conversation(
        conversation_id=body.conversation_id,
        farm_id=farm_id,
        sector_id=body.sector_id,
        user_id=access.current_user.id,
        first_message=body.message,
        db=db,
    )
    persisted = await conversation_history(conversation.id, db)
    history = persisted or body.history
    await add_chat_message(
        conversation,
        role="user",
        content=body.message,
        db=db,
    )
    try:
        result = await agent.run(
            farm_id=farm_id,
            sector_id=conversation.sector_id,
            message=body.message,
            history=history,
            access=access,
            db=db,
        )
    except Exception as exc:
        logger.exception(
            "Chat completion failed; returning explicit degraded response",
            extra={"error_type": type(exc).__name__},
        )
        ai_degraded_responses_total.labels("chat", type(exc).__name__).inc()
        result = ChatResult(
            reply=(
                "O assistente está temporariamente indisponível. "
                "As recomendações determinísticas e os dados de monitorização "
                "continuam disponíveis na página do sector."
            ),
            degraded=True,
            model_name=getattr(agent.client, "last_model", None),
        )
    assistant_message = await add_chat_message(
        conversation,
        role="assistant",
        content=result.reply,
        proposed_action=result.proposed_action,
        degraded=result.degraded,
        model_name=result.model_name,
        db=db,
    )
    await db.commit()
    return ChatResponse(
        reply=result.reply,
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        proposed_action=result.proposed_action,
        degraded=result.degraded,
        model_name=result.model_name,
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _reply_chunks(reply: str, chunk_size: int = 80):
    for start in range(0, len(reply), chunk_size):
        yield reply[start : start + chunk_size]


@router.post(
    "/ai/feedback",
    response_model=AIResponseFeedbackOut,
    status_code=201,
)
async def create_ai_feedback(
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

    row = AIResponseFeedback(
        user_id=access.current_user.id,
        farm_id=farm_id,
        chat_message_id=body.chat_message_id,
        surface=body.surface,
        entity_id=body.entity_id,
        rating=body.rating,
        comment=body.comment,
        details=body.details,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await db.commit()
    ai_response_feedback_total.labels(body.surface, str(body.rating)).inc()
    return AIResponseFeedbackOut.model_validate(row)


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
    try:
        structured = await assistant.explain_recommendation_structured(
            sector_id=sector_id, db=db, user_notes=body.user_notes
        )
        explanation = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ExplainResponse(explanation=explanation, structured=structured)


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
    try:
        structured = await assistant.diagnose_sector_structured(sector_id=sector_id, db=db)
        diagnosis = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DiagnosisResponse(diagnosis=diagnosis, structured=structured)


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
    try:
        structured = await assistant.analyze_sector_changes(
            sector_id=sector_id,
            db=db,
            window_hours=body.window_hours,
        )
        analysis = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChangeAnalysisResponse(analysis=analysis, structured=structured)


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
    )
