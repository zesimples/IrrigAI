from datetime import datetime

from pydantic import BaseModel


class FarmBase(BaseModel):
    name: str
    location_lat: float | None = None
    location_lon: float | None = None
    region: str | None = None
    timezone: str = "Europe/Lisbon"


class FarmCreate(FarmBase):
    owner_id: str | None = None  # Optional in MVP; resolved server-side to first available user


class FarmUpdate(BaseModel):
    name: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    region: str | None = None
    timezone: str | None = None


class FarmOut(FarmBase):
    id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FarmDetail(FarmOut):
    plot_count: int = 0
    sector_count: int = 0
