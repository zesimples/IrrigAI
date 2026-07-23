"""API contracts for persisted and streaming AI chat."""

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ai import ChatTurn, ProposedAction

_MAX_DETAILS_BYTES = 4096


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=16)
    sector_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    message_id: str
    proposed_action: ProposedAction | None = None
    degraded: bool = False
    model_name: str | None = None


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
    proposed_action: ProposedAction | None = None
    degraded: bool = False
    model_name: str | None = None
    created_at: datetime


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
    created_at: datetime
