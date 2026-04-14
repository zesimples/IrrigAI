from datetime import datetime

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: str
    sector_id: str | None = None
    farm_id: str
    alert_type: str
    severity: str
    title_pt: str
    title_en: str
    description_pt: str
    description_en: str
    is_active: bool
    acknowledged_at: datetime | None = None
    data: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AcknowledgeRequest(BaseModel):
    notes: str | None = None
