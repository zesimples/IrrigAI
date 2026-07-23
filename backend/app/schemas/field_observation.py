"""API contracts for user-authored field observations."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldObservationCreate(BaseModel):
    observation_type: str = Field(min_length=1, max_length=50)
    structured_value: dict | list | None = None
    text: str | None = Field(default=None, max_length=2000)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        if not self.text and self.structured_value is None:
            raise ValueError("text or structured_value is required")
        if self.expires_at and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at")
        return self


class FieldObservationVerify(BaseModel):
    is_verified: bool


class FieldObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sector_id: str
    author_id: str | None
    observation_type: str
    structured_value: dict | list | None
    text: str | None
    observed_at: datetime
    expires_at: datetime | None
    is_verified: bool
    verified_by_id: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
