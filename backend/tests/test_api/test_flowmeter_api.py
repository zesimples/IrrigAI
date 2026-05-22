# backend/tests/test_api/test_flowmeter_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_flowmeter_returns_404_for_unknown_sector(client: AsyncClient):
    resp = await client.get("/api/v1/sectors/00000000-0000-0000-0000-000000000000/flowmeter")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_flowmeter_readings_returns_404_for_unknown_sector(client: AsyncClient):
    resp = await client.get(
        "/api/v1/sectors/00000000-0000-0000-0000-000000000000/flowmeter/readings"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_flowmeter_events_returns_404_for_unknown_sector(client: AsyncClient):
    resp = await client.get(
        "/api/v1/sectors/00000000-0000-0000-0000-000000000000/flowmeter/events"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_flowmeter_dashboard_returns_404_for_unknown_farm(client: AsyncClient):
    resp = await client.get(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/flowmeter-dashboard"
    )
    assert resp.status_code == 404
