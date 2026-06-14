"""Edge-case tests for OrderRouter (Medusa → Shopify fulfillment routing)."""

from unittest.mock import MagicMock

import pytest

from shopforge.medusa import OrderRouter, NicheStorefront, MedusaStorefront
from shopforge.core import Product, ProductVariant, InventoryStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_shopify_client(draft_order_response=None, fail=False):
    """Return a mock ShopifyClient with configurable _make_request."""
    client = MagicMock()
    if fail:
        client._make_request.return_value = None
    else:
        response = draft_order_response or {
            "draft_order": {
                "id": 99999,
                "name": "#D2001",
                "invoice_url": "https://shop.myshopify.com/inv/99999",
            }
        }
        client._make_request.return_value = response
    return client


def _order_data(items, email="test@example.com", source="pet_paradise", shipping=None):
    """Build minimal order_data dict for create_draft_order_from_medusa."""
    data = {
        "source_storefront": source,
        "email": email,
        "items": items,
    }
    if shipping:
        data["shipping_address"] = shipping
    return data


def _webhook_payload(items, order_id="medusa-001", email="buyer@example.com",
                     shipping=None, event="order.placed"):
    """Build minimal Medusa webhook payload."""
    payload = {
        "event": event,
        "data": {
            "id": order_id,
            "email": email,
            "items": items,
        },
    }
    if shipping:
        payload["data"]["shipping_address"] = shipping
    return payload


# ---------------------------------------------------------------------------
# Tests — create_draft_order_from_medusa
# ---------------------------------------------------------------------------

class TestOrderRoutingSingleCenter:
    """Routing with a single fulfillment center (Shopify hub)."""

    def test_single_item_routes_successfully(self):
        router = OrderRouter(shopify_client=_mock_shopify_client())
        result = router.create_draft_order_from_medusa(
            _order_data([{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}])
        )
        assert result["success"] is True
        assert result["shopify_draft_order_id"] == 99999

    def test_single_item_tags_include_source(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        router.create_draft_order_from_medusa(
            _order_data(
                [{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}],
                source="tech_hub",
            )
        )
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        assert "tech_hub" in call_data["tags"]

    def test_email_forwarded_to_shopify(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        router.create_draft_order_from_medusa(
            _order_data(
                [{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}],
                email="vip@example.com",
            )
        )
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        assert call_data["email"] == "vip@example.com"


class TestOrderRoutingMultipleItems:
    """Routing orders with multiple items."""

    def test_multiple_items_all_routed(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [
            {"quantity": 2, "metadata": {"shopify_variant_id": "100"}},
            {"quantity": 1, "metadata": {"shopify_variant_id": "200"}},
        ]
        result = router.create_draft_order_from_medusa(_order_data(items))
        assert result["success"] is True
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        assert len(call_data["line_items"]) == 2

    def test_quantities_preserved(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [
            {"quantity": 5, "metadata": {"shopify_variant_id": "100"}},
            {"quantity": 3, "metadata": {"shopify_variant_id": "200"}},
        ]
        router.create_draft_order_from_medusa(_order_data(items))
        line_items = client._make_request.call_args[1]["data"]["draft_order"]["line_items"]
        assert line_items[0]["quantity"] == 5
        assert line_items[1]["quantity"] == 3


class TestSplitOrderRouting:
    """Partial routing when only some items have Shopify IDs."""

    def test_only_shopify_linked_items_included(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [
            {"quantity": 1, "metadata": {"shopify_variant_id": "100"}},
            {"quantity": 1, "metadata": {}},  # No Shopify variant
        ]
        result = router.create_draft_order_from_medusa(_order_data(items))
        assert result["success"] is True
        line_items = client._make_request.call_args[1]["data"]["draft_order"]["line_items"]
        assert len(line_items) == 1

    def test_all_items_without_shopify_id_returns_error(self):
        router = OrderRouter(shopify_client=_mock_shopify_client())
        items = [
            {"quantity": 1, "metadata": {}},
            {"quantity": 2, "metadata": {"other_field": "abc"}},
        ]
        result = router.create_draft_order_from_medusa(_order_data(items))
        assert "error" in result
        assert "No Shopify-linked" in result["error"]


class TestOutOfStockRoutingFallback:
    """Routing behaviour when Shopify API rejects the draft order."""

    def test_shopify_api_failure_returns_error(self):
        router = OrderRouter(shopify_client=_mock_shopify_client(fail=True))
        items = [{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}]
        result = router.create_draft_order_from_medusa(_order_data(items))
        assert "error" in result
        assert "Failed" in result["error"]


class TestInternationalOrderRouting:
    """Routing with international shipping addresses."""

    def test_shipping_address_forwarded(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        shipping = {
            "first_name": "Hans",
            "last_name": "Mueller",
            "address_1": "Hauptstr. 5",
            "city": "Berlin",
            "province": "Berlin",
            "postal_code": "10115",
            "country_code": "DE",
        }
        items = [{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}]
        router.create_draft_order_from_medusa(_order_data(items, shipping=shipping))
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        assert call_data["shipping_address"] == shipping

    def test_no_shipping_address_omits_key(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}]
        router.create_draft_order_from_medusa(_order_data(items))
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        assert "shipping_address" not in call_data


class TestOrderPriorityHandling:
    """Routing preserves note metadata for priority tracking."""

    def test_note_includes_source_storefront(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [{"quantity": 1, "metadata": {"shopify_variant_id": "100"}}]
        router.create_draft_order_from_medusa(_order_data(items, source="glow_go"))
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        assert "glow_go" in call_data["note"]


# ---------------------------------------------------------------------------
# Tests — handle_order_placed (webhook)
# ---------------------------------------------------------------------------

class TestWebhookOrderRouting:
    """Tests for the webhook handler path."""

    def test_webhook_extracts_variant_from_nested_metadata(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [
            {
                "quantity": 2,
                "variant": {"metadata": {"shopify_variant_id": "500"}},
            }
        ]
        result = router.handle_order_placed(_webhook_payload(items))
        assert result["success"] is True
        line_items = client._make_request.call_args[1]["data"]["draft_order"]["line_items"]
        assert line_items[0]["variant_id"] == 500
        assert line_items[0]["quantity"] == 2

    def test_webhook_maps_shipping_address_to_shopify_format(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        shipping = {
            "first_name": "Jane",
            "last_name": "Doe",
            "address_1": "456 Oak Ave",
            "city": "Portland",
            "province": "OR",
            "postal_code": "97201",
            "country_code": "US",
        }
        items = [{"quantity": 1, "variant": {"metadata": {"shopify_variant_id": "500"}}}]
        router.handle_order_placed(_webhook_payload(items, shipping=shipping))
        call_data = client._make_request.call_args[1]["data"]["draft_order"]
        sa = call_data["shipping_address"]
        # Medusa uses address_1, Shopify uses address1
        assert sa["address1"] == "456 Oak Ave"
        assert sa["zip"] == "97201"
        assert sa["country"] == "US"

    def test_webhook_wrong_event_type_returns_error(self):
        router = OrderRouter(shopify_client=_mock_shopify_client())
        result = router.handle_order_placed(
            _webhook_payload([], event="order.cancelled")
        )
        assert "error" in result
        assert "Unexpected event" in result["error"]

    def test_webhook_no_shopify_client_returns_error(self):
        router = OrderRouter()
        result = router.handle_order_placed(_webhook_payload([]))
        assert "error" in result

    def test_webhook_no_shopify_linked_items(self):
        router = OrderRouter(shopify_client=_mock_shopify_client())
        items = [{"quantity": 1, "variant": {"metadata": {}}}]
        result = router.handle_order_placed(_webhook_payload(items))
        assert "error" in result

    def test_webhook_api_failure(self):
        router = OrderRouter(shopify_client=_mock_shopify_client(fail=True))
        items = [{"quantity": 1, "variant": {"metadata": {"shopify_variant_id": "500"}}}]
        result = router.handle_order_placed(_webhook_payload(items))
        assert "error" in result

    def test_webhook_returns_medusa_order_id(self):
        client = _mock_shopify_client()
        router = OrderRouter(shopify_client=client)
        items = [{"quantity": 1, "variant": {"metadata": {"shopify_variant_id": "500"}}}]
        result = router.handle_order_placed(
            _webhook_payload(items, order_id="medusa-xyz")
        )
        assert result["medusa_order_id"] == "medusa-xyz"


class TestNicheStorefrontProductMatching:
    """NicheStorefront.matches_product edge cases relevant to routing."""

    def test_product_matches_by_tag(self):
        sf = NicheStorefront(
            key="pet_paradise", name="Pet Paradise",
            description="Pets", url="pets.example.com",
            segments=["pets"],
            product_filters={"tags": ["pets", "dogs"]},
        )
        product = Product(
            title="Dog Toy", product_type="Other",
            tags=["pets", "fun"],
        )
        assert sf.matches_product(product) is True

    def test_product_no_matching_tag(self):
        sf = NicheStorefront(
            key="pet_paradise", name="Pet Paradise",
            description="Pets", url="pets.example.com",
            segments=["pets"],
            product_filters={"tags": ["pets", "dogs"]},
        )
        product = Product(title="Laptop", product_type="Electronics", tags=["tech"])
        assert sf.matches_product(product) is False

    def test_product_matches_by_product_type_partial(self):
        sf = NicheStorefront(
            key="tech_hub", name="Tech Hub",
            description="Tech", url="tech.example.com",
            segments=["tech"],
            product_filters={"product_types": ["Electronics"], "tags": ["tech"]},
        )
        product = Product(
            title="Phone", product_type="Electronics",
            tags=["tech"],
        )
        assert sf.matches_product(product) is True

    def test_empty_items_list(self):
        """Order with empty items list returns error."""
        router = OrderRouter(shopify_client=_mock_shopify_client())
        result = router.create_draft_order_from_medusa(
            _order_data([], source="pet_paradise")
        )
        assert "error" in result
