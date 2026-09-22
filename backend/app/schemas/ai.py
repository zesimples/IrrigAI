"""Pydantic schemas for the LLM-facing structured agronomic context.

These are the shapes the assistant produces and consumes.  The
`AgronomicInterpretation` schema is the structured output the LLM is asked
to return — it doubles as a validation surface for the grounded answers.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AgronomicCitation(BaseModel):
    """The only evidence shape the LLM may produce."""

    evidence_id: str


class AgronomicEvidence(BaseModel):
    """A server-resolved citation safe to return to API consumers.

    The optional defaults preserve parsing of cached/test responses from before
    evidence IDs. Runtime responses are always populated by the server registry.
    """

    evidence_id: str = ""
    source: str
    value: str
    label: str = "Dados"


class AnswerConfidence(BaseModel):
    """Three independent confidence axes, all derived by the server.

    ``engine_confidence`` is the deterministic engine's own level, ``data_quality``
    grades the measured inputs, and ``explanation_status`` says whether the prose
    was generated or fell back.  See ``app/ai/answer_confidence.py`` for the rules.
    Defaults keep cached/pre-A1 payloads parseable.
    """

    engine_confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    data_quality: Literal["fresh", "stale", "missing", "unknown"] = "unknown"
    explanation_status: Literal["generated", "degraded", "unavailable"] = "generated"
    score: float = Field(default=0.4, ge=0.0, le=1.0)
    basis: str = ""


class AgronomicInterpretationDraft(BaseModel):
    """Structured model output before evidence IDs are resolved by the server."""

    summary: str
    risk_level: Literal["low", "medium", "high"]
    irrigation_advice: str
    evidence: list[AgronomicCitation] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    confidence_explanation: str
    recommended_actions: list[str] = Field(default_factory=list)


class AgronomicInterpretation(BaseModel):
    summary: str
    risk_level: Literal["low", "medium", "high"]
    irrigation_advice: str
    evidence: list[AgronomicEvidence] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    # DEPRECATED for API consumers: kept for compatibility, but it is no longer a
    # model-authored percentage. The server derives it from ``confidence`` below.
    confidence_score: float = Field(default=0.4, ge=0.0, le=1.0)
    confidence_explanation: str
    confidence: AnswerConfidence = Field(default_factory=AnswerConfidence)
    recommended_actions: list[str] = Field(default_factory=list)
    degraded: bool = False
    error_code: str | None = None


class StructuredAIResponse(BaseModel):
    """Backward-compatible wrapper for string UI plus structured evidence."""

    text: str
    structured: AgronomicInterpretation


ProposedActionType = Literal[
    "override_recommendation",
    "accept_recommendation",
    "reject_recommendation",
    "regenerate_recommendation",
    "run_calibration",
]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ProposedAction(BaseModel):
    type: ProposedActionType
    summary: str
    sector_id: str | None = None
    recommendation_id: str | None = None
    params: dict = Field(default_factory=dict)
