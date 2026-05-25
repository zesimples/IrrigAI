# backend/tests/test_flowmeter/test_flowmeter_analysis_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_farm_analysis_unknown_farm_returns_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/flowmeter-analysis",
        json={"period_days": 7, "language": "pt"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sector_analysis_unknown_sector_returns_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/sectors/00000000-0000-0000-0000-000000000000/flowmeter-analysis",
        json={"period_days": 7, "language": "pt"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deviations_endpoint_unknown_farm_returns_404(client: AsyncClient):
    response = await client.get(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/flowmeter-deviations"
    )
    assert response.status_code == 404


from app.services.flowmeter_cache import _make_cache_key


def test_cache_key_includes_language():
    key_pt = _make_cache_key("farm", "abc123", 7, "pt")
    key_en = _make_cache_key("farm", "abc123", 7, "en")
    assert key_pt != key_en


def test_cache_key_format():
    key = _make_cache_key("sector", "xyz", 30, "pt")
    assert "sector" in key
    assert "xyz" in key
    assert "30" in key
    assert "pt" in key
