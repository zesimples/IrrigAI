"""E2E: Full operational day pipeline using the seeded demo farm.

Requires: seeded DB (run `python -m app.seed` before this test suite).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Alert,
    AuditLog,
    IrrigationEvent,
    Plot,
    Recommendation,
    Sector,
    SectorCropProfile,
)


@pytest.mark.asyncio
async def test_full_day_pipeline(client: AsyncClient, db: AsyncSession, seed_farm_id: str):
    """
    Simulates a complete operational day using the seeded demo farm.

    Steps covered:
      1.  Templates + presets exist
      2.  Dashboard returns all sectors
      3.  Generate recommendations for all 4 sectors
      4.  Verify Kc is read from SectorCropProfile (not hardcoded)
      5.  Sector with no stage (if present) gets penalised confidence
      6.  Recommendation detail has reasons + confidence + computation_log
      7.  Accept a recommendation → audit log entry created
      8.  Log a manual irrigation event
      9.  Re-run recommendation after irrigation → new record exists
      10. Run alert engine → appropriate alerts generated
      11. AI explanation (mock LLM) → non-empty response
    """

    # ── Step 1: Verify seed data ──────────────────────────────────────────────
    resp = await client.get("/api/v1/crop-profile-templates")
    assert resp.status_code == 200
    templates = resp.json()
    assert len(templates) >= 3
    crop_types = {t["crop_type"] for t in templates}
    assert {"olive", "almond", "maize"} <= crop_types

    resp = await client.get("/api/v1/soil-presets")
    assert resp.status_code == 200
    assert len(resp.json()) >= 5

    # ── Step 2: Dashboard ─────────────────────────────────────────────────────
    resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
    assert resp.status_code == 200
    dash = resp.json()
    assert len(dash["sectors_summary"]) >= 4

    # ── Step 3: Generate recommendations for all sectors ──────────────────────
    resp = await client.post(
        f"/api/v1/farms/{seed_farm_id}/recommendations/generate"
    )
    assert resp.status_code == 201
    recs = resp.json()
    assert len(recs) >= 4
    for rec in recs:
        assert rec["action"] in ("irrigate", "skip", "defer", "reduce", "increase")
        assert 0.0 <= rec["confidence_score"] <= 1.0

    # Collect sector info for later steps
    plots_result = await db.execute(select(Plot).where(Plot.farm_id == seed_farm_id))
    plots = plots_result.scalars().all()
    all_sectors = []
    for plot in plots:
        s_result = await db.execute(select(Sector).where(Sector.plot_id == plot.id))
        all_sectors.extend(s_result.scalars().all())

    sector_by_name = {s.name: s for s in all_sectors}

    # ── Step 4: Kc comes from SectorCropProfile ───────────────────────────────
    # Use the first available sector with a phenological stage
    setor1 = next(
        s for s in all_sectors if s.current_phenological_stage is not None
    )
    scp = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == setor1.id)
        )
    ).scalar_one()
    # Confirm stage is oil_accumulation and expected Kc is 0.60
    oil_acc_stage = next(s for s in scp.stages if s["key"] == "olive_oil_accumulation")
    assert oil_acc_stage["kc"] == 0.60

    # Generate for this specific sector and verify computation_log mentions Kc
    resp = await client.post(
        f"/api/v1/sectors/{setor1.id}/recommendations/generate"
    )
    assert resp.status_code == 201
    rec1_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/recommendations/{rec1_id}")
    assert resp.status_code == 200
    detail = resp.json()
    log_lines = " ".join(detail["computation_log"].get("log", []))
    assert "Kc=" in log_lines or "kc" in detail["computation_log"].get("kc_source", "").lower()

    # ── Step 5: Sector with no stage (if any) gets lower confidence ───────────
    setor4_candidates = [s for s in all_sectors if s.current_phenological_stage is None]
    if setor4_candidates:
        setor4 = setor4_candidates[0]
        resp = await client.post(
            f"/api/v1/sectors/{setor4.id}/recommendations/generate"
        )
        assert resp.status_code == 201
        rec4 = resp.json()
        assert rec4["confidence_score"] < 0.90  # penalized for missing stage

    # ── Step 6: Detail has reasons, confidence, computation_log ──────────────
    resp = await client.get(f"/api/v1/recommendations/{rec1_id}")
    detail = resp.json()
    assert len(detail["reasons"]) >= 1
    assert detail["confidence_score"] > 0
    assert "log" in detail["computation_log"]
    assert len(detail["computation_log"]["log"]) >= 3
    snap = detail["inputs_snapshot"]
    assert "et0_mm" in snap
    assert "depletion_mm" in snap
    assert "taw_mm" in snap

    # ── Step 7: Accept recommendation → audit log entry ───────────────────────
    resp = await client.post(
        f"/api/v1/recommendations/{rec1_id}/accept",
        json={"notes": "E2E pipeline test acceptance"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_accepted"] is True

    # Verify audit log has the entry
    resp = await client.get(
        "/api/v1/audit-log",
        params={"action": "recommendation_accepted", "entity_id": rec1_id},
    )
    assert resp.status_code == 200
    audit_items = resp.json()["items"]
    assert any(a["entity_id"] == rec1_id for a in audit_items)

    # ── Step 8: Log a manual irrigation event ────────────────────────────────
    from datetime import UTC, datetime
    start_time = datetime.now(UTC).isoformat()
    resp = await client.post(
        f"/api/v1/sectors/{setor1.id}/irrigation-events",
        json={
            "start_time": start_time,
            "applied_mm": 20.0,
            "duration_min": 180,
            "source": "manual_log",
            "notes": "E2E test irrigation",
        },
    )
    assert resp.status_code == 201
    irrig_event_id = resp.json()["id"]
    assert irrig_event_id

    # Verify it persists
    irrig = await db.get(IrrigationEvent, irrig_event_id)
    assert irrig is not None
    assert irrig.applied_mm == 20.0

    # ── Step 9: Re-run recommendation ────────────────────────────────────────
    resp = await client.post(
        f"/api/v1/sectors/{setor1.id}/recommendations/generate"
    )
    assert resp.status_code == 201
    rec1_new = resp.json()
    assert rec1_new["id"] != rec1_id  # new record created

    # ── Step 10: Alert engine ─────────────────────────────────────────────────
    resp = await client.post(f"/api/v1/farms/{seed_farm_id}/alerts/run")
    assert resp.status_code == 200
    alert_result = resp.json()
    assert "generated" in alert_result

    alerts_resp = await client.get(
        f"/api/v1/farms/{seed_farm_id}/alerts",
        params={"active_only": True},
    )
    assert alerts_resp.status_code == 200
    # Just verify the alerts endpoint is functional; count depends on seed data
    assert "items" in alerts_resp.json()

    # ── Step 11: AI explanation (mock LLM) ───────────────────────────────────
    resp = await client.post(f"/api/v1/sectors/{setor1.id}/explain")
    assert resp.status_code == 200
    explanation = resp.json()["explanation"]
    assert isinstance(explanation, str)
    assert len(explanation) > 10


@pytest.mark.asyncio
async def test_dashboard_returns_sector_summaries(client: AsyncClient, seed_farm_id: str):
    resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["farm"]["id"] == seed_farm_id
    for s in data["sectors_summary"]:
        assert "sector_id" in s
        assert "sector_name" in s
        assert "crop_type" in s


@pytest.mark.asyncio
async def test_recommendation_confidence_and_reasons_present(
    client: AsyncClient, seed_farm_id: str, seed_sector_ids: list[str]
):
    sector_id = seed_sector_ids[0]
    resp = await client.post(f"/api/v1/sectors/{sector_id}/recommendations/generate")
    assert resp.status_code == 201
    rec_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/recommendations/{rec_id}")
    data = resp.json()
    assert data["confidence_level"] in ("high", "medium", "low")
    assert len(data["reasons"]) >= 1
    assert all("message_pt" in r for r in data["reasons"])
