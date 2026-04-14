"""Weather anomaly detection rules."""

from datetime import datetime

from app.anomaly.types import Anomaly
from app.anomaly.rules.sensor_rules import Reading

RAIN_MISMATCH_THRESHOLD_MM = 5.0   # station reports >5mm but probes don't respond
RAIN_RESPONSE_DELTA = 0.02          # m³/m³ increase expected from rainfall
RAIN_RESPONSE_WINDOW_H = 12.0       # hours after rain to check for response


def detect_rainfall_mismatch(
    probe_readings_by_depth: dict[int, list[Reading]],   # depth_cm → readings
    rainfall_mm: float,
    rain_observed_at: datetime,
    sector_id: str | None,
    farm_id: str | None,
) -> list[Anomaly]:
    """Weather station reports >5mm rainfall but no moisture response at any depth.

    Also flags the inverse: moisture spike without recorded rain or irrigation.

    Args:
        probe_readings_by_depth: depth_cm → sorted list of readings around the rain event
        rainfall_mm: mm recorded at weather station
        rain_observed_at: timestamp of rain observation
        sector_id: sector being checked
        farm_id: farm (for station context)
    """
    anomalies: list[Anomaly] = []

    # Case 1: station reports rain but probes don't respond
    if rainfall_mm >= RAIN_MISMATCH_THRESHOLD_MM:
        window_end = datetime.fromtimestamp(
            rain_observed_at.timestamp() + RAIN_RESPONSE_WINDOW_H * 3600,
            tz=rain_observed_at.tzinfo,
        )
        any_response = False
        for depth_cm, readings in probe_readings_by_depth.items():
            before = [r for r in readings if r.timestamp <= rain_observed_at]
            after = [r for r in readings if rain_observed_at < r.timestamp <= window_end]
            if not before or not after:
                continue
            delta = max((r.vwc for r in after), default=0.0) - before[-1].vwc
            if delta >= RAIN_RESPONSE_DELTA:
                any_response = True
                break

        if not any_response and probe_readings_by_depth:
            anomalies.append(Anomaly(
                anomaly_type="rainfall_mismatch_no_probe_response",
                severity="info",
                confidence=0.65,
                sector_id=sector_id,
                probe_id=None,
                depth_cm=None,
                detected_at=rain_observed_at,
                description_pt=(
                    f"Estação meteorológica registou {rainfall_mm:.1f}mm de chuva mas "
                    f"nenhum sensor respondeu em {RAIN_RESPONSE_WINDOW_H:.0f}h"
                ),
                description_en=(
                    f"Weather station recorded {rainfall_mm:.1f}mm of rain but "
                    f"no probe showed moisture increase in {RAIN_RESPONSE_WINDOW_H:.0f}h"
                ),
                likely_causes=(
                    "Localised rainfall — weather station too far from field",
                    "Rain gauge malfunction or blockage",
                    "Canopy interception preventing soil infiltration",
                ),
                recommended_actions=(
                    "Verify distance between weather station and field",
                    "Cross-check with regional radar or a closer rain gauge",
                    "Inspect rain gauge for debris blockage",
                ),
                data_context={
                    "rainfall_mm": rainfall_mm,
                    "rain_observed_at": rain_observed_at.isoformat(),
                    "response_window_h": RAIN_RESPONSE_WINDOW_H,
                    "depths_checked": list(probe_readings_by_depth.keys()),
                },
            ))

    # Case 2: probes show moisture spike without recorded rain or irrigation
    if rainfall_mm < RAIN_MISMATCH_THRESHOLD_MM:
        for depth_cm, readings in probe_readings_by_depth.items():
            if len(readings) < 2:
                continue
            for i in range(1, len(readings)):
                delta = readings[i].vwc - readings[i - 1].vwc
                if delta >= 0.05:   # significant moisture increase unexplained by rain
                    anomalies.append(Anomaly(
                        anomaly_type="rainfall_mismatch_unexplained_spike",
                        severity="info",
                        confidence=0.60,
                        sector_id=sector_id,
                        probe_id=None,
                        depth_cm=depth_cm,
                        detected_at=readings[i].timestamp,
                        description_pt=(
                            f"Aumento súbito de humidade ({delta:.3f} m³/m³) a {depth_cm}cm "
                            f"sem chuva ou irrigação registada"
                        ),
                        description_en=(
                            f"Unexplained moisture spike ({delta:.3f} m³/m³) at {depth_cm}cm "
                            f"with no recorded rain or irrigation"
                        ),
                        likely_causes=(
                            "Unrecorded irrigation event",
                            "Localised rain not captured by weather station",
                            "Sensor disturbance",
                        ),
                        recommended_actions=(
                            "Check irrigation controller logs for unlogged events",
                            "Verify weather station records vs. local observation",
                        ),
                        data_context={
                            "delta_vwc": round(delta, 4),
                            "timestamp": readings[i].timestamp.isoformat(),
                            "depth_cm": depth_cm,
                            "station_rain_mm": rainfall_mm,
                        },
                    ))
                    break  # one anomaly per depth is enough

    return anomalies
