"""Tests for Shopforge service token auth and new endpoints."""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
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


class TestServiceTokenAuth:
    @pytest.mark.asyncio
    async def test_service_token_bypasses_auth(self, client):
        """Valid service token should bypass tenant auth."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.get(
                "/v1/storefronts",
                headers={"X-Service-Token": "test-secret-token"},
            )
            assert resp.status_code == 200
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original

    @pytest.mark.asyncio
    async def test_invalid_service_token_rejected(self, client):
        """Wrong service token should not bypass auth."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.get(
                "/v1/storefronts",
                headers={"X-Service-Token": "wrong-token"},
            )
            assert resp.status_code == 401
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original

    @pytest.mark.asyncio
    async def test_empty_service_token_config_disables_bypass(self, client):
        """When SHOPFORGE_SERVICE_TOKEN is empty, service token bypass is disabled."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = ""
        try:
            resp = await client.get(
                "/v1/storefronts",
                headers={"X-Service-Token": "anything"},
            )
            # Should fall through to normal auth, which fails without Bearer
            assert resp.status_code == 401
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original

    @pytest.mark.asyncio
    async def test_service_token_grants_full_entitlements(self, client):
        """Service token should grant full entitlements (analytics is shopforge:full)."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.get(
                "/v1/analytics",
                headers={"X-Service-Token": "test-secret-token"},
            )
            assert resp.status_code == 200
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original


class TestRevenueSummaryEndpoint:
    @pytest.mark.asyncio
    async def test_revenue_summary_returns_200(self, client):
        """Revenue summary endpoint should return 200 with service token."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.get(
                "/v1/revenue/summary",
                headers={"X-Service-Token": "test-secret-token"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "total_inventory_value" in data
            assert "total_products" in data
            assert "gross_margin" in data
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original


class TestProvisionEndpoint:
    @pytest.mark.asyncio
    async def test_provision_shopify_missing_fields(self, client):
        """Provision without required fields should fail."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.post(
                "/v1/storefronts/provision",
                headers={"X-Service-Token": "test-secret-token"},
                json={"key": "new_store", "platform": "shopify"},
            )
            assert resp.status_code == 400
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original

    @pytest.mark.asyncio
    async def test_provision_unsupported_platform(self, client):
        """Provision with unsupported platform should fail."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.post(
                "/v1/storefronts/provision",
                headers={"X-Service-Token": "test-secret-token"},
                json={"key": "x", "platform": "woocommerce"},
            )
            assert resp.status_code == 400
            assert "Unsupported platform" in resp.json()["detail"]
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original

    @pytest.mark.asyncio
    async def test_provision_medusa_missing_base_url(self, client):
        """Provision Medusa without base_url should fail."""
        import shopforge.app as app_module
        original = app_module.SHOPFORGE_SERVICE_TOKEN
        app_module.SHOPFORGE_SERVICE_TOKEN = "test-secret-token"
        try:
            resp = await client.post(
                "/v1/storefronts/provision",
                headers={"X-Service-Token": "test-secret-token"},
                json={"key": "med1", "platform": "medusa"},
            )
            assert resp.status_code == 400
            assert "base_url" in resp.json()["detail"]
        finally:
            app_module.SHOPFORGE_SERVICE_TOKEN = original
