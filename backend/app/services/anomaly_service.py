"""Anomaly persistence service.

Runs the detector, converts Anomaly objects to Alert DB records, avoids duplicates,
and resolves stale alerts when anomalies are no longer detected.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomaly.detector import AnomalyDetector
from app.anomaly.types import Anomaly
from app.models import Alert, Plot, Sector
from app.models.base import new_uuid

logger = logging.getLogger(__name__)

_detector = AnomalyDetector()

# Map anomaly_type → AlertType string (uses string values to avoid circular imports)
_ANOMALY_TYPE_TO_ALERT_TYPE: dict[str, str] = {
    "flatline": "probe_anomaly",
    "impossible_jump": "probe_anomaly",
    "impossible_value": "probe_anomaly",
    "depth_inconsistency": "probe_anomaly",
    "no_response_to_irrigation": "probe_anomaly",
    "persistent_saturation": "over_irrigation",
    "suspicious_repetition": "probe_anomaly",
    "sudden_drying": "probe_anomaly",
    "irrigation_underperformance": "underperformance",
    "over_irrigation": "over_irrigation",
    "rainfall_mismatch_no_probe_response": "missing_data",
    "rainfall_mismatch_unexplained_spike": "missing_data",
}


async def run_anomaly_detection(
    sector_id: str,
    db: AsyncSession,
    lookback_hours: int = 72,
) -> list[Anomaly]:
    """Run detector for a sector, persist new alerts, resolve stale ones.

    Returns the list of currently detected anomalies.
    """
    sector = await db.get(Sector, sector_id)
    if sector is None:
        return []

    plot = await db.get(Plot, sector.plot_id)
    farm_id = plot.farm_id if plot else None
    if farm_id is None:
        return []

    detected = await _detector.detect_sector(sector_id, db, lookback_hours)
    detected_keys = {a.dedup_key() for a in detected}

    # Resolve alerts for anomalies that are no longer detected
    await _resolve_stale_alerts(sector_id, farm_id, detected_keys, db)

    # Persist new alerts (skip duplicates)
    for anomaly in detected:
        await _persist_if_new(anomaly, sector_id, farm_id, db)

    await db.commit()
    return detected


async def run_for_farm(
    farm_id: str,
    db: AsyncSession,
    lookback_hours: int = 72,
) -> list[Anomaly]:
    """Run detector for all sectors of a farm."""
    plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
    plots = plots_result.scalars().all()

    all_anomalies: list[Anomaly] = []
    for plot in plots:
        sectors_result = await db.execute(
            select(Sector).where(Sector.plot_id == plot.id)
        )
        for sector in sectors_result.scalars().all():
            try:
                anomalies = await run_anomaly_detection(sector.id, db, lookback_hours)
                all_anomalies.extend(anomalies)
            except Exception:
                logger.exception("Anomaly service failed for sector %s", sector.id)

    return all_anomalies


async def _persist_if_new(
    anomaly: Anomaly,
    sector_id: str,
    farm_id: str,
    db: AsyncSession,
) -> None:
    """Create an Alert record if no similar active alert already exists."""
    alert_type = _ANOMALY_TYPE_TO_ALERT_TYPE.get(anomaly.anomaly_type, "probe_anomaly")

    # Check for existing active alert of same type for same sector/probe/depth
    existing = await db.execute(
        select(Alert).where(
            Alert.sector_id == sector_id,
            Alert.farm_id == farm_id,
            Alert.alert_type == alert_type,
            Alert.is_active.is_(True),
            Alert.data["anomaly_type"].as_string() == anomaly.anomaly_type,
        ).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return  # already active — don't duplicate

    title_en = _make_title(anomaly)
    title_pt = _make_title_pt(anomaly)

    alert = Alert(
        sector_id=sector_id,
        farm_id=farm_id,
        alert_type=alert_type,
        severity=anomaly.severity,
        title_pt=title_pt,
        title_en=title_en,
        description_pt=anomaly.description_pt,
        description_en=anomaly.description_en,
        is_active=True,
        data={
            "anomaly_type": anomaly.anomaly_type,
            "probe_id": anomaly.probe_id,
            "depth_cm": anomaly.depth_cm,
            "confidence": anomaly.confidence,
            "detected_at": anomaly.detected_at.isoformat(),
            "likely_causes": list(anomaly.likely_causes),
            "recommended_actions": list(anomaly.recommended_actions),
            "data_context": anomaly.data_context,
        },
    )
    db.add(alert)
    logger.info(
        "New alert: %s [%s] sector=%s", anomaly.anomaly_type, anomaly.severity, sector_id
    )


async def _resolve_stale_alerts(
    sector_id: str,
    farm_id: str,
    active_anomaly_keys: set[tuple],
    db: AsyncSession,
) -> None:
    """Mark alerts as inactive if their anomaly is no longer detected."""
    result = await db.execute(
        select(Alert).where(
            Alert.sector_id == sector_id,
            Alert.farm_id == farm_id,
            Alert.is_active.is_(True),
        )
    )
    alerts = result.scalars().all()

    for alert in alerts:
        if not alert.data:
            continue
        anomaly_type = alert.data.get("anomaly_type")
        probe_id = alert.data.get("probe_id")
        depth_cm = alert.data.get("depth_cm")
        key = (anomaly_type, sector_id, probe_id, depth_cm)
        if key not in active_anomaly_keys:
            alert.is_active = False
            logger.info("Resolved stale alert %s (anomaly %s no longer detected)", alert.id, anomaly_type)


def _make_title(anomaly: Anomaly) -> str:
    labels = {
        "flatline": "Sensor Flatline Detected",
        "impossible_jump": "Impossible Moisture Jump",
        "impossible_value": "Impossible Sensor Value",
        "depth_inconsistency": "Depth Moisture Inconsistency",
        "no_response_to_irrigation": "No Response to Irrigation",
        "persistent_saturation": "Persistent Soil Saturation",
        "suspicious_repetition": "Suspicious Data Repetition",
        "sudden_drying": "Sudden Unexplained Drying",
        "irrigation_underperformance": "Irrigation Underperformance",
        "over_irrigation": "Possible Over-Irrigation",
        "rainfall_mismatch_no_probe_response": "Rainfall Not Detected by Probes",
        "rainfall_mismatch_unexplained_spike": "Unexplained Moisture Spike",
    }
    title = labels.get(anomaly.anomaly_type, anomaly.anomaly_type.replace("_", " ").title())
    if anomaly.depth_cm:
        title += f" ({anomaly.depth_cm}cm)"
    return title


def _make_title_pt(anomaly: Anomaly) -> str:
    labels = {
        "flatline": "Sensor Bloqueado Detectado",
        "impossible_jump": "Variação de Humidade Impossível",
        "impossible_value": "Valor de Sensor Impossível",
        "depth_inconsistency": "Inconsistência de Humidade por Profundidade",
        "no_response_to_irrigation": "Sem Resposta à Irrigação",
        "persistent_saturation": "Saturação Persistente do Solo",
        "suspicious_repetition": "Repetição Suspeita de Dados",
        "sudden_drying": "Secagem Súbita Inexplicável",
        "irrigation_underperformance": "Subdesempenho de Irrigação",
        "over_irrigation": "Possível Excesso de Irrigação",
        "rainfall_mismatch_no_probe_response": "Chuva Não Detectada pelos Sensores",
        "rainfall_mismatch_unexplained_spike": "Pico de Humidade Inexplicável",
    }
    title = labels.get(anomaly.anomaly_type, anomaly.anomaly_type.replace("_", " ").title())
    if anomaly.depth_cm:
        title += f" ({anomaly.depth_cm}cm)"
    return title
