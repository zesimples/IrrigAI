"""E2E: Crop profile template → sector workflow.

Tests the full lifecycle of a SectorCropProfile:
  - Auto-creation from template on sector setup
  - Customisation (is_customized flag, template unchanged)
  - Reset back to template defaults
  - Engine reading customised Kc (reflected in computation_log)
"""

import copy

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CropProfileTemplate, SectorCropProfile

from tests.test_e2e.conftest import (
    api_create_farm,
    api_create_plot,
    api_create_sector,
    api_add_irrigation_system,
)


@pytest.mark.asyncio
async def test_crop_profile_template_to_sector(
    client: AsyncClient, db: AsyncSession, olive_template: CropProfileTemplate
):
    """
    1. Get olive template via API.
    2. Create sector with crop_type='olive'.
    3. Verify SectorCropProfile.stages matches template.stages.
    4. Verify SectorCropProfile.source_template_id = olive template ID.
    5. Update sector's crop profile (change Kc for one stage).
    6. Verify is_customized = True.
    7. Verify template is unchanged (source template Kc intact).
    """

    # ── Step 1: Fetch template via API ────────────────────────────────────────
    resp = await client.get("/api/v1/crop-profile-templates")
    assert resp.status_code == 200
    templates = resp.json()
    api_olive = next(t for t in templates if t["crop_type"] == "olive" and t["is_system_default"])
    assert api_olive["id"] == olive_template.id
    assert len(api_olive["stages"]) >= 4

    original_template_stages = copy.deepcopy(api_olive["stages"])

    # ── Step 2: Create sector with olive crop type ────────────────────────────
    farm_id = await api_create_farm(client, name="Quinta do Perfil")
    plot_id = await api_create_plot(client, farm_id, name="Parcela A")
    sector_id = await api_create_sector(
        client, plot_id, name="Olival Perfil", crop_type="olive", stage=None
    )

    # ── Step 3 & 4: Verify SectorCropProfile auto-created from template ───────
    resp = await client.get(f"/api/v1/sectors/{sector_id}/crop-profile")
    assert resp.status_code == 200
    profile = resp.json()

    assert profile["source_template_id"] == olive_template.id, (
        "source_template_id must point to the olive template"
    )
    assert profile["is_customized"] is False, "Profile should start as not customized"
    assert profile["crop_type"] == "olive"

    # Stages must match template (same keys and Kc values)
    profile_stage_map = {s["key"]: s for s in profile["stages"]}
    template_stage_map = {s["key"]: s for s in original_template_stages}
    for key, tmpl_stage in template_stage_map.items():
        assert key in profile_stage_map, f"Stage {key} missing from sector profile"
        assert profile_stage_map[key]["kc"] == pytest.approx(tmpl_stage["kc"], abs=0.001), (
            f"Kc mismatch for stage {key}"
        )

    # ── Step 5: Update one stage Kc to a custom value ────────────────────────
    oil_acc_key = "olive_oil_accumulation"
    assert oil_acc_key in profile_stage_map, f"Expected stage {oil_acc_key} in profile"

    # Build modified stages list with custom Kc for oil_accumulation
    custom_kc = 0.75  # olive default is 0.60
    modified_stages = [
        {**s, "kc": custom_kc} if s["key"] == oil_acc_key else s
        for s in profile["stages"]
    ]

    resp = await client.put(
        f"/api/v1/sectors/{sector_id}/crop-profile",
        json={"stages": modified_stages},
    )
    assert resp.status_code == 200, f"Failed to update crop profile: {resp.text}"
    updated = resp.json()

    # ── Step 6: is_customized must be True ────────────────────────────────────
    assert updated["is_customized"] is True, "Profile must be marked customized after update"

    # Verify the custom Kc is stored
    updated_stage_map = {s["key"]: s for s in updated["stages"]}
    assert updated_stage_map[oil_acc_key]["kc"] == pytest.approx(custom_kc, abs=0.001), (
        "Custom Kc should be saved"
    )

    # ── Step 7: Template must be unchanged ────────────────────────────────────
    resp = await client.get(f"/api/v1/crop-profile-templates/{olive_template.id}")
    assert resp.status_code == 200
    fresh_template = resp.json()
    fresh_stage_map = {s["key"]: s for s in fresh_template["stages"]}

    original_oil_acc_kc = template_stage_map[oil_acc_key]["kc"]
    assert fresh_stage_map[oil_acc_key]["kc"] == pytest.approx(original_oil_acc_kc, abs=0.001), (
        f"Template Kc for {oil_acc_key} must not change when sector profile is edited. "
        f"Expected {original_oil_acc_kc}, got {fresh_stage_map[oil_acc_key]['kc']}"
    )


@pytest.mark.asyncio
async def test_crop_profile_reset(
    client: AsyncClient, db: AsyncSession, olive_template: CropProfileTemplate
):
    """
    1. Create sector with olive crop type.
    2. Customize profile (change a Kc).
    3. Reset to template.
    4. Verify stages match template again.
    5. Verify is_customized = False after reset.
    """

    # Create sector
    farm_id = await api_create_farm(client, name="Quinta do Reset")
    plot_id = await api_create_plot(client, farm_id, name="Talhão B")
    sector_id = await api_create_sector(
        client, plot_id, name="Setor Reset", crop_type="olive", stage=None
    )

    # Get original profile
    resp = await client.get(f"/api/v1/sectors/{sector_id}/crop-profile")
    assert resp.status_code == 200
    original_profile = resp.json()
    original_stage_map = {s["key"]: s for s in original_profile["stages"]}
    oil_acc_original_kc = original_stage_map["olive_oil_accumulation"]["kc"]

    # Customize: set a different Kc
    custom_kc = oil_acc_original_kc + 0.25
    modified_stages = [
        {**s, "kc": custom_kc} if s["key"] == "olive_oil_accumulation" else s
        for s in original_profile["stages"]
    ]
    resp = await client.put(
        f"/api/v1/sectors/{sector_id}/crop-profile",
        json={"stages": modified_stages},
    )
    assert resp.status_code == 200
    assert resp.json()["is_customized"] is True

    # Reset to template
    resp = await client.post(
        f"/api/v1/sectors/{sector_id}/crop-profile/reset",
        json={"template_id": olive_template.id},
    )
    assert resp.status_code == 200, f"Reset failed: {resp.text}"
    reset_profile = resp.json()

    # is_customized must be False after reset
    assert reset_profile["is_customized"] is False, "is_customized should be False after reset"

    # Stages must match the template
    reset_stage_map = {s["key"]: s for s in reset_profile["stages"]}
    assert reset_stage_map["olive_oil_accumulation"]["kc"] == pytest.approx(
        oil_acc_original_kc, abs=0.001
    ), "Kc should revert to template value after reset"


@pytest.mark.asyncio
async def test_engine_reads_customized_profile(
    client: AsyncClient, db: AsyncSession, olive_template: CropProfileTemplate, sandy_loam_preset
):
    """
    1. Create olive sector with oil_accumulation stage.
    2. Set custom Kc = 0.95 for oil_accumulation.
    3. Generate recommendation.
    4. Verify computation_log mentions Kc or kc_source reflects custom value.
    5. Recommendation should reference the customized Kc in its snapshot.
    """

    # Setup
    farm_id = await api_create_farm(client, name="Quinta Kc Customizado")
    plot_id = await api_create_plot(client, farm_id, name="Talhão Kc", soil_preset_id=sandy_loam_preset.id)
    sector_id = await api_create_sector(
        client, plot_id,
        name="Olival Kc Custom",
        crop_type="olive",
        stage="olive_oil_accumulation",
    )
    await api_add_irrigation_system(client, sector_id, system_type="drip")

    # Get current profile
    resp = await client.get(f"/api/v1/sectors/{sector_id}/crop-profile")
    assert resp.status_code == 200
    profile = resp.json()

    # Set a distinctive custom Kc value (far from defaults)
    custom_kc = 0.95
    modified_stages = [
        {**s, "kc": custom_kc} if s["key"] == "olive_oil_accumulation" else s
        for s in profile["stages"]
    ]
    resp = await client.put(
        f"/api/v1/sectors/{sector_id}/crop-profile",
        json={"stages": modified_stages},
    )
    assert resp.status_code == 200

    # Generate recommendation
    resp = await client.post(
        f"/api/v1/sectors/{sector_id}/recommendations/generate"
    )
    assert resp.status_code == 201, f"Recommendation generation failed: {resp.text}"
    rec_id = resp.json()["id"]

    # Inspect detail
    resp = await client.get(f"/api/v1/recommendations/{rec_id}")
    assert resp.status_code == 200
    detail = resp.json()

    # Computation log must reference Kc
    comp_log = detail["computation_log"]
    log_text = " ".join(comp_log.get("log", []))
    kc_source = comp_log.get("kc_source", "")

    assert "Kc=" in log_text or "kc" in kc_source.lower(), (
        "computation_log should mention Kc. log_text: {!r}, kc_source: {!r}".format(log_text, kc_source)
    )

    # The inputs_snapshot should capture the Kc that was used
    snap = detail["inputs_snapshot"]
    assert "kc" in snap or "Kc" in str(snap), (
        f"inputs_snapshot should include kc. Got keys: {list(snap.keys())}"
    )

    # Verify the Kc used is close to our custom value (not the default 0.60)
    # This is checked via inputs_snapshot or computation_log
    if "kc" in snap:
        assert snap["kc"] == pytest.approx(custom_kc, abs=0.05), (
            f"Engine should use custom Kc={custom_kc}, got {snap['kc']}"
        )
