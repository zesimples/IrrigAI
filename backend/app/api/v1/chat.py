"""Chat and explanation endpoints for the AI assistant layer."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import get_chat_client
from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["chat"])


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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    sector_id: str | None = None


class ChatResponse(BaseModel):
    reply: str


class ExplainRequest(BaseModel):
    user_notes: str | None = None


class ExplainResponse(BaseModel):
    explanation: str


class SummaryResponse(BaseModel):
    summary: str


class QuestionsResponse(BaseModel):
    questions: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/farms/{farm_id}/chat", response_model=ChatResponse)
async def farm_chat(
    farm_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Free-form conversational chat about the farm or a specific sector."""
    try:
        reply = await assistant.chat(
            farm_id=farm_id,
            user_message=body.message,
            db=db,
            sector_id=body.sector_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(reply=reply)


@router.post("/sectors/{sector_id}/explain", response_model=ExplainResponse)
async def explain_sector_recommendation(
    sector_id: str,
    body: ExplainRequest = ExplainRequest(),
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain the latest recommendation for a sector in natural language.

    Optionally accepts `user_notes` — field observations or agronomist context
    that will be incorporated into the AI analysis.
    """
    try:
        explanation = await assistant.explain_recommendation(
            sector_id=sector_id, db=db, user_notes=body.user_notes
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ExplainResponse(explanation=explanation)


@router.post("/farms/{farm_id}/summary", response_model=SummaryResponse)
async def farm_daily_summary(
    farm_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Produce a natural-language daily status summary for the farm."""
    try:
        summary = await assistant.summarize_farm(farm_id=farm_id, db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SummaryResponse(summary=summary)


@router.post("/farms/{farm_id}/questions", response_model=QuestionsResponse)
async def missing_data_questions(
    farm_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Return prioritised configuration questions to improve recommendation confidence."""
    try:
        questions = await assistant.generate_missing_data_questions(farm_id=farm_id, db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return QuestionsResponse(questions=questions)


@router.post("/alerts/{alert_id}/explain", response_model=ExplainResponse)
async def explain_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain an active alert in natural language."""
    try:
        explanation = await assistant.explain_anomaly(alert_id=alert_id, db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ExplainResponse(explanation=explanation)
