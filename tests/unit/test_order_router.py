"""Tests for OrderRouter."""

from unittest.mock import MagicMock

from shopforge.medusa import OrderRouter


class TestOrderRouter:
    def test_create_draft_order_success(self):
        mock_client = MagicMock()
        mock_client._make_request.return_value = {
            "draft_order": {
                "id": 12345,
                "name": "#D1001",
                "invoice_url": "https://shop.myshopify.com/inv/12345",
            }
        }

        router = OrderRouter(shopify_client=mock_client)
        result = router.create_draft_order_from_medusa({
            "source_storefront": "pet_paradise",
            "email": "customer@example.com",
            "items": [
                {"quantity": 2, "metadata": {"shopify_variant_id": "99001"}},
            ],
        })

        assert result["success"] is True
        assert result["shopify_draft_order_id"] == 12345
        assert result["source_storefront"] == "pet_paradise"

    def test_create_draft_order_no_client(self):
        router = OrderRouter()
        result = router.create_draft_order_from_medusa({
            "email": "test@test.com",
            "items": [{"metadata": {"shopify_variant_id": "123"}, "quantity": 1}],
        })
        assert "error" in result

    def test_create_draft_order_no_shopify_items(self):
        mock_client = MagicMock()
        router = OrderRouter(shopify_client=mock_client)

        result = router.create_draft_order_from_medusa({
            "email": "test@test.com",
            "items": [{"quantity": 1, "metadata": {}}],  # No shopify_variant_id
        })
        assert result == {"error": "No Shopify-linked items in order"}

    def test_handle_order_placed_webhook(self):
        mock_client = MagicMock()
        mock_client._make_request.return_value = {
            "draft_order": {"id": 54321}
        }

        router = OrderRouter(shopify_client=mock_client)
        result = router.handle_order_placed({
            "event": "order.placed",
            "data": {
                "id": "medusa-order-001",
                "email": "buyer@example.com",
                "items": [
                    {
                        "quantity": 1,
                        "variant": {
                            "metadata": {"shopify_variant_id": "77001"},
                        },
                    }
                ],
                "shipping_address": {
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "address_1": "123 Main St",
                    "city": "Portland",
                    "province": "OR",
                    "postal_code": "97201",
                    "country_code": "US",
                },
            },
        })

        assert result["success"] is True
        assert result["medusa_order_id"] == "medusa-order-001"
        assert result["shopify_draft_order_id"] == 54321

    def test_handle_wrong_event_type(self):
        mock_client = MagicMock()
        router = OrderRouter(shopify_client=mock_client)

        result = router.handle_order_placed({
            "event": "order.cancelled",
            "data": {},
        })
        assert "error" in result
