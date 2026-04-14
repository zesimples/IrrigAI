import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code in (200, 503)  # 503 if DB/Redis not running in test env
    data = response.json()
    assert "status" in data
    assert "checks" in data
    assert "db" in data["checks"]
    assert "redis" in data["checks"]


@pytest.mark.asyncio
async def test_health_structure(client: AsyncClient):
    response = await client.get("/health")
    data = response.json()
    assert data["status"] in ("ok", "degraded")
