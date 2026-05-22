# backend/app/services/flowmeter_ingestion.py
"""Flowmeter data ingestion service.

Fetches Water Meter readings from the MyIrrigation API (same endpoint/auth as
probes, different device IDs) and detects irrigation events from the time-series.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event detection
# ---------------------------------------------------------------------------

@dataclass
class DetectedEvent:
    start_time: datetime
    end_time: datetime
    duration_minutes: float
    total_m3_ha: float
    peak_m3_ha: float
    num_readings: int


class IrrigationEventDetector:
    """Detect irrigation events from flowmeter 15-minute time-series data."""

    def detect_events(
        self,
        readings: list[tuple[datetime, float]],
        threshold_m3_ha: float = 0.5,
    ) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        in_event = False
        event_readings: list[tuple[datetime, float]] = []

        for ts, value in sorted(readings, key=lambda x: x[0]):
            if value > threshold_m3_ha:
                in_event = True
                event_readings.append((ts, value))
            else:
                if in_event and event_readings:
                    if len(event_readings) >= 2:
                        events.append(self._build_event(event_readings))
                    in_event = False
                    event_readings = []

        # Close event still open at end of data
        if in_event and len(event_readings) >= 2:
            events.append(self._build_event(event_readings))

        return events

    def _build_event(self, readings: list[tuple[datetime, float]]) -> DetectedEvent:
        start_time = readings[0][0]
        end_time = readings[-1][0]
        duration_minutes = (end_time - start_time).total_seconds() / 60.0
        total_m3_ha = sum(v for _, v in readings)
        peak_m3_ha = max(v for _, v in readings)
        return DetectedEvent(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            total_m3_ha=round(total_m3_ha, 4),
            peak_m3_ha=peak_m3_ha,
            num_readings=len(readings),
        )
