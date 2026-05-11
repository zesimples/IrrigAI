"""Chat and explanation endpoints for the AI assistant layer."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import get_chat_client
from app.config import get_settings
from app.database import get_db
from app.schemas.ai import AgronomicInterpretation

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
    structured: AgronomicInterpretation | None = None


class ExplainRequest(BaseModel):
    user_notes: str | None = None


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
    window_hours: int = 72


class ChangeAnalysisResponse(BaseModel):
    analysis: str
    structured: AgronomicInterpretation


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
        structured = await assistant.chat_structured(
            farm_id=farm_id,
            user_message=body.message,
            db=db,
            sector_id=body.sector_id,
        )
        reply = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(reply=reply, structured=structured)


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
        structured = await assistant.explain_recommendation_structured(
            sector_id=sector_id, db=db, user_notes=body.user_notes
        )
        explanation = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ExplainResponse(explanation=explanation, structured=structured)


@router.post("/farms/{farm_id}/summary", response_model=SummaryResponse)
async def farm_daily_summary(
    farm_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Produce a natural-language daily status summary for the farm."""
    try:
        structured = await assistant.summarize_farm_structured(farm_id=farm_id, db=db)
        summary = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SummaryResponse(summary=summary, structured=structured)


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


@router.post("/sectors/{sector_id}/diagnosis", response_model=DiagnosisResponse)
async def diagnose_sector(
    sector_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Root-cause diagnosis: explain WHY a sector is in its current hydric state."""
    try:
        structured = await assistant.diagnose_sector_structured(sector_id=sector_id, db=db)
        diagnosis = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DiagnosisResponse(diagnosis=diagnosis, structured=structured)


@router.post("/probes/{probe_id}/interpret", response_model=InterpretationResponse)
async def interpret_probe(
    probe_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Interpret time-series probe signal patterns (flatline, drainage, etc.)."""
    try:
        structured = await assistant.interpret_probe_patterns_structured(probe_id=probe_id, db=db)
        interpretation = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return InterpretationResponse(interpretation=interpretation, structured=structured)


@router.post("/sectors/{sector_id}/change-analysis", response_model=ChangeAnalysisResponse)
async def sector_change_analysis(
    sector_id: str,
    body: ChangeAnalysisRequest = ChangeAnalysisRequest(),
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain what changed in a sector over the selected recent window."""
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
async def explain_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    assistant: IrrigationAssistant = Depends(get_assistant),
):
    """Explain an active alert in natural language."""
    try:
        structured = await assistant.explain_anomaly_structured(alert_id=alert_id, db=db)
        explanation = assistant.render_structured(structured)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ExplainResponse(explanation=explanation, structured=structured)
