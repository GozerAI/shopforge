"""Unit tests for ShopForge FastAPI health endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from shopforge.service import CommerceService


@pytest.fixture
def service():
    return CommerceService()


@pytest.fixture
async def client(service):
    """Create test client with mocked auth."""
    import shopforge.app as app_module
    from shopforge.app import app

    original_service = app_module._service
    app_module._service = service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app_module._service = original_service


class TestHealth:

    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "shopforge"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_health_detailed(self, client):
        resp = await client.get("/health/detailed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "shopforge"
        assert "checks" in data
        assert data["checks"]["service"]["status"] == "ok"
