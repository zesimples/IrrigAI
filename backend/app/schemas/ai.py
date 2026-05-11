"""Pydantic schemas for the LLM-facing structured agronomic context.

These are the shapes the assistant produces and consumes.  The
`AgronomicInterpretation` schema is the structured output the LLM is asked
to return — it doubles as a validation surface for the grounded answers.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AgronomicEvidence(BaseModel):
    """A single citation backing the LLM's claims.

    `source` should reference a key from the structured context dict
    (e.g. "probe_summary.latest_readings", "weather.forecast", "water_events").
    """
    source: str
    value: str


class AgronomicInterpretation(BaseModel):
    summary: str
    risk_level: Literal["low", "medium", "high"]
    irrigation_advice: str
    evidence: list[AgronomicEvidence] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_explanation: str
    recommended_actions: list[str] = Field(default_factory=list)
