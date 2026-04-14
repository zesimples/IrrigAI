"""Tests for AlertEngine — unit tests using mocked DB interactions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.alerts.engine import (
    AlertEngine,
    _missing_config_alert,
    _stale_probe_alert,
    _stale_weather_alert,
    _water_stress_alert,
    _over_irrigation_alert,
    _rain_skip_alert,
    _low_confidence_alert,
)
from app.core.enums import AlertSeverity, AlertType
from app.models import Alert

FARM_ID = "farm-001"
SECTOR_ID = "sec-001"
SECTOR_NAME = "Norte"


# ---------------------------------------------------------------------------
# Factory helper tests
# ---------------------------------------------------------------------------

def test_water_stress_alert_warning():
    alert = _water_stress_alert(SECTOR_NAME, 82.0, FARM_ID, SECTOR_ID)
    assert alert.alert_type == AlertType.WATER_STRESS
    assert alert.severity == AlertSeverity.WARNING
    assert "82" in alert.description_pt


def test_water_stress_alert_critical():
    alert = _water_stress_alert(SECTOR_NAME, 95.0, FARM_ID, SECTOR_ID)
    assert alert.severity == AlertSeverity.CRITICAL


def test_over_irrigation_alert():
    alert = _over_irrigation_alert(SECTOR_NAME, FARM_ID, SECTOR_ID)
    assert alert.alert_type == AlertType.OVER_IRRIGATION
    assert alert.severity == AlertSeverity.WARNING


def test_rain_skip_alert():
    alert = _rain_skip_alert(SECTOR_NAME, 15.0, FARM_ID, SECTOR_ID)
    assert alert.alert_type == AlertType.RAIN_SKIP
    assert alert.severity == AlertSeverity.INFO
    assert "15" in alert.description_pt


def test_stale_probe_alert():
    alert = _stale_probe_alert(SECTOR_NAME, 12.5, FARM_ID, SECTOR_ID)
    assert alert.alert_type == AlertType.STALE_PROBE
    assert alert.severity == AlertSeverity.WARNING
    assert "12.5" in alert.description_pt


def test_stale_weather_alert():
    alert = _stale_weather_alert(30.0, FARM_ID)
    assert alert.alert_type == AlertType.STALE_WEATHER
    assert alert.sector_id is None


def test_missing_config_alert():
    alert = _missing_config_alert(SECTOR_NAME, ["irrigation system not configured"], FARM_ID, SECTOR_ID)
    assert alert.alert_type == AlertType.MISSING_DATA
    assert "irrigation" in alert.description_pt.lower()


def test_low_confidence_alert():
    alert = _low_confidence_alert(SECTOR_NAME, 0.35, FARM_ID, SECTOR_ID)
    assert alert.alert_type == AlertType.LOW_CONFIDENCE
    assert "35%" in alert.description_pt


# ---------------------------------------------------------------------------
# Reconciliation logic tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconcile_creates_new_alerts():
    """New alert types not in existing → should be added."""
    engine = AlertEngine()
    db = AsyncMock()

    # Existing: no active alerts
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    new_alerts = [_water_stress_alert(SECTOR_NAME, 85.0, FARM_ID, SECTOR_ID)]
    await engine.reconcile_alerts(FARM_ID, new_alerts, db)

    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reconcile_no_duplicates():
    """Existing active alert of same type+sector → update, don't create new."""
    engine = AlertEngine()
    db = AsyncMock()

    existing = Alert(
        id="existing-001",
        alert_type=AlertType.WATER_STRESS,
        sector_id=SECTOR_ID,
        farm_id=FARM_ID,
        severity=AlertSeverity.WARNING,
        title_pt="x", title_en="x",
        description_pt="old", description_en="old",
        is_active=True,
    )
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
        )
    )

    new_alerts = [_water_stress_alert(SECTOR_NAME, 90.0, FARM_ID, SECTOR_ID)]
    await engine.reconcile_alerts(FARM_ID, new_alerts, db)

    # Should NOT call db.add (update in place instead)
    db.add.assert_not_called()
    # Existing alert should be updated
    assert existing.description_pt != "old"


@pytest.mark.asyncio
async def test_reconcile_auto_resolves_fixed_alerts():
    """Existing active alert not in new alerts → auto-resolve."""
    engine = AlertEngine()
    db = AsyncMock()

    existing = Alert(
        id="existing-002",
        alert_type=AlertType.WATER_STRESS,
        sector_id=SECTOR_ID,
        farm_id=FARM_ID,
        severity=AlertSeverity.WARNING,
        title_pt="x", title_en="x",
        description_pt="x", description_en="x",
        is_active=True,
    )
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
        )
    )

    # No new alerts — water stress is resolved
    await engine.reconcile_alerts(FARM_ID, [], db)

    assert existing.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reconcile_different_type_not_resolved():
    """Existing alert of different type not in new → gets resolved too if not in new_alerts."""
    engine = AlertEngine()
    db = AsyncMock()

    existing_ws = Alert(
        id="e1", alert_type=AlertType.WATER_STRESS, sector_id=SECTOR_ID, farm_id=FARM_ID,
        severity=AlertSeverity.WARNING, title_pt="x", title_en="x",
        description_pt="x", description_en="x", is_active=True,
    )
    existing_sp = Alert(
        id="e2", alert_type=AlertType.STALE_PROBE, sector_id=SECTOR_ID, farm_id=FARM_ID,
        severity=AlertSeverity.WARNING, title_pt="x", title_en="x",
        description_pt="x", description_en="x", is_active=True,
    )
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing_ws, existing_sp])))
        )
    )

    # Only stale probe in new alerts
    new_alerts = [_stale_probe_alert(SECTOR_NAME, 8.0, FARM_ID, SECTOR_ID)]
    await engine.reconcile_alerts(FARM_ID, new_alerts, db)

    # Water stress should be auto-resolved, stale probe updated
    assert existing_ws.is_active is False
    assert existing_sp.is_active is True  # still active, was updated
