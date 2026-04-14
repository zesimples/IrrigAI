"""Irrigation anomaly detection rules."""

from datetime import datetime

from app.anomaly.types import Anomaly
from app.anomaly.rules.sensor_rules import Reading

UNDERPERFORMANCE_THRESHOLD = 0.70   # applied < 70% of recommended
UNDERPERFORMANCE_MIN_EVENTS = 3
DEEP_DRAINAGE_DEPTH_CM = 60         # threshold depth for over-irrigation detection
DEEP_DRAINAGE_DELTA = 0.02          # m³/m³ increase at deep layer


def detect_irrigation_underperformance(
    events: list[dict],     # list of {"applied_mm": float, "recommended_mm": float, "event_at": datetime}
    sector_id: str | None,
    probe_id: str | None = None,
) -> list[Anomaly]:
    """Applied water < 70% of recommended for 3+ consecutive events.

    Each event dict should have:
        applied_mm: float
        recommended_mm: float
        event_at: datetime
    """
    if len(events) < UNDERPERFORMANCE_MIN_EVENTS:
        return []

    anomalies: list[Anomaly] = []
    under_run: list[dict] = []

    for event in events:
        recommended = event.get("recommended_mm", 0.0)
        applied = event.get("applied_mm", 0.0)
        if recommended <= 0:
            under_run = []
            continue
        ratio = applied / recommended
        if ratio < UNDERPERFORMANCE_THRESHOLD:
            under_run.append(event)
        else:
            if len(under_run) >= UNDERPERFORMANCE_MIN_EVENTS:
                anomalies.append(_make_underperformance(under_run, sector_id))
            under_run = []

    if len(under_run) >= UNDERPERFORMANCE_MIN_EVENTS:
        anomalies.append(_make_underperformance(under_run, sector_id))

    return anomalies


def _make_underperformance(events: list[dict], sector_id: str | None) -> Anomaly:
    n = len(events)
    avg_ratio = sum(e["applied_mm"] / e["recommended_mm"] for e in events if e["recommended_mm"] > 0) / n
    last_ts = max(e["event_at"] for e in events)
    return Anomaly(
        anomaly_type="irrigation_underperformance",
        severity="warning",
        confidence=0.85,
        sector_id=sector_id,
        probe_id=None,
        depth_cm=None,
        detected_at=last_ts,
        description_pt=(
            f"{n} eventos consecutivos de irrigação com <70% da dose recomendada "
            f"(média: {avg_ratio:.0%} do recomendado)"
        ),
        description_en=(
            f"{n} consecutive irrigation events with <70% of recommended depth "
            f"(avg: {avg_ratio:.0%} of recommended)"
        ),
        likely_causes=(
            "Pressure drop in the irrigation network",
            "Clogged emitters reducing flow",
            "Incorrect runtime programmed in controller",
            "Valve malfunction — partial opening",
        ),
        recommended_actions=(
            "Measure system pressure at the sector inlet",
            "Perform emitter flow test and clean or replace clogged emitters",
            "Verify controller runtime matches agronomic recommendation",
        ),
        data_context={
            "n_events": n,
            "avg_applied_ratio": round(avg_ratio, 3),
            "events": [
                {
                    "event_at": e["event_at"].isoformat() if isinstance(e["event_at"], datetime) else e["event_at"],
                    "applied_mm": e["applied_mm"],
                    "recommended_mm": e["recommended_mm"],
                }
                for e in events
            ],
        },
    )


def detect_over_irrigation(
    shallow_readings: list[Reading],    # 10 cm or 30 cm
    deep_readings: list[Reading],       # 60 cm or 90 cm
    irrigation_start: datetime,
    sector_id: str | None,
    probe_id: str | None,
) -> list[Anomaly]:
    """Deep layer (60cm+) shows moisture increase after irrigation → water past root zone."""
    if not deep_readings:
        return []

    response_window_h = 12.0
    window_end = datetime.fromtimestamp(
        irrigation_start.timestamp() + response_window_h * 3600,
        tz=irrigation_start.tzinfo,
    )

    before_deep = [r for r in deep_readings if r.timestamp <= irrigation_start]
    after_deep = [r for r in deep_readings if irrigation_start < r.timestamp <= window_end]

    if not before_deep or not after_deep:
        return []

    vwc_before = before_deep[-1].vwc
    max_after = max(r.vwc for r in after_deep)
    delta = max_after - vwc_before

    if delta < DEEP_DRAINAGE_DELTA:
        return []

    return [Anomaly(
        anomaly_type="over_irrigation",
        severity="info",
        confidence=0.75,
        sector_id=sector_id,
        probe_id=probe_id,
        depth_cm=DEEP_DRAINAGE_DEPTH_CM,
        detected_at=after_deep[-1].timestamp,
        description_pt=(
            f"Humidade aumentou {delta:.3f} m³/m³ na camada profunda ({DEEP_DRAINAGE_DEPTH_CM}cm) "
            f"após irrigação — possível drenagem profunda"
        ),
        description_en=(
            f"Moisture increased {delta:.3f} m³/m³ at deep layer ({DEEP_DRAINAGE_DEPTH_CM}cm) "
            f"after irrigation — possible deep drainage below root zone"
        ),
        likely_causes=(
            "Irrigation depth exceeds root zone storage capacity",
            "MAD set too low relative to actual soil water holding capacity",
            "Shallow effective root zone (soil compaction or young trees)",
        ),
        recommended_actions=(
            "Reduce irrigation runtime to limit gross depth",
            "Review MAD setting — consider increasing to 50–60%",
            "Check effective root zone depth with soil probe",
        ),
        data_context={
            "irrigation_start": irrigation_start.isoformat(),
            "deep_vwc_before": vwc_before,
            "deep_vwc_max_after": max_after,
            "delta": round(delta, 4),
            "depth_cm": DEEP_DRAINAGE_DEPTH_CM,
        },
    )]
