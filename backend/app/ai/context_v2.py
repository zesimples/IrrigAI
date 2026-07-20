"""Canonical, versioned context contract for sector-scoped LLM calls.

The ten blocks below are the only first-class AI grounding surface.  Compatibility
aliases for older prompts live in ``context_builder`` and must not become new data
sources: the engine snapshot and shared resolvers remain authoritative.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

SECTOR_AI_CONTEXT_BLOCKS = (
    "scope",
    "engine_decision",
    "water_balance",
    "probe_state",
    "weather",
    "irrigation_execution",
    "outcomes",
    "crop_state",
    "calibration",
    "alerts_and_limitations",
)

_BLOCK_METADATA = ("observed_at", "source", "units")


@dataclass(frozen=True)
class SectorAIContextV2:
    """Stable ten-block context shared by chat, diagnosis, and compact cards."""

    scope: dict
    engine_decision: dict
    water_balance: dict
    probe_state: dict
    weather: dict
    irrigation_execution: dict
    outcomes: dict
    crop_state: dict
    calibration: dict
    alerts_and_limitations: dict
    schema_version: str = "2.0"

    def __post_init__(self) -> None:
        for name in SECTOR_AI_CONTEXT_BLOCKS:
            block = getattr(self, name)
            missing = [key for key in _BLOCK_METADATA if key not in block]
            if missing:
                required = ", ".join(_BLOCK_METADATA)
                raise ValueError(f"{name} must contain block metadata: {required}")

    def to_dict(self) -> dict:
        payload = asdict(self)
        # Dataclass field ordering puts schema_version last; the serialized contract
        # deliberately leads with it and then keeps the ten canonical blocks stable.
        return {
            "schema_version": payload.pop("schema_version"),
            **{name: payload[name] for name in SECTOR_AI_CONTEXT_BLOCKS},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
