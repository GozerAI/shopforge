"""
Shopify Integration - Client and storefront management.

Provides Shopify Admin API integration for product management,
inventory tracking, and order processing.
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shopforge.core import (
    StorefrontPlatform,
    StorefrontStatus,
    InventoryStatus,
    Product,
    ProductVariant,
    Collection,
    Order,
    OrderLineItem,
    OrderStatus,
    Storefront,
)

logger = logging.getLogger(__name__)


def _parse_cost(*values) -> Optional[float]:
    """Parse cost from multiple possible sources. Returns None only if no value provided."""
    for v in values:
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


class RateLimiter:
    """Handle Shopify API rate limiting.

    Tracks the ``X-Shopify-Shop-Api-Call-Limit`` response header
    and throttles requests when the remaining bucket capacity is low.
    """

    def __init__(self, calls_per_second: float = 2.0):
        self.calls_per_second = calls_per_second
        self.last_call: float = 0
        self.bucket: int = 40  # Shopify's default bucket size
        self.bucket_max: int = 40

    def wait_if_needed(self, response_headers: Optional[Dict[str, str]] = None) -> None:
        """Wait if we're approaching rate limits."""
        if response_headers:
            limit_header = response_headers.get("X-Shopify-Shop-Api-Call-Limit", "")
            if "/" in limit_header:
                current, maximum = map(int, limit_header.split("/"))
                self.bucket = maximum - current
                self.bucket_max = maximum

        # If bucket is low, wait
        if self.bucket < 5:
            wait_time = (5 - self.bucket) / self.calls_per_second
            time.sleep(wait_time)

        # Ensure minimum time between calls
        elapsed = time.time() - self.last_call
        min_interval = 1.0 / self.calls_per_second
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        self.last_call = time.time()


# Segment-to-tag mapping for smart collection creation
SEGMENT_TAGS: Dict[str, List[str]] = {
    "pets": ["pets", "dog", "cat", "pet"],
    "fashion": ["fashion", "style", "accessory"],
    "jewelry": ["jewelry", "ring", "necklace", "bracelet"],
    "home_decor": ["home", "decor", "light", "lamp"],
    "tech": ["tech", "electronic", "smart", "charger"],
    "kitchen": ["kitchen", "cooking", "wine"],
    "health": ["health", "massage", "wellness"],
    "beauty": ["beauty", "makeup", "skincare"],
    "garden": ["garden", "outdoor", "plant"],
}


@dataclass
class ShopifyCredentials:
    """Shopify API credentials."""
    store_url: str
    access_token: str
    api_version: str = "2024-01"

    @property
    def api_base(self) -> str:
        """Get API base URL."""
        return f"https://{self.store_url}/admin/api/{self.api_version}"


class ShopifyClient:
    """
    Shopify Admin API client.

    Provides methods for interacting with Shopify's Admin API
    for product, inventory, and order management.
    """

    def __init__(self, credentials: ShopifyCredentials):
        self.credentials = credentials
        self._request_count = 0
        self._last_request: Optional[datetime] = None
        self._rate_limiter = RateLimiter()

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        _retry_count: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Make authenticated request to Shopify API with rate limiting."""
        url = f"{self.credentials.api_base}/{endpoint}"

        self._rate_limiter.wait_if_needed()

        try:
            req = urllib.request.Request(url)
            req.add_header("X-Shopify-Access-Token", self.credentials.access_token)
            req.add_header("Content-Type", "application/json")
            req.method = method

            if data:
                req.data = json.dumps(data).encode("utf-8")

            with urllib.request.urlopen(req, timeout=30) as response:
                self._request_count += 1
                self._last_request = datetime.now(timezone.utc)
                # Update rate limiter from response headers
                headers = {k: v for k, v in response.headers.items()}
                self._rate_limiter.wait_if_needed(headers)
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            if e.code == 429 and _retry_count < 3:
                # Rate limited — respect Retry-After header, max 3 retries
                retry_after = float(e.headers.get("Retry-After", "2.0"))
                logger.warning(f"Shopify rate limited, retry {_retry_count + 1}/3 after {retry_after}s")
                time.sleep(retry_after)
                return self._make_request(endpoint, method, data, _retry_count + 1)
            # Read error body for debugging
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            logger.error(
                f"Shopify API error: {method} {endpoint} → {e.code} {e.reason}"
                + (f" | {error_body}" if error_body else "")
            )
            return None
        except urllib.error.URLError as e:
            logger.error(f"Shopify connection error: {method} {endpoint} → {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Shopify request failed: {method} {endpoint} → {e}")
            return None

    # ==========================================
    # PRODUCTS
    # ==========================================

    def get_products(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        collection_id: Optional[str] = None,
    ) -> List[Product]:
        """Get products from Shopify."""
        params = [f"limit={limit}"]
        if status:
            params.append(f"status={status}")
        if collection_id:
            params.append(f"collection_id={collection_id}")

        endpoint = f"products.json?{'&'.join(params)}"
        response = self._make_request(endpoint)

        if not response:
            logger.warning("get_products returned no data — API may be unreachable")
            return []

        products = []
        for p in response.get("products", []):
            products.append(self._parse_product(p))

        return products

    def get_product(self, product_id: str) -> Optional[Product]:
        """Get a single product."""
        response = self._make_request(f"products/{product_id}.json")
        if response and "product" in response:
            return self._parse_product(response["product"])
        return None

    def create_product(self, product_data: Dict[str, Any]) -> Optional[Product]:
        """Create a new product."""
        response = self._make_request(
            "products.json",
            method="POST",
            data={"product": product_data},
        )
        if response and "product" in response:
            return self._parse_product(response["product"])
        return None

    def update_product(
        self,
        product_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Product]:
        """Update an existing product."""
        response = self._make_request(
            f"products/{product_id}.json",
            method="PUT",
            data={"product": updates},
        )
        if response and "product" in response:
            return self._parse_product(response["product"])
        return None

    def delete_product(self, product_id: str) -> bool:
        """Delete a product."""
        response = self._make_request(
            f"products/{product_id}.json",
            method="DELETE",
        )
        return response is not None

    def update_variant_price(
        self,
        variant_id: str,
        price: float,
        compare_at_price: Optional[float] = None,
    ) -> bool:
        """Update variant pricing."""
        data = {"variant": {"price": str(price)}}
        if compare_at_price:
            data["variant"]["compare_at_price"] = str(compare_at_price)

        response = self._make_request(
            f"variants/{variant_id}.json",
            method="PUT",
            data=data,
        )
        return response is not None

    def _parse_product(self, data: Dict[str, Any]) -> Product:
        """Parse Shopify product data into Product model."""
        variants = []
        for v in data.get("variants", []):
            inventory_qty = v.get("inventory_quantity", 0)
            if inventory_qty <= 0:
                inv_status = InventoryStatus.OUT_OF_STOCK
            elif inventory_qty < 10:
                inv_status = InventoryStatus.LOW_STOCK
            else:
                inv_status = InventoryStatus.IN_STOCK

            variants.append(ProductVariant(
                id=str(v.get("id", "")),
                sku=v.get("sku", ""),
                title=v.get("title", "Default"),
                price=float(v.get("price", 0)),
                compare_at_price=float(v.get("compare_at_price")) if v.get("compare_at_price") else None,
                cost=_parse_cost(v.get("inventory_item", {}).get("cost"), v.get("cost")),
                inventory_quantity=inventory_qty,
                inventory_status=inv_status,
                weight=float(v.get("weight", 0)) if v.get("weight") else None,
                weight_unit=v.get("weight_unit", "lb"),
                barcode=v.get("barcode"),
                options={
                    "option1": v.get("option1"),
                    "option2": v.get("option2"),
                    "option3": v.get("option3"),
                },
            ))

        images = [
            {"id": str(img.get("id")), "src": img.get("src"), "alt": img.get("alt")}
            for img in data.get("images", [])
        ]

        return Product(
            platform_id=str(data.get("id", "")),
            platform=StorefrontPlatform.SHOPIFY,
            title=data.get("title", ""),
            handle=data.get("handle", ""),
            description=data.get("body_html", ""),
            vendor=data.get("vendor"),
            product_type=data.get("product_type"),
            variants=variants,
            tags=data.get("tags", "").split(", ") if data.get("tags") else [],
            images=images,
            status=data.get("status", "active"),
            published=data.get("published_at") is not None,
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")) if data.get("updated_at") else None,
        )

    # ==========================================
    # COLLECTIONS
    # ==========================================

    def get_collections(self) -> List[Collection]:
        """Get custom collections."""
        response = self._make_request("custom_collections.json")
        if not response:
            logger.warning("get_collections returned no data — API may be unreachable")
            return []

        collections = []
        for c in response.get("custom_collections", []):
            collections.append(Collection(
                platform_id=str(c.get("id", "")),
                title=c.get("title", ""),
                handle=c.get("handle", ""),
                description=c.get("body_html", ""),
                collection_type="custom",
                published=c.get("published_at") is not None,
            ))
        return collections

    def get_smart_collections(self) -> List[Collection]:
        """Get smart collections."""
        response = self._make_request("smart_collections.json")
        if not response:
            logger.warning("get_smart_collections returned no data — API may be unreachable")
            return []

        collections = []
        for c in response.get("smart_collections", []):
            collections.append(Collection(
                platform_id=str(c.get("id", "")),
                title=c.get("title", ""),
                handle=c.get("handle", ""),
                description=c.get("body_html", ""),
                collection_type="smart",
                rules=c.get("rules", []),
                published=c.get("published_at") is not None,
            ))
        return collections

    # ==========================================
    # ORDERS
    # ==========================================

    def get_orders(
        self,
        status: str = "any",
        limit: int = 50,
    ) -> List[Order]:
        """Get orders."""
        response = self._make_request(f"orders.json?status={status}&limit={limit}")
        if not response:
            logger.warning("get_orders returned no data — API may be unreachable")
            return []

        orders = []
        for o in response.get("orders", []):
            orders.append(self._parse_order(o))
        return orders

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get a single order."""
        response = self._make_request(f"orders/{order_id}.json")
        if response and "order" in response:
            return self._parse_order(response["order"])
        return None

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse Shopify order data."""
        line_items = []
        for item in data.get("line_items", []):
            line_items.append(OrderLineItem(
                id=str(item.get("id", "")),
                product_id=str(item.get("product_id", "")),
                variant_id=str(item.get("variant_id", "")),
                title=item.get("title", ""),
                variant_title=item.get("variant_title", ""),
                quantity=item.get("quantity", 1),
                price=float(item.get("price", 0)),
                total=float(item.get("price", 0)) * item.get("quantity", 1),
                sku=item.get("sku"),
                fulfillment_status=item.get("fulfillment_status"),
            ))

        status_map = {
            "pending": OrderStatus.PENDING,
            "confirmed": OrderStatus.CONFIRMED,
            "fulfilled": OrderStatus.SHIPPED,
            "cancelled": OrderStatus.CANCELLED,
        }

        return Order(
            platform_id=str(data.get("id", "")),
            order_number=str(data.get("order_number", "")),
            customer_email=data.get("email"),
            customer_name=f"{data.get('customer', {}).get('first_name', '')} {data.get('customer', {}).get('last_name', '')}".strip() or None,
            line_items=line_items,
            subtotal=float(data.get("subtotal_price", 0)),
            total_tax=float(data.get("total_tax", 0)),
            total_shipping=float(data.get("total_shipping_price_set", {}).get("shop_money", {}).get("amount", 0)),
            total_discounts=float(data.get("total_discounts", 0)),
            total=float(data.get("total_price", 0)),
            currency=data.get("currency", "USD"),
            status=status_map.get(data.get("fulfillment_status", ""), OrderStatus.PENDING),
            financial_status=data.get("financial_status", "pending"),
            fulfillment_status=data.get("fulfillment_status"),
            shipping_address=data.get("shipping_address"),
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")) if data.get("created_at") else None,
        )

    # ==========================================
    # INVENTORY
    # ==========================================

    def get_inventory_levels(self, inventory_item_ids: List[str]) -> Dict[str, int]:
        """Get inventory levels for items."""
        if not inventory_item_ids:
            return {}

        ids = ",".join(inventory_item_ids[:50])  # API limit
        response = self._make_request(f"inventory_levels.json?inventory_item_ids={ids}")

        if not response:
            logger.warning("get_inventory_levels returned no data — API may be unreachable")
            return {}

        levels = {}
        for level in response.get("inventory_levels", []):
            item_id = str(level.get("inventory_item_id", ""))
            levels[item_id] = level.get("available", 0)

        return levels

    def adjust_inventory(
        self,
        inventory_item_id: str,
        location_id: str,
        adjustment: int,
    ) -> bool:
        """Adjust inventory level."""
        response = self._make_request(
            "inventory_levels/adjust.json",
            method="POST",
            data={
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "available_adjustment": adjustment,
            },
        )
        return response is not None

    # ==========================================
    # ANALYTICS
    # ==========================================

    def get_product_analytics(self, products: List[Product]) -> Dict[str, Any]:
        """Get analytics for products."""
        total_products = len(products)
        total_variants = sum(len(p.variants) for p in products)
        total_inventory = sum(p.total_inventory for p in products)
        inventory_value = sum(p.inventory_value for p in products)

        # Margin analysis
        products_with_cost = [p for p in products if p.cost is not None]
        avg_margin = (sum(p.margin for p in products_with_cost if p.margin is not None) / len(products_with_cost)) if products_with_cost else 0

        # Status counts
        in_stock = len([p for p in products if p.get_inventory_status() == InventoryStatus.IN_STOCK])
        low_stock = len([p for p in products if p.get_inventory_status() == InventoryStatus.LOW_STOCK])
        out_of_stock = len([p for p in products if p.get_inventory_status() == InventoryStatus.OUT_OF_STOCK])

        return {
            "total_products": total_products,
            "total_variants": total_variants,
            "total_inventory": total_inventory,
            "inventory_value": round(inventory_value, 2),
            "average_margin": round(avg_margin, 2),
            "products_with_cost_data": len(products_with_cost),
            "inventory_status": {
                "in_stock": in_stock,
                "low_stock": low_stock,
                "out_of_stock": out_of_stock,
            },
        }


class ShopifyStorefront:
    """
    High-level Shopify storefront manager.

    Wraps ShopifyClient with caching and business logic.
    """

    def __init__(
        self,
        storefront: Storefront,
        credentials: ShopifyCredentials,
    ):
        self.storefront = storefront
        self.client = ShopifyClient(credentials)

        # Cache
        self._products_cache: List[Product] = []
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = 300  # 5 minutes

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._cache_time:
            return False
        age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
        return age < self._cache_ttl

    async def get_products(
        self,
        use_cache: bool = True,
        limit: int = 100,
    ) -> List[Product]:
        """Get products with caching."""
        if use_cache and self._is_cache_valid():
            return self._products_cache[:limit]

        products = self.client.get_products(limit=limit)
        for p in products:
            p.storefront_key = self.storefront.key

        self._products_cache = products
        self._cache_time = datetime.now(timezone.utc)

        # Update storefront metrics
        self.storefront.product_count = len(products)
        self.storefront.last_sync = datetime.now(timezone.utc)

        return products

    async def get_analytics(self) -> Dict[str, Any]:
        """Get storefront analytics."""
        products = await self.get_products()
        analytics = self.client.get_product_analytics(products)
        analytics["storefront_key"] = self.storefront.key
        analytics["storefront_name"] = self.storefront.name
        return analytics

    async def update_price(
        self,
        product_id: str,
        variant_id: str,
        new_price: float,
        compare_at_price: Optional[float] = None,
    ) -> bool:
        """Update product variant price."""
        success = self.client.update_variant_price(variant_id, new_price, compare_at_price)
        if success:
            # Invalidate cache
            self._cache_time = None
        return success

    async def get_low_stock_products(self, threshold: int = 10) -> List[Product]:
        """Get products with low stock."""
        products = await self.get_products()
        return [
            p for p in products
            if p.total_inventory > 0 and p.total_inventory <= threshold
        ]

    async def get_out_of_stock_products(self) -> List[Product]:
        """Get products that are out of stock."""
        products = await self.get_products()
        return [p for p in products if p.total_inventory <= 0]

    async def get_products_needing_pricing(
        self,
        min_margin: float = 20.0,
    ) -> List[Product]:
        """Get products with margin below threshold."""
        products = await self.get_products()
        return [
            p for p in products
            if p.margin is not None and p.margin < min_margin
        ]

    def clear_cache(self) -> None:
        """Clear the product cache."""
        self._products_cache = []
        self._cache_time = None

    async def create_bundle(
        self,
        bundle_name: str,
        product_ids: List[str],
        discount: float = 0.85,
    ) -> Optional[Product]:
        """
        Create a product bundle with a discount.

        Args:
            bundle_name: Name for the bundle product
            product_ids: List of product platform IDs to include
            discount: Discount factor (0.85 = 15% off). Default 0.85.

        Returns:
            The created bundle Product, or None on failure
        """
        products = await self.get_products(limit=500)
        bundle_products = [p for p in products if p.platform_id in product_ids]

        if not bundle_products:
            return None

        total_price = sum(p.price for p in bundle_products)
        bundle_price = round(total_price * discount, 2)

        description_items = "".join(
            f"<li>{p.title}</li>" for p in bundle_products
        )
        bundle_data = {
            "title": bundle_name,
            "body_html": f"<p>This bundle includes:</p><ul>{description_items}</ul>",
            "vendor": "Bundle",
            "product_type": "Bundle",
            "tags": "bundle, deal, value",
            "variants": [{
                "price": str(bundle_price),
                "compare_at_price": str(total_price),
                "sku": f"BUNDLE-{bundle_name.replace(' ', '-').upper()[:30]}",
            }],
        }

        result = self.client.create_product(bundle_data)
        if result:
            self._cache_time = None  # Invalidate cache
        return result

    def create_segment_collection(
        self,
        segment: str,
    ) -> Optional[Collection]:
        """
        Create a smart collection for a product segment.

        Uses SEGMENT_TAGS mapping to create a smart collection
        with OR logic (disjunctive=True) matching any of the
        segment's tags.

        Args:
            segment: Segment key from SEGMENT_TAGS

        Returns:
            The created Collection, or None on failure
        """
        tags = SEGMENT_TAGS.get(segment)
        if not tags:
            logger.warning(f"No tag mapping for segment: {segment}")
            return None

        rules = [
            {"column": "tag", "relation": "equals", "condition": tag}
            for tag in tags
        ]

        collection_data = {
            "title": segment.replace("_", " ").title(),
            "rules": rules,
            "disjunctive": True,  # OR logic
            "published": True,
        }

        response = self.client._make_request(
            "smart_collections.json",
            method="POST",
            data={"smart_collection": collection_data},
        )

        if response and "smart_collection" in response:
            c = response["smart_collection"]
            return Collection(
                platform_id=str(c.get("id", "")),
                title=c.get("title", ""),
                handle=c.get("handle", ""),
                description=c.get("body_html", ""),
                collection_type="smart",
                rules=c.get("rules", []),
                published=c.get("published_at") is not None,
            )
        return None
