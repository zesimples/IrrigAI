"""Tests for override workflow — audit trail, sector override persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.sector_override import SectorOverride
from app.services.audit_service import AuditService, OVERRIDE_CREATED, OVERRIDE_REMOVED


# ---------------------------------------------------------------------------
# SectorOverride model
# ---------------------------------------------------------------------------

def test_sector_override_defaults():
    override = SectorOverride(
        sector_id="sec-001",
        override_type="fixed_depth",
        value=12.0,
        reason="Visual stress signs observed",
        is_active=True,
        override_strategy="one_time",
    )
    assert override.is_active is True
    assert override.override_type == "fixed_depth"
    assert override.value == 12.0


def test_sector_override_skip_type():
    override = SectorOverride(
        sector_id="sec-001",
        override_type="skip",
        value=None,
        reason="Rain incoming",
        is_active=True,
        override_strategy="one_time",
    )
    assert override.value is None
    assert override.override_type == "skip"


# ---------------------------------------------------------------------------
# Audit service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_log_created_for_override():
    """AuditService.log should add an AuditLog entry via db.add."""
    svc = AuditService()
    db = AsyncMock()
    db.flush = AsyncMock()

    await svc.log(
        action=OVERRIDE_CREATED,
        entity_type="sector_override",
        entity_id="ov-001",
        db=db,
        after_data={"sector_id": "sec-001", "type": "fixed_depth"},
    )

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.action == OVERRIDE_CREATED
    assert added.entity_type == "sector_override"
    assert added.entity_id == "ov-001"


@pytest.mark.asyncio
async def test_audit_log_created_for_removal():
    svc = AuditService()
    db = AsyncMock()
    db.flush = AsyncMock()

    await svc.log(
        action=OVERRIDE_REMOVED,
        entity_type="sector_override",
        entity_id="ov-001",
        db=db,
        before_data={"is_active": True},
        after_data={"is_active": False},
    )

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.action == OVERRIDE_REMOVED
    assert added.before_data == {"is_active": True}
    assert added.after_data == {"is_active": False}


@pytest.mark.asyncio
async def test_audit_service_does_not_raise_on_db_error():
    """AuditService should swallow DB errors gracefully."""
    svc = AuditService()
    db = AsyncMock()
    db.add.side_effect = RuntimeError("DB exploded")

    # Should not raise
    await svc.log(OVERRIDE_CREATED, "sector_override", "ov-001", db)


# ---------------------------------------------------------------------------
# Engine override application
# ---------------------------------------------------------------------------

def test_override_types_coverage():
    """All override types can be instantiated."""
    from app.core.enums import OverrideType
    for ot in OverrideType:
        override = SectorOverride(
            sector_id="sec-001",
            override_type=ot.value,
            value=10.0 if ot == OverrideType.FIXED_DEPTH else None,
            reason="test",
            is_active=True,
            override_strategy="one_time",
        )
        assert override.override_type == ot.value


def test_override_strategy_values():
    from app.core.enums import OverrideStrategy
    assert OverrideStrategy.ONE_TIME.value == "one_time"
    assert OverrideStrategy.UNTIL_NEXT_STAGE.value == "until_next_stage"


# ---------------------------------------------------------------------------
# Recommendation override request schema
# ---------------------------------------------------------------------------

def test_override_request_schema_new_fields():
    from app.schemas.recommendation import OverrideRequest

    req = OverrideRequest(
        custom_action="irrigate",
        custom_depth_mm=8.0,
        custom_runtime_min=120,
        override_reason="Visual stress observed",
        override_strategy="until_next_stage",
    )
    assert req.custom_depth_mm == 8.0
    assert req.override_strategy == "until_next_stage"
    assert req.override_reason == "Visual stress observed"


def test_override_request_legacy_fields_still_work():
    from app.schemas.recommendation import OverrideRequest

    req = OverrideRequest(
        irrigation_depth_mm=10.0,
        override_reason="legacy compat",
    )
    assert req.irrigation_depth_mm == 10.0
    assert req.override_strategy == "one_time"  # default
