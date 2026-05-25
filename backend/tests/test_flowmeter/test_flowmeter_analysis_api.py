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
