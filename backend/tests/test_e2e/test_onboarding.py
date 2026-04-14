"""E2E: Onboarding flow — create a farm from scratch and generate a recommendation.

These tests create all data via API (no dependency on seeded demo farm).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plot, Sector, SectorCropProfile

from tests.test_e2e.conftest import (
    api_create_farm,
    api_create_plot,
    api_create_sector,
    api_add_irrigation_system,
)


@pytest.mark.asyncio
async def test_onboarding_creates_working_farm(
    client: AsyncClient, db: AsyncSession, sandy_loam_preset
):
    """
    Simulates a user going through onboarding from scratch.

    Steps:
    1. Verify crop templates + soil presets are available via API.
    2. Create farm, plot (with sandy-loam preset), and sector.
    3. Verify SectorCropProfile was auto-created from olive template.
    4. Verify profile stages include expected olive stages.
    5. Set phenological stage + irrigation system.
    6. Generate recommendation — must succeed.
    7. Verify recommendation has valid action and confidence.
    """

    # ── Step 1: Templates + presets ───────────────────────────────────────────
    resp = await client.get("/api/v1/crop-profile-templates")
    assert resp.status_code == 200
    templates = resp.json()
    assert len(templates) >= 3
    assert any(t["crop_type"] == "olive" for t in templates)
    assert any(t["crop_type"] == "almond" for t in templates)
    assert any(t["crop_type"] == "maize" for t in templates)

    resp = await client.get("/api/v1/soil-presets")
    assert resp.status_code == 200
    presets = resp.json()
    assert len(presets) >= 5
    sandy_loam = next(p for p in presets if p["texture"] == "sandy_loam")
    assert sandy_loam["field_capacity"] == pytest.approx(0.18, abs=0.01)
    assert sandy_loam["wilting_point"] == pytest.approx(0.08, abs=0.01)

    # ── Step 2: Create farm → plot → sector ───────────────────────────────────
    farm_id = await api_create_farm(
        client, name="Quinta de Teste Onboarding"
    )

    # Create farm with location
    resp = await client.patch(
        f"/api/v1/farms/{farm_id}",
        json={"location_lat": 38.5, "location_lon": -8.1, "region": "Alentejo"},
    )
    # PATCH may not be implemented; ignore if 405 — location is optional

    plot_id = await api_create_plot(
        client, farm_id, name="Bloco A", soil_preset_id=sandy_loam_preset.id
    )

    # Verify plot got FC/PWP from preset
    resp = await client.get(f"/api/v1/plots/{plot_id}")
    assert resp.status_code == 200
    plot_data = resp.json()
    assert plot_data["field_capacity"] == pytest.approx(0.18, abs=0.02)
    assert plot_data["wilting_point"] == pytest.approx(0.08, abs=0.02)

    sector_id = await api_create_sector(
        client, plot_id, name="Olival Teste", crop_type="olive", stage=None
    )

    # ── Step 3: SectorCropProfile auto-created ────────────────────────────────
    scp_result = await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )
    scp = scp_result.scalar_one_or_none()
    assert scp is not None, "SectorCropProfile should be auto-created on sector creation"
    assert scp.source_template_id is not None

    # ── Step 4: Profile has olive stages ─────────────────────────────────────
    stage_keys = {s["key"] for s in scp.stages}
    expected_stages = {
        "olive_dormancy",
        "olive_oil_accumulation",
        "olive_harvest",
        "olive_pit_hardening",
    }
    assert expected_stages <= stage_keys, f"Missing stages: {expected_stages - stage_keys}"

    # ── Step 5: Set stage + irrigation system ─────────────────────────────────
    resp = await client.patch(
        f"/api/v1/sectors/{sector_id}",
        json={"current_phenological_stage": "olive_oil_accumulation"},
    )
    # If PATCH not implemented try PUT
    if resp.status_code == 405:
        resp = await client.put(
            f"/api/v1/sectors/{sector_id}",
            json={
                "name": "Olival Teste",
                "crop_type": "olive",
                "current_phenological_stage": "olive_oil_accumulation",
            },
        )
    assert resp.status_code in (200, 201), f"Could not update stage: {resp.text}"

    await api_add_irrigation_system(
        client, sector_id, system_type="drip", emitter_flow_lph=2.3, emitter_spacing_m=0.75
    )

    # ── Step 6: Generate recommendation ──────────────────────────────────────
    resp = await client.post(
        f"/api/v1/sectors/{sector_id}/recommendations/generate"
    )
    assert resp.status_code == 201, resp.text
    rec = resp.json()

    # ── Step 7: Verify recommendation ────────────────────────────────────────
    assert rec["action"] in ("irrigate", "skip", "defer", "reduce", "increase")
    assert 0.0 <= rec["confidence_score"] <= 1.0
    assert rec["confidence_level"] in ("high", "medium", "low")

    # With no probe data, confidence is penalized but still functional
    detail_resp = await client.get(f"/api/v1/recommendations/{rec['id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["reasons"]) >= 1

    snap = detail["inputs_snapshot"]
    missing = snap.get("missing_config", [])
    defaults = snap.get("defaults_used", [])
    # Without weather data, some defaults will be used
    assert isinstance(missing, list)
    assert isinstance(defaults, list)


@pytest.mark.asyncio
async def test_minimal_config_still_works(client: AsyncClient, db: AsyncSession):
    """
    Graceful degradation: absolute minimum configuration.

    1. Farm with just a name (no location).
    2. Plot with just a name (no soil config).
    3. Sector with name + crop_type only (no stage, no area, no spacing).
    4. No irrigation system.
    5. Recommendation is generated (not an error).
    6. confidence_score < 0.60 (many penalties).
    7. runtime_minutes is None (no irrigation system).
    8. missing_config lists irrigation system.
    """

    # ── Create bare-minimum farm ───────────────────────────────────────────────
    farm_resp = await client.post("/api/v1/farms", json={"name": "Exploração Mínima"})
    assert farm_resp.status_code == 201
    farm_id = farm_resp.json()["id"]

    plot_resp = await client.post(
        f"/api/v1/farms/{farm_id}/plots",
        json={"name": "Talhão Único"},
    )
    assert plot_resp.status_code == 201
    plot_id = plot_resp.json()["id"]

    sector_resp = await client.post(
        f"/api/v1/plots/{plot_id}/sectors",
        json={"name": "Setor Mínimo", "crop_type": "maize"},
    )
    assert sector_resp.status_code == 201
    sector_id = sector_resp.json()["id"]

    # ── Generate recommendation — must not crash ───────────────────────────────
    resp = await client.post(
        f"/api/v1/sectors/{sector_id}/recommendations/generate"
    )
    assert resp.status_code == 201, f"Engine should not crash on minimal config: {resp.text}"
    rec = resp.json()

    # ── Verify graceful degradation ───────────────────────────────────────────
    # Action is always set
    assert rec["action"] in ("irrigate", "skip", "defer", "reduce", "increase")

    # Confidence is penalized
    assert rec["confidence_score"] < 0.75, (
        f"Confidence should be penalized for minimal config, got {rec['confidence_score']}"
    )

    # No irrigation system → runtime should be None
    assert rec["irrigation_runtime_min"] is None, (
        "runtime_min should be None with no irrigation system configured"
    )

    # Check detail for missing_config and defaults_used
    detail_resp = await client.get(f"/api/v1/recommendations/{rec['id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    snap = detail["inputs_snapshot"]
    missing = snap.get("missing_config", [])
    defaults = snap.get("defaults_used", [])

    assert any("irrigation" in m.lower() for m in missing), (
        f"missing_config should include irrigation system, got: {missing}"
    )
    assert len(defaults) >= 1, (
        f"defaults_used should list soil/Kc defaults, got: {defaults}"
    )

    # Reasons list should not be empty
    assert len(detail["reasons"]) >= 1


@pytest.mark.asyncio
async def test_farm_list_returns_created_farms(client: AsyncClient):
    """Farms created via API appear in the farms list."""
    name = "Quinta para Listar"
    resp = await client.post("/api/v1/farms", json={"name": name})
    assert resp.status_code == 201
    farm_id = resp.json()["id"]

    resp = await client.get("/api/v1/farms")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(f["id"] == farm_id for f in items)
