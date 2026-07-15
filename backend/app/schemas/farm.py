from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class FarmBase(BaseModel):
    name: str
    location_lat: float | None = Field(None, ge=-90, le=90)
    location_lon: float | None = Field(None, ge=-180, le=180)
    elevation_m: float | None = Field(None, ge=-500, le=9000)
    region: str | None = None
    timezone: str = "Europe/Lisbon"

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        if (self.location_lat is None) != (self.location_lon is None):
            raise ValueError("location_lat and location_lon must be provided together")
        return self


class FarmCreate(FarmBase):
    owner_id: str | None = None  # Optional in MVP; resolved server-side to first available user


class FarmUpdate(BaseModel):
    name: str | None = None
    location_lat: float | None = Field(None, ge=-90, le=90)
    location_lon: float | None = Field(None, ge=-180, le=180)
    elevation_m: float | None = Field(None, ge=-500, le=9000)
    region: str | None = None
    timezone: str | None = None


class FarmOut(FarmBase):
    id: str
    owner_id: str
    is_archived: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FarmDetail(FarmOut):
    plot_count: int = 0
    sector_count: int = 0


class FarmCredentialsUpsert(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=500)
    project_id: str | None = Field(None, max_length=50)
    weather_device_id: str | None = Field(None, max_length=50)


class FarmCredentialsStatus(BaseModel):
    configured: bool
    has_username: bool
    has_password: bool
    has_client_id: bool
    has_client_secret: bool
    project_id: str | None = None
    weather_device_id: str | None = None


class ProviderResource(BaseModel):
    id: str
    name: str
    kind: str | None = None
    project_id: str | None = None
    serial_number: str | None = None


class ProviderDiscovery(BaseModel):
    projects: list[ProviderResource]
    devices: list[ProviderResource]
