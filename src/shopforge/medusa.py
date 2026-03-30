"""
Medusa Integration - Multi-storefront niche commerce.

Provides Medusa backend integration for managing multiple niche
storefronts connected to a central Shopify fulfillment hub.

Architecture:
- Shopify (Cirrus1) = Source of truth, Zendrop fulfillment hub
- 8+ Medusa storefronts = Niche customer-facing stores (hardcoded + dynamic)
"""

import json
import logging
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shopforge.core import (
    StorefrontPlatform,
    StorefrontStatus,
    InventoryStatus,
    Product,
    ProductVariant,
    Storefront,
)

logger = logging.getLogger(__name__)


# Niche storefront definitions — production storefronts
NICHE_STOREFRONTS = {
    "pet_paradise": {
        "name": "Pet Paradise",
        "description": "Everything for dog and cat lovers",
        "url": "pet-paradise.gozerai.com",
        "segments": ["pets", "animals"],
        "product_filters": {
            "product_types": ["Pet Supplies"],
            "tags": ["pets", "dogs", "cats", "pet"],
        },
        "theme": "warm",
        "target_audience": "Pet owners, animal lovers",
    },
    "glow_go": {
        "name": "Glow & Go Beauty",
        "description": "Skincare, makeup, and beauty tools",
        "url": "glow-go.gozerai.com",
        "segments": ["beauty", "skincare"],
        "product_filters": {
            "product_types": ["Beauty"],
            "tags": ["beauty", "makeup", "skincare"],
        },
        "theme": "elegant",
        "target_audience": "Beauty enthusiasts, skincare lovers",
    },
    "kitchen_essentials": {
        "name": "Kitchen Essentials",
        "description": "Smart kitchen gadgets and wine accessories",
        "url": "kitchen-essentials.gozerai.com",
        "segments": ["kitchen", "cooking"],
        "product_filters": {
            "product_types": ["Kitchen"],
            "tags": ["kitchen", "wine", "cooking"],
        },
        "theme": "clean",
        "target_audience": "Home cooks, wine enthusiasts, hosts",
    },
    "tech_hub": {
        "name": "Tech & Gadgets Hub",
        "description": "Wireless chargers, phone accessories, smart devices",
        "url": "tech-hub.gozerai.com",
        "segments": ["technology", "electronics", "gadgets"],
        "product_filters": {
            "product_types": ["Electronics"],
            "tags": ["tech", "trendy gadgets", "electronics"],
        },
        "theme": "modern",
        "target_audience": "Tech enthusiasts, gadget lovers",
    },
    "wellness_hub": {
        "name": "Wellness & Recovery",
        "description": "Massage tools, fitness recovery, self-care",
        "url": "wellness-hub.gozerai.com",
        "segments": ["health", "wellness", "fitness"],
        "product_filters": {
            "product_types": ["Health & Wellness"],
            "tags": ["health", "massage", "wellness", "fitness"],
        },
        "theme": "calm",
        "target_audience": "Fitness enthusiasts, self-care focused",
    },
    "style_shop": {
        "name": "Style & Accessories",
        "description": "Jewelry, watches, fashion accessories",
        "url": "style-shop.gozerai.com",
        "segments": ["fashion", "accessories", "lifestyle"],
        "product_filters": {
            "product_types": ["Fashion"],
            "tags": ["fashion", "jewelry", "men's fashion", "stylish"],
        },
        "theme": "luxe",
        "target_audience": "Fashion-conscious shoppers",
    },
    "home_garden": {
        "name": "Home & Garden",
        "description": "Decor, lighting, garden tools, organization",
        "url": "home-garden.gozerai.com",
        "segments": ["home", "garden", "decor"],
        "product_filters": {
            "product_types": ["Home & Garden"],
            "tags": ["home_decor", "garden", "lighting"],
        },
        "theme": "natural",
        "target_audience": "Homeowners, decor enthusiasts",
    },
    "daily_deals": {
        "name": "Daily Deals & Bundles",
        "description": "Best sellers, trending items, value bundles",
        "url": "daily-deals.gozerai.com",
        "segments": ["deals", "bundles", "trending"],
        "product_filters": {
            "product_types": ["Bundle"],
            "tags": ["best sellers", "trending deals", "bundle", "deal", "value"],
        },
        "theme": "energetic",
        "target_audience": "Deal hunters, value shoppers",
    },
}


@dataclass
class MedusaCredentials:
    """Medusa API credentials."""
    base_url: str
    api_key: Optional[str] = None
    jwt_token: Optional[str] = None


class MedusaClient:
    """
    Medusa API client.

    Provides methods for interacting with Medusa backend.
    """

    def __init__(self, credentials: MedusaCredentials):
        self.credentials = credentials
        self._request_count = 0

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Make request to Medusa API.

        Returns:
            Tuple of (response_data, error_message). On success error is None.
            On failure response_data is None and error contains details.
        """
        url = f"{self.credentials.base_url}/{endpoint}"

        try:
            req = urllib.request.Request(url)
            req.add_header("Content-Type", "application/json")

            if self.credentials.api_key:
                req.add_header("x-medusa-access-token", self.credentials.api_key)
            if self.credentials.jwt_token:
                req.add_header("Authorization", f"Bearer {self.credentials.jwt_token}")

            req.method = method

            if data:
                req.data = json.dumps(data).encode("utf-8")

            with urllib.request.urlopen(req, timeout=30) as response:
                self._request_count += 1
                return json.loads(response.read().decode("utf-8")), None

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            msg = f"Medusa API error on {method} {endpoint}: {e.code} - {e.reason}"
            if error_body:
                msg += f" | body: {error_body}"
            logger.error(msg)
            return None, msg
        except urllib.error.URLError as e:
            msg = f"Medusa unreachable on {method} {endpoint}: {e.reason}"
            logger.error(msg)
            return None, msg
        except Exception as e:
            msg = f"Medusa request failed on {method} {endpoint}: {e}"
            logger.error(msg)
            return None, msg

    def get_products(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Get products from Medusa.

        Returns:
            Dict with 'products' and 'count' keys. If the API call fails,
            includes an 'api_error' key so callers can distinguish from an
            empty catalog.
        """
        response, error = self._make_request(f"admin/products?limit={limit}&offset={offset}")
        if error:
            return {"products": [], "count": 0, "api_error": error}
        return response or {"products": [], "count": 0}

    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Get a single product."""
        response, error = self._make_request(f"admin/products/{product_id}")
        return response.get("product") if response else None

    def create_product(self, product_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a product in Medusa."""
        response, error = self._make_request(
            "admin/products",
            method="POST",
            data=product_data,
        )
        return response.get("product") if response else None

    def update_product(
        self,
        product_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update a product."""
        response, error = self._make_request(
            f"admin/products/{product_id}",
            method="POST",
            data=updates,
        )
        return response.get("product") if response else None

    def get_regions(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Get available regions.

        Returns:
            Tuple of (regions_list, error_message).
        """
        response, error = self._make_request("admin/regions")
        if error:
            return [], error
        return (response.get("regions", []) if response else []), None

    def get_orders(self, limit: int = 50) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Get orders.

        Returns:
            Tuple of (orders_list, error_message).
        """
        response, error = self._make_request(f"admin/orders?limit={limit}")
        if error:
            return [], error
        return (response.get("orders", []) if response else []), None

    def health_check(self) -> bool:
        """Check if Medusa is healthy."""
        response, error = self._make_request("health")
        return response is not None


@dataclass
class NicheStorefront:
    """
    Represents a niche storefront in the Medusa ecosystem.

    Each niche storefront filters products from the master Shopify
    catalog based on specific criteria.
    """
    key: str
    name: str
    description: str
    url: str
    segments: List[str] = field(default_factory=list)
    product_filters: Dict[str, Any] = field(default_factory=dict)
    status: StorefrontStatus = StorefrontStatus.ACTIVE

    # Metrics
    product_count: int = 0
    order_count: int = 0
    revenue: float = 0.0

    # Pricing
    markup_percentage: float = 0.0  # Additional markup for this storefront
    pricing_strategy: str = "competitive"

    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches_product(self, product: Product) -> bool:
        """Check if a product matches this storefront's filters."""
        # Check product type
        if "product_types" in self.product_filters:
            if product.product_type not in self.product_filters["product_types"]:
                # Also check partial match
                if not any(
                    pt.lower() in (product.product_type or "").lower()
                    for pt in self.product_filters["product_types"]
                ):
                    return False

        # Check tags
        if "tags" in self.product_filters:
            product_tags = set(t.lower() for t in product.tags)
            filter_tags = set(t.lower() for t in self.product_filters["tags"])
            if not product_tags & filter_tags:
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "segments": self.segments,
            "status": self.status.value,
            "product_count": self.product_count,
            "order_count": self.order_count,
            "revenue": self.revenue,
            "markup_percentage": self.markup_percentage,
        }


class MedusaStorefront:
    """
    High-level Medusa storefront manager.

    Manages niche storefronts and product synchronization
    with the master Shopify catalog. Supports both hardcoded
    niche storefronts and dynamically provisioned ones.
    """

    # Default path for persisted dynamic storefronts
    _DEFAULT_DATA_DIR = Path(__file__).parent / "data"

    def __init__(
        self,
        credentials: Optional[MedusaCredentials] = None,
        data_dir: Optional[Path] = None,
    ):
        self.client = MedusaClient(credentials) if credentials else None
        self._niche_storefronts: Dict[str, NicheStorefront] = {}
        self._dynamic_keys: set = set()  # track which keys are dynamic
        self._data_dir = data_dir or self._DEFAULT_DATA_DIR
        self._storefronts_file = self._data_dir / "storefronts.json"
        self._init_niche_storefronts()
        self._load_dynamic_storefronts()

    def _init_niche_storefronts(self) -> None:
        """Initialize niche storefront definitions."""
        for key, config in NICHE_STOREFRONTS.items():
            self._niche_storefronts[key] = NicheStorefront(
                key=key,
                name=config["name"],
                description=config["description"],
                url=config["url"],
                segments=config["segments"],
                product_filters=config["product_filters"],
            )

    def _load_dynamic_storefronts(self) -> None:
        """Load dynamically registered storefronts from JSON persistence."""
        if not self._storefronts_file.exists():
            return
        try:
            with open(self._storefronts_file, "r") as f:
                data = json.load(f)
            for key, config in data.items():
                if key in self._niche_storefronts and key not in self._dynamic_keys:
                    continue
                sf = NicheStorefront(
                    key=key,
                    name=config["name"],
                    description=config.get("description", ""),
                    url=config.get("url", ""),
                    segments=config.get("segments", []),
                    product_filters=config.get("product_filters", {}),
                    markup_percentage=config.get("markup_percentage", 0.0),
                    metadata=config.get("metadata", {}),
                )
                self._niche_storefronts[key] = sf
                self._dynamic_keys.add(key)
            logger.info(
                "Loaded %d dynamic storefronts from %s",
                len(data),
                self._storefronts_file,
            )
        except Exception as e:
            logger.error("Failed to load dynamic storefronts: %s", e)

    def _save_dynamic_storefronts(self) -> None:
        """Persist dynamic storefronts to JSON file."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        dynamic = {}
        for key in self._dynamic_keys:
            sf = self._niche_storefronts.get(key)
            if sf is None:
                continue
            dynamic[key] = {
                "name": sf.name,
                "description": sf.description,
                "url": sf.url,
                "segments": sf.segments,
                "product_filters": sf.product_filters,
                "markup_percentage": sf.markup_percentage,
                "metadata": sf.metadata,
            }
        try:
            with open(self._storefronts_file, "w") as f:
                json.dump(dynamic, f, indent=2)
        except Exception as e:
            logger.error("Failed to save dynamic storefronts: %s", e)

    @staticmethod
    def _slugify(name: str) -> str:
        """Generate a slug key from a storefront name."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        slug = slug.strip("_")
        return slug

    def register_dynamic_storefront(self, config: dict) -> NicheStorefront:
        """Register a new dynamic storefront from config.

        Args:
            config: Dict with keys: name (required), description, url, segments,
                    product_types, tags, theme, target_audience, markup_percentage

        Returns:
            The created NicheStorefront.

        Raises:
            ValueError: If name is missing or a storefront with this key already exists.
        """
        name = config.get("name", "").strip()
        if not name:
            raise ValueError("Storefront name is required")

        key = self._slugify(name)
        if not key:
            raise ValueError(
                "Storefront name must contain at least one alphanumeric character"
            )

        if key in self._niche_storefronts:
            raise ValueError(f"Storefront with key '{key}' already exists")

        product_filters: Dict[str, Any] = {}
        if config.get("product_types"):
            product_filters["product_types"] = config["product_types"]
        if config.get("tags"):
            product_filters["tags"] = config["tags"]

        metadata: Dict[str, Any] = {
            "dynamic": True,
            "theme": config.get("theme", "default"),
            "target_audience": config.get("target_audience", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        sf = NicheStorefront(
            key=key,
            name=name,
            description=config.get("description", ""),
            url=config.get("url", f"{key}.gozerai.com"),
            segments=config.get("segments", []),
            product_filters=product_filters,
            markup_percentage=config.get("markup_percentage", 0.0),
            metadata=metadata,
        )

        self._niche_storefronts[key] = sf
        self._dynamic_keys.add(key)
        self._save_dynamic_storefronts()

        logger.info("Registered dynamic storefront: %s (%s)", key, name)
        return sf

    def list_all_storefronts(self) -> List[NicheStorefront]:
        """List all storefronts (hardcoded + dynamic)."""
        return list(self._niche_storefronts.values())

    def list_dynamic_storefronts(self) -> List[NicheStorefront]:
        """List only dynamically registered storefronts."""
        return [
            self._niche_storefronts[key]
            for key in self._dynamic_keys
            if key in self._niche_storefronts
        ]



    def get_niche_storefront(self, key: str) -> Optional[NicheStorefront]:
        """Get a niche storefront by key."""
        return self._niche_storefronts.get(key)

    def list_niche_storefronts(self) -> List[NicheStorefront]:
        """List all niche storefronts."""
        return list(self._niche_storefronts.values())

    def filter_products_for_storefront(
        self,
        storefront_key: str,
        products: List[Product],
    ) -> List[Product]:
        """Filter products for a specific niche storefront."""
        storefront = self._niche_storefronts.get(storefront_key)
        if not storefront:
            return []

        matching = [p for p in products if storefront.matches_product(p)]
        storefront.product_count = len(matching)
        return matching

    def get_storefront_product_summary(
        self,
        products: List[Product],
    ) -> Dict[str, Dict[str, Any]]:
        """Get product summary for all niche storefronts."""
        summary = {}

        for key, storefront in self._niche_storefronts.items():
            matching = self.filter_products_for_storefront(key, products)

            summary[key] = {
                "name": storefront.name,
                "product_count": len(matching),
                "segments": storefront.segments,
                "sample_products": [
                    {"title": p.title, "price": p.price}
                    for p in matching[:3]
                ],
            }

        return summary

    async def sync_products_to_medusa(
        self,
        products: List[Product],
        storefront_key: str,
    ) -> Dict[str, Any]:
        """
        Sync products to a Medusa storefront.

        Args:
            products: Products to sync
            storefront_key: Target niche storefront

        Returns:
            Sync results
        """
        if not self.client:
            return {"error": "Medusa client not configured"}

        storefront = self._niche_storefronts.get(storefront_key)
        if not storefront:
            return {"error": f"Unknown storefront: {storefront_key}"}

        # Pre-flight: verify Medusa is reachable
        if not self.client.health_check():
            return {"error": "Medusa backend unreachable — sync aborted"}

        # Filter products for this storefront
        filtered = self.filter_products_for_storefront(storefront_key, products)

        if not filtered:
            return {
                "storefront": storefront_key,
                "products_filtered": 0,
                "products_synced": 0,
                "errors": 0,
                "warning": "No products matched this storefront's filters",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }

        synced = 0
        errors = 0
        error_details: List[str] = []

        for product in filtered:
            # Apply storefront markup
            adjusted_price = product.price * (1 + storefront.markup_percentage / 100)

            # Validate price is positive
            if adjusted_price <= 0:
                errors += 1
                error_details.append(f"{product.title}: invalid price {adjusted_price}")
                continue

            # Prepare Medusa product data
            medusa_data = {
                "title": product.title,
                "handle": product.handle,
                "description": product.description,
                "status": "published" if product.published else "draft",
                "metadata": {
                    "source_platform": "shopify",
                    "source_id": product.platform_id,
                    "storefront": storefront_key,
                },
                "variants": [
                    {
                        "title": v.title,
                        "sku": v.sku,
                        "prices": [{"amount": int(adjusted_price * 100), "currency_code": "usd"}],
                        "inventory_quantity": v.inventory_quantity,
                    }
                    for v in product.variants
                ],
            }

            result = self.client.create_product(medusa_data)
            if result:
                synced += 1
            else:
                errors += 1
                error_details.append(f"{product.title}: API create failed")

        result_dict: Dict[str, Any] = {
            "storefront": storefront_key,
            "products_filtered": len(filtered),
            "products_synced": synced,
            "errors": errors,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

        if error_details:
            result_dict["error_details"] = error_details[:20]  # Cap at 20

        if errors > 0 and synced == 0:
            result_dict["warning"] = "All products failed to sync"
        elif errors > 0:
            result_dict["warning"] = f"Partial sync: {errors}/{len(filtered)} products failed"

        return result_dict

    def get_architecture_summary(self) -> Dict[str, Any]:
        """Get summary of the multi-storefront architecture."""
        return {
            "architecture": {
                "fulfillment_hub": "Shopify (Cirrus1)",
                "backend": "Medusa",
                "niche_storefronts": len(self._niche_storefronts),
                "dynamic_storefronts": len(self._dynamic_keys),
                "future": ["TikTok Shop"],
            },
            "storefronts": {
                key: {
                    "name": sf.name,
                    "segments": sf.segments,
                    "status": sf.status.value,
                    "product_count": sf.product_count,
                }
                for key, sf in self._niche_storefronts.items()
            },
            "total_capacity": "unlimited (dynamic provisioning enabled)",
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get storefront statistics."""
        storefronts = self.list_niche_storefronts()
        return {
            "total_niche_storefronts": len(storefronts),
            "hardcoded_storefronts": len(storefronts) - len(self._dynamic_keys),
            "dynamic_storefronts": len(self._dynamic_keys),
            "active_storefronts": len([s for s in storefronts if s.status == StorefrontStatus.ACTIVE]),
            "total_products_across_niches": sum(s.product_count for s in storefronts),
            "total_revenue": sum(s.revenue for s in storefronts),
            "segments_covered": list(set(
                seg for sf in storefronts for seg in sf.segments
            )),
        }


class OrderRouter:
    """
    Routes orders from Medusa storefronts to Shopify for fulfillment.

    When a customer places an order on a Medusa niche storefront,
    this router creates a corresponding draft order in Shopify
    (Cirrus1 fulfillment hub) for Zendrop to fulfill.
    """

    def __init__(self, shopify_client: Any = None):
        """
        Args:
            shopify_client: A ShopifyClient instance connected to the
                fulfillment hub (Cirrus1).
        """
        self.shopify_client = shopify_client

    def create_draft_order_from_medusa(
        self,
        order_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create a Shopify draft order from Medusa checkout data.

        Args:
            order_data: Dict with keys:
                - source_storefront: niche storefront key (e.g. "pet_paradise")
                - email: customer email
                - shipping_address: address dict (optional)
                - items: list of items with metadata.shopify_variant_id

        Returns:
            Result dict with shopify_draft_order_id and invoice_url
        """
        if not self.shopify_client:
            return {"error": "Shopify client not configured"}

        line_items = []
        for item in order_data.get("items", []):
            metadata = item.get("metadata", {})
            shopify_variant_id = metadata.get("shopify_variant_id")
            if shopify_variant_id:
                line_items.append({
                    "variant_id": int(shopify_variant_id),
                    "quantity": item.get("quantity", 1),
                })

        if not line_items:
            return {"error": "No Shopify-linked items in order"}

        source = order_data.get("source_storefront", "medusa")
        draft_order = {
            "line_items": line_items,
            "email": order_data.get("email"),
            "note": f"Order from Medusa storefront: {source}",
            "tags": f"medusa,{source}",
        }

        shipping = order_data.get("shipping_address")
        if shipping:
            draft_order["shipping_address"] = shipping

        response = self.shopify_client._make_request(
            "draft_orders.json",
            method="POST",
            data={"draft_order": draft_order},
        )

        if not response:
            return {"error": "Failed to create draft order in Shopify"}

        shopify_order = response.get("draft_order", {})
        return {
            "success": True,
            "shopify_draft_order_id": shopify_order.get("id"),
            "shopify_order_name": shopify_order.get("name"),
            "invoice_url": shopify_order.get("invoice_url"),
            "source_storefront": source,
        }

    def handle_order_placed(
        self,
        webhook_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle a Medusa order.placed webhook event.

        Extracts items with Shopify metadata and creates a
        draft order in the fulfillment hub.

        Args:
            webhook_payload: Medusa webhook payload with event + data

        Returns:
            Result dict with medusa_order_id and shopify_draft_order_id
        """
        if not self.shopify_client:
            return {"error": "Shopify client not configured"}

        event_type = webhook_payload.get("event")
        if event_type != "order.placed":
            return {"error": f"Unexpected event type: {event_type}"}

        order = webhook_payload.get("data", {})

        # Extract items with Shopify variant metadata
        line_items = []
        for item in order.get("items", []):
            variant = item.get("variant", {})
            metadata = variant.get("metadata", {})
            shopify_variant_id = metadata.get("shopify_variant_id")
            if shopify_variant_id:
                line_items.append({
                    "variant_id": int(shopify_variant_id),
                    "quantity": item.get("quantity", 1),
                })

        if not line_items:
            return {"error": "No Shopify-linked items in webhook order"}

        # Map Medusa shipping address to Shopify format
        shipping = order.get("shipping_address", {})
        draft_order: Dict[str, Any] = {
            "line_items": line_items,
            "email": order.get("email"),
            "note": f"Medusa Order: {order.get('id')}",
            "tags": "medusa,webhook",
        }

        if shipping:
            draft_order["shipping_address"] = {
                "first_name": shipping.get("first_name"),
                "last_name": shipping.get("last_name"),
                "address1": shipping.get("address_1"),
                "address2": shipping.get("address_2"),
                "city": shipping.get("city"),
                "province": shipping.get("province"),
                "zip": shipping.get("postal_code"),
                "country": shipping.get("country_code"),
                "phone": shipping.get("phone"),
            }

        response = self.shopify_client._make_request(
            "draft_orders.json",
            method="POST",
            data={"draft_order": draft_order},
        )

        if not response:
            return {"error": "Failed to create draft order from webhook"}

        return {
            "success": True,
            "medusa_order_id": order.get("id"),
            "shopify_draft_order_id": response.get("draft_order", {}).get("id"),
        }
