from datetime import datetime

from pydantic import BaseModel


class IrrigationEventCreate(BaseModel):
    start_time: datetime
    end_time: datetime | None = None
    duration_minutes: float | None = None
    applied_mm: float | None = None
    source: str = "manual_log"
    notes: str | None = None


class IrrigationEventUpdate(BaseModel):
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: float | None = None
    applied_mm: float | None = None
    notes: str | None = None


class IrrigationEventOut(BaseModel):
    id: str
    sector_id: str
    start_time: datetime
    end_time: datetime | None = None
    duration_minutes: float | None = None
    applied_mm: float | None = None
    source: str
    recommendation_id: str | None = None
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
