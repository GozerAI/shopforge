"""Tests for CommerceService."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from shopforge.medusa import MedusaClient, MedusaCredentials, MedusaStorefront
from shopforge.shopify import ShopifyClient
from shopforge.core import Product, ProductVariant


class TestCommerceService:
    """Tests for the CommerceService."""

    @pytest.fixture
    def commerce_service(self):
        """Create a CommerceService instance."""
        from shopforge import CommerceService
        return CommerceService()

    def test_service_initialization(self, commerce_service):
        """Verify service initializes correctly."""
        assert commerce_service is not None
        assert hasattr(commerce_service, "_registry")

    def test_list_storefronts(self, commerce_service):
        """List storefronts returns expected structure."""
        result = commerce_service.list_storefronts()
        # Returns list of storefront dicts directly
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_executive_report_crevo(self, commerce_service):
        """CRO report (CRevO not implemented, uses CRO)."""
        report = await commerce_service.get_executive_report("CRO")
        assert report["executive"] == "CRO"
        assert "focus" in report

    @pytest.mark.asyncio
    async def test_get_executive_report_cfo(self, commerce_service):
        """CFO report has financial focus."""
        report = await commerce_service.get_executive_report("CFO")
        assert report["executive"] == "CFO"
        assert report["focus"] == "Financial Metrics"

    @pytest.mark.asyncio
    async def test_get_margin_analysis(self, commerce_service):
        """Get margin analysis returns expected structure."""
        result = await commerce_service.get_margin_analysis()
        assert isinstance(result, dict)

    def test_get_low_stock_alerts(self, commerce_service):
        """Get low stock alerts."""
        result = commerce_service.get_low_stock_alerts(threshold=10)
        assert isinstance(result, dict)

    def test_get_stats(self, commerce_service):
        """Get service stats."""
        stats = commerce_service.get_stats()
        assert isinstance(stats, dict)

    def test_get_telemetry_returns_dict(self, commerce_service):
        """get_telemetry always returns a dict (empty if lib not installed)."""
        result = commerce_service.get_telemetry()
        assert isinstance(result, dict)

    def test_get_telemetry_graceful_without_lib(self, commerce_service):
        """Without gozerai-telemetry installed, get_telemetry returns {}."""
        import shopforge.service as svc
        original = svc._HAS_TELEMETRY
        try:
            svc._HAS_TELEMETRY = False
            result = commerce_service.get_telemetry()
            assert result == {}
        finally:
            svc._HAS_TELEMETRY = original

    @pytest.mark.asyncio
    async def test_get_products_unknown_storefront(self, commerce_service):
        """get_products raises KeyError for unknown storefront."""
        with pytest.raises(KeyError, match="not found"):
            await commerce_service.get_products("nonexistent_store")

    def test_order_routing_no_shopify_connected(self, commerce_service):
        """Order routing returns error when no Shopify storefront is connected."""
        result = commerce_service.create_draft_order_from_medusa({
            "email": "test@example.com",
            "items": [{"metadata": {"shopify_variant_id": "123"}, "quantity": 1}],
        })
        assert "error" in result
        assert "No Shopify" in result["error"]

    def test_webhook_no_shopify_connected(self, commerce_service):
        """Webhook handling returns error when no Shopify connected."""
        result = commerce_service.handle_medusa_order_webhook({
            "event": "order.placed",
            "data": {"id": "test", "items": []},
        })
        assert "error" in result
        assert "No Shopify" in result["error"]


class TestMedusaClient:
    """Tests for MedusaClient error handling."""

    def test_get_products_api_error_has_error_key(self):
        """get_products includes api_error key on failure."""
        creds = MedusaCredentials(base_url="http://invalid-host:9999")
        client = MedusaClient(creds)
        result = client.get_products()
        assert "api_error" in result
        assert result["products"] == []
        assert result["count"] == 0

    def test_get_regions_returns_error_tuple(self):
        """get_regions returns error string on failure."""
        creds = MedusaCredentials(base_url="http://invalid-host:9999")
        client = MedusaClient(creds)
        regions, error = client.get_regions()
        assert regions == []
        assert error is not None

    def test_get_orders_returns_error_tuple(self):
        """get_orders returns error string on failure."""
        creds = MedusaCredentials(base_url="http://invalid-host:9999")
        client = MedusaClient(creds)
        orders, error = client.get_orders()
        assert orders == []
        assert error is not None

    def test_health_check_returns_false_on_failure(self):
        """health_check returns False when Medusa is unreachable."""
        creds = MedusaCredentials(base_url="http://invalid-host:9999")
        client = MedusaClient(creds)
        assert client.health_check() is False


class TestMedusaSyncValidation:
    """Tests for Medusa sync pre-flight validation."""

    @pytest.fixture
    def medusa_storefront(self):
        return MedusaStorefront()

    @pytest.mark.asyncio
    async def test_sync_no_client(self, medusa_storefront):
        """Sync returns error when no client configured."""
        result = await medusa_storefront.sync_products_to_medusa([], "pet_paradise")
        assert result["error"] == "Medusa client not configured"

    @pytest.mark.asyncio
    async def test_sync_unknown_storefront(self):
        """Sync returns error for unknown storefront."""
        creds = MedusaCredentials(base_url="http://localhost:9999")
        sf = MedusaStorefront(creds)
        result = await sf.sync_products_to_medusa([], "nonexistent")
        assert "Unknown storefront" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_unreachable_aborts(self):
        """Sync aborts with error when Medusa is unreachable."""
        creds = MedusaCredentials(base_url="http://invalid-host:9999")
        sf = MedusaStorefront(creds)
        products = [
            Product(
                id="p1", title="Test", handle="test",
                variants=[ProductVariant(id="v1", title="Default", price=10.0)],
                product_type="Pet Supplies", tags=["pets"],
            ),
        ]
        result = await sf.sync_products_to_medusa(products, "pet_paradise")
        assert "unreachable" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_no_matching_products(self):
        """Sync returns warning when no products match filters."""
        creds = MedusaCredentials(base_url="http://localhost:9999")
        sf = MedusaStorefront(creds)
        # Mock health_check to pass
        sf.client.health_check = lambda: True
        products = [
            Product(
                id="p1", title="Unrelated", handle="unrelated",
                variants=[ProductVariant(id="v1", title="Default", price=10.0)],
                product_type="Random", tags=["nothing"],
            ),
        ]
        result = await sf.sync_products_to_medusa(products, "pet_paradise")
        assert result["products_filtered"] == 0
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_sync_invalid_price_skipped(self):
        """Products with zero/negative price are skipped with error detail."""
        creds = MedusaCredentials(base_url="http://localhost:9999")
        sf = MedusaStorefront(creds)
        sf.client.health_check = lambda: True
        products = [
            Product(
                id="p1", title="Free Item", handle="free",
                variants=[ProductVariant(id="v1", title="Default", price=0.0)],
                product_type="Pet Supplies", tags=["pets"],
            ),
        ]
        result = await sf.sync_products_to_medusa(products, "pet_paradise")
        assert result["errors"] == 1
        assert "error_details" in result
        assert "invalid price" in result["error_details"][0]


class TestProductAnalyticsMargin:
    """Tests for get_product_analytics margin calculation."""

    def test_zero_margin_included_in_average(self):
        """Products with 0% margin should be included in average, not excluded."""
        from shopforge.shopify import ShopifyClient, ShopifyCredentials
        creds = ShopifyCredentials(
            store_url="test.myshopify.com",
            access_token="shpat_test",
        )
        client = ShopifyClient(creds)
        products = [
            Product(
                id="p1", title="High Margin", handle="high",
                variants=[ProductVariant(id="v1", title="Default", price=100.0,
                                        cost=50.0, inventory_quantity=10)],
            ),
            Product(
                id="p2", title="Zero Margin", handle="zero",
                variants=[ProductVariant(id="v2", title="Default", price=50.0,
                                        cost=50.0, inventory_quantity=10)],
            ),
        ]
        analytics = client.get_product_analytics(products)
        # Product 1: margin = (100-50)/100 = 50%, Product 2: margin = (50-50)/50 = 0%
        # Average should be 25%, not 50%
        assert analytics["average_margin"] == 25.0
        assert analytics["products_with_cost_data"] == 2
