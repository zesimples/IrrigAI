"""Mock probe data provider.

Generates realistic soil moisture data for testing the full engine stack.
Parameterizable for soil type, baseline moisture, anomaly injection, and
irrigation events that cause moisture spikes.
"""

import math
import random
from datetime import UTC, datetime, timedelta

from app.adapters.base import ProbeDataProvider
from app.adapters.dto import ProbeMetadataDTO, ProbeReadingDTO

# VWC ranges by soil texture — (field_capacity, wilting_point)
SOIL_VWC_RANGES: dict[str, tuple[float, float]] = {
    "clay": (0.36, 0.20),
    "clay_loam": (0.28, 0.14),
    "loam": (0.24, 0.10),
    "sandy_loam": (0.18, 0.08),
    "sand": (0.12, 0.05),
}

DEPTHS_CM = [10, 30, 60, 90]

# Anomaly types for injection
_ANOMALY_TYPES = ["flatline", "impossible_jump", "impossible_value"]


class MockProbeProvider(ProbeDataProvider):
    """
    Generates synthetic soil moisture data realistic enough to drive the engine.

    Data characteristics per depth:
    - 10 cm: dries fast, diurnal signal, large spike after irrigation
    - 30 cm: medium drying rate, smaller spike
    - 60 cm: slow drying, delayed spike
    - 90 cm: very slow drying, minimal irrigation response, high baseline

    Anomaly injection (when anomaly_rate > 0):
    - flatline: repeated identical value for several hours
    - impossible_jump: sudden VWC change > 0.20 in one step
    - impossible_value: VWC outside [0, 0.60] range
    """

    DEPTH_PROFILES = {
        10:  {"dry_rate": 0.0055, "irrig_response": 1.00, "irrig_delay_h": 0,  "baseline_pct": 0.60},
        30:  {"dry_rate": 0.0030, "irrig_response": 0.70, "irrig_delay_h": 2,  "baseline_pct": 0.70},
        60:  {"dry_rate": 0.0015, "irrig_response": 0.45, "irrig_delay_h": 6,  "baseline_pct": 0.80},
        90:  {"dry_rate": 0.0008, "irrig_response": 0.20, "irrig_delay_h": 12, "baseline_pct": 0.88},
    }

    def __init__(
        self,
        base_soil_moisture: float = 0.22,
        soil_type: str = "clay_loam",
        anomaly_rate: float = 0.02,
        irrigation_events: list[datetime] | None = None,
        season: str = "summer",
        probe_ids: list[str] | None = None,
    ) -> None:
        self.soil_type = soil_type
        self.anomaly_rate = anomaly_rate
        self.irrigation_events = irrigation_events or []
        self.season = season
        self._probe_ids = probe_ids or ["MOCK-PROBE-001"]

        fc, pwp = SOIL_VWC_RANGES.get(soil_type, (0.28, 0.14))
        self.fc = fc
        self.pwp = pwp
        # Allow override of baseline; clamp to valid range
        self.base_swc = max(pwp + 0.01, min(fc, base_soil_moisture))

    # ------------------------------------------------------------------
    # ProbeDataProvider interface
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """No-op for mock."""

    async def health_check(self) -> bool:
        return True

    async def list_probes(self) -> list[ProbeMetadataDTO]:
        return [
            ProbeMetadataDTO(
                external_id=pid,
                serial_number=f"SN-{pid}",
                manufacturer="MockSense",
                model="MS-4D-Mock",
                depths_cm=DEPTHS_CM,
                last_reading_at=datetime.now(UTC),
                battery_level_pct=85.0,
                status="ok",
            )
            for pid in self._probe_ids
        ]

    async def fetch_probe_metadata(self, probe_external_id: str) -> ProbeMetadataDTO:
        return ProbeMetadataDTO(
            external_id=probe_external_id,
            serial_number=f"SN-{probe_external_id}",
            manufacturer="MockSense",
            model="MS-4D-Mock",
            depths_cm=DEPTHS_CM,
            last_reading_at=datetime.now(UTC),
            battery_level_pct=85.0,
            status="ok",
        )

    async def fetch_readings(
        self,
        probe_external_id: str,
        since: datetime,
        until: datetime,
    ) -> list[ProbeReadingDTO]:
        readings = []
        rng = random.Random(hash(probe_external_id) % (2**31))

        for depth_cm in DEPTHS_CM:
            depth_readings = self._generate_depth_readings(
                probe_external_id=probe_external_id,
                depth_cm=depth_cm,
                since=since,
                until=until,
                rng=rng,
            )
            readings.extend(depth_readings)

        return readings

    # ------------------------------------------------------------------
    # Internal generation logic
    # ------------------------------------------------------------------

    def _generate_depth_readings(
        self,
        probe_external_id: str,
        depth_cm: int,
        since: datetime,
        until: datetime,
        rng: random.Random,
    ) -> list[ProbeReadingDTO]:
        profile = self.DEPTH_PROFILES[depth_cm]
        dry_rate = profile["dry_rate"]
        irrig_response = profile["irrig_response"]
        irrig_delay_h = profile["irrig_delay_h"]
        baseline_pct = profile["baseline_pct"]

        # Starting moisture — deeper = wetter baseline
        swc = self.pwp + (self.fc - self.pwp) * baseline_pct

        # Build hourly timestamps
        since_hour = since.replace(minute=0, second=0, microsecond=0)
        until_hour = until.replace(minute=0, second=0, microsecond=0)

        readings: list[ProbeReadingDTO] = []
        current = since_hour
        flatline_count = 0
        flatline_value = swc

        while current <= until_hour:
            # Diurnal drying (peaks at 14:00)
            hour = current.hour
            diurnal = 0.6 + 0.4 * math.sin(math.pi * (hour - 6) / 12) if 6 <= hour <= 18 else 0.6
            hourly_loss = dry_rate * diurnal if depth_cm <= 30 else dry_rate

            # Irrigation events — moisture spikes at depth-appropriate delay
            for irrig_ts in self.irrigation_events:
                irrig_ts_aware = irrig_ts.replace(tzinfo=UTC) if irrig_ts.tzinfo is None else irrig_ts
                delta_h = (current - irrig_ts_aware).total_seconds() / 3600
                if irrig_delay_h <= delta_h < irrig_delay_h + 1:
                    boost = (self.fc - swc) * irrig_response
                    swc = min(self.fc, swc + boost)

            swc = max(self.pwp + 0.005, swc - hourly_loss)

            # Anomaly injection
            value = swc
            quality = "ok"

            if rng.random() < self.anomaly_rate:
                anomaly_type = rng.choice(_ANOMALY_TYPES)
                if anomaly_type == "flatline":
                    flatline_count = rng.randint(4, 12)
                    flatline_value = value
                elif anomaly_type == "impossible_jump":
                    value = value + rng.choice([-1, 1]) * rng.uniform(0.18, 0.30)
                    quality = "suspect"
                elif anomaly_type == "impossible_value":
                    value = rng.uniform(-0.05, -0.01)
                    quality = "invalid"

            if flatline_count > 0:
                value = flatline_value
                quality = "suspect"
                flatline_count -= 1

            raw = round(max(-0.10, min(0.70, value + rng.gauss(0, 0.001))), 4)
            calibrated = round(raw, 4)

            readings.append(
                ProbeReadingDTO(
                    probe_external_id=probe_external_id,
                    depth_cm=depth_cm,
                    timestamp=current,
                    raw_value=raw,
                    calibrated_value=calibrated,
                    unit="vwc_m3m3",
                    sensor_type="moisture",
                )
            )
            current += timedelta(hours=1)

        return readings
