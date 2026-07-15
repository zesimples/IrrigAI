from datetime import datetime

from pydantic import BaseModel


class RecommendationOutcomeOut(BaseModel):
    id: str
    recommendation_id: str
    sector_id: str
    irrigation_event_id: str | None = None
    detected_event_id: str | None = None
    evaluated_at: datetime
    status: str
    recommended_depth_mm: float | None = None
    actual_applied_mm: float | None = None
    dose_error_mm: float | None = None
    dose_error_pct: float | None = None
    pre_irrigation_vwc: float | None = None
    post_irrigation_vwc: float | None = None
    probe_response_delta: float | None = None
    details: dict

    model_config = {"from_attributes": True}
