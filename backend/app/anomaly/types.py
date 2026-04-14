"""Anomaly data structures.

All anomalies are immutable dataclasses produced by detection rules.
They are converted to Alert records by the anomaly service.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Anomaly:
    anomaly_type: str           # e.g. "flatline", "impossible_jump"
    severity: str               # "critical", "warning", "info"
    confidence: float           # 0.0–1.0
    sector_id: str | None
    probe_id: str | None
    depth_cm: int | None
    detected_at: datetime
    description_pt: str
    description_en: str
    likely_causes: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    data_context: dict = field(default_factory=dict, hash=False, compare=False)

    def dedup_key(self) -> tuple:
        """Key used to deduplicate anomalies of the same type on the same probe/depth."""
        return (self.anomaly_type, self.sector_id, self.probe_id, self.depth_cm)
