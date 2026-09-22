"""API contracts for persisted and streaming AI chat."""

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ai import AgronomicEvidence, ChatTurn, ProposedAction

_MAX_DETAILS_BYTES = 4096


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=16)
    sector_id: str | None = None
    # Client-side turn identity. A retried send resumes the same turn instead of
    # appending a duplicate question after a dropped connection.
    client_message_id: str | None = Field(default=None, max_length=80)


class ProposedActionOut(ProposedAction):
    """A proposal plus the durable lifecycle state the server keeps for it.

    ``status`` is ``legacy`` for proposals stored before the action table existed:
    the outcome of those was never recorded, so they are shown as historical and
    must never be replayed as if still pending.
    """

    action_id: str | None = None
    status: Literal[
        "pending",
        "confirmed",
        "succeeded",
        "failed",
        "cancelled",
        "invalidated",
        "legacy",
    ] = "pending"
    error_detail: str | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    message_id: str
    proposed_action: ProposedActionOut | None = None
    degraded: bool = False
    model_name: str | None = None
    # A2: server-resolved grounding travelling with every answer.
    evidence: list[AgronomicEvidence] = Field(default_factory=list)
    context_version: str = ""
    contract_version: str = ""
    recommendation_id: str | None = None
    validation_status: Literal["validated", "repaired", "fallback"] = "validated"
    data_timestamps: dict = Field(default_factory=dict)
    status: Literal["complete", "interrupted", "failed"] = "complete"


class ChatActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    chat_message_id: str | None
    sector_id: str | None
    recommendation_id: str | None
    action_type: str
    summary: str
    status: str
    result: dict | None
    error_detail: str | None
    created_at: datetime
    completed_at: datetime | None


class QuickActionRequest(BaseModel):
    """Run a card surface inside the conversation, so its result is persisted."""

    kind: Literal["farm_summary", "explain_sector", "missing_data"]
    conversation_id: str | None = None
    sector_id: str | None = None


class AnalysisProvenance(BaseModel):
    """What a stored analysis was computed from, so staleness is decidable."""

    recommendation_id: str | None = None
    context_version: str = ""
    contract_version: str = ""
    generated_at: datetime | None = None


class ChatConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    farm_id: str
    sector_id: str | None
    title: str | None
    last_message_at: datetime
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    proposed_action: ProposedActionOut | None = None
    degraded: bool = False
    model_name: str | None = None
    created_at: datetime
    evidence: list[AgronomicEvidence] = Field(default_factory=list)
    context_version: str | None = None
    contract_version: str = ""
    validation_status: str = "fallback"
    recommendation_id: str | None = None
    surface: str | None = None
    status: str = "complete"


class ChatConversationDetail(ChatConversationOut):
    messages: list[ChatMessageOut]


class AIResponseFeedbackCreate(BaseModel):
    surface: Literal[
        "chat",
        "recommendation",
        "farm_summary",
        "alert_explanation",
        "sector_diagnosis",
        "probe_diagnosis",
        "change_analysis",
        "irrigation_effectiveness",
    ]
    rating: Literal[-1, 1]
    farm_id: str | None = None
    chat_message_id: str | None = None
    entity_id: str | None = None
    comment: str | None = Field(default=None, max_length=2000)
    details: dict = Field(default_factory=dict)
    # Actionable reasons: a thumbs-down alone cannot tell a wrong number from an
    # answer that was merely hard to read.
    reason: (
        Literal["wrong_data", "stale_answer", "unclear_explanation", "unhelpful_next_step"] | None
    ) = None
    context_version: str | None = Field(default=None, max_length=120)
    contract_version: str | None = Field(default=None, max_length=20)

    @field_validator("details")
    @classmethod
    def _bound_details(cls, value: dict) -> dict:
        if len(json.dumps(value, default=str)) > _MAX_DETAILS_BYTES:
            raise ValueError("details payload too large")
        return value


class AIResponseFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    surface: str
    rating: int
    farm_id: str | None
    chat_message_id: str | None
    entity_id: str | None
    comment: str | None
    reason: str | None = None
    context_version: str | None = None
    created_at: datetime
