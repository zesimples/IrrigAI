from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class DayProjectionOut(BaseModel):
    date: str
    projected_etc_mm: float
    projected_rain_mm: float
    projected_depletion_mm: float
    projected_depletion_pct: float
    stress_triggered: bool


class StressProjectionOut(BaseModel):
    current_depletion_pct: float
    hours_to_stress: float | None = None
    stress_date: str | None = None
    urgency: str
    message_pt: str
    message_en: str
    projections: list[DayProjectionOut] = []


class ReasonOut(BaseModel):
    order: int
    category: str
    message_pt: str
    message_en: str
    data_key: str | None = None
    data_value: str | None = None

    model_config = {"from_attributes": True}


class RecommendationOut(BaseModel):
    id: str
    sector_id: str
    target_date: date
    generated_at: datetime
    action: str
    confidence_score: float
    confidence_level: str
    irrigation_depth_mm: float | None = None
    irrigation_runtime_min: float | None = None
    suggested_start_time: str | None = None
    is_accepted: bool | None = None
    accepted_at: datetime | None = None
    override_notes: str | None = None
    engine_version: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RecommendationDetail(RecommendationOut):
    reasons: list[ReasonOut] = []
    inputs_snapshot: dict = {}
    computation_log: dict = {}
    stress_projection: StressProjectionOut | None = None


class AcceptRequest(BaseModel):
    notes: str | None = None


class RejectRequest(BaseModel):
    notes: str | None = None


class OverrideRequest(BaseModel):
    custom_action: str | None = None              # e.g. "irrigate", "skip"
    custom_depth_mm: float | None = None
    custom_runtime_min: float | None = None
    override_reason: str                           # required
    override_strategy: str = "one_time"            # "one_time" | "until_next_stage"
    # Legacy fields kept for backwards compat
    irrigation_depth_mm: float | None = None
    irrigation_runtime_min: float | None = None
    notes: str | None = None
