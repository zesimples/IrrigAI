"""Stable versions of the actual canonical inputs, not just their latest timestamps."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_runtime import CONTRACT_VERSION


@dataclass(frozen=True)
class AnalysisProvenanceData:
    recommendation_id: str | None
    context_version: str
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict:
        return vars(self).copy()


def compute_context_version(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def context_input_version(payload: dict) -> str:
    # These blocks use request time as observed_at in the absence of data.
    # Preserve real source timestamps and freshness states, removing clock noise.
    payload = {
        key: dict(value) if isinstance(value, dict) else value for key, value in payload.items()
    }
    for name in ("scope", "crop_state", "alerts_and_limitations"):
        if isinstance(payload.get(name), dict):
            payload[name].pop("observed_at", None)

    def stable(node):
        if isinstance(node, dict):
            return {
                key: stable(value)
                for key, value in node.items()
                if key not in {"hours_since_reading", "age_hours", "hours_since_last_reading"}
            }
        if isinstance(node, list):
            return [stable(value) for value in node]
        return node

    return compute_context_version([json.dumps(stable(payload), sort_keys=True, default=str)])


async def sector_analysis_provenance(sector_id: str, db: AsyncSession) -> AnalysisProvenanceData:
    from app.ai.context_builder import build_sector_ai_context_v2

    context = await build_sector_ai_context_v2(sector_id, db, compact=False)
    return AnalysisProvenanceData(
        recommendation_id=context.engine_decision.get("recommendation_id"),
        context_version=context_input_version(context.to_dict()),
    )
