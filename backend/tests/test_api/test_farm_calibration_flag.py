"""The per-farm auto-apply opt-in flag: default, toggle, tenant isolation."""

import pytest


@pytest.mark.asyncio
async def test_flag_defaults_to_false_on_create(client):
    resp = await client.post("/api/v1/farms", json={"name": "Flag Default Farm"})
    assert resp.status_code == 201
    assert resp.json()["calibration_auto_apply"] is False


@pytest.mark.asyncio
async def test_flag_can_be_toggled_on_and_off(client):
    farm_id = (await client.post("/api/v1/farms", json={"name": "Flag Toggle Farm"})).json()["id"]

    on = await client.put(f"/api/v1/farms/{farm_id}", json={"calibration_auto_apply": True})
    assert on.status_code == 200
    assert on.json()["calibration_auto_apply"] is True

    off = await client.put(f"/api/v1/farms/{farm_id}", json={"calibration_auto_apply": False})
    assert off.status_code == 200
    assert off.json()["calibration_auto_apply"] is False


@pytest.mark.asyncio
async def test_unknown_farm_returns_404(client):
    resp = await client.put(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000",
        json={"calibration_auto_apply": True},
    )
    assert resp.status_code == 404
