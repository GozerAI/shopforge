"""
Commerce Core - Data models and base structures.

Provides foundational data structures for multi-storefront commerce
operations including products, orders, and pricing.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class StorefrontPlatform(Enum):
    """Supported e-commerce platforms."""
    SHOPIFY = "shopify"
    MEDUSA = "medusa"
    TIKTOK = "tiktok"
    CUSTOM = "custom"


class StorefrontStatus(Enum):
    """Storefront operational status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    SETUP = "setup"


class PricingStrategy(Enum):
    """Product pricing strategies."""
    COST_PLUS = "cost_plus"
    COMPETITIVE = "competitive"
    VALUE_BASED = "value_based"
    DYNAMIC = "dynamic"
    LOSS_LEADER = "loss_leader"
    PREMIUM = "premium"
    BUNDLE = "bundle"
    PENETRATION = "penetration"


class InventoryStatus(Enum):
    """Inventory status levels."""
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    BACKORDERED = "backordered"
    DISCONTINUED = "discontinued"
    PREORDER = "preorder"


class OrderStatus(Enum):
    """Order fulfillment status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass
class ProductVariant:
    """Product variant (size, color, etc.)."""
    id: str = ""
    sku: str = ""
    title: str = "Default"
    price: float = 0.0
    compare_at_price: Optional[float] = None
    cost: Optional[float] = None
    inventory_quantity: int = 0
    inventory_status: InventoryStatus = InventoryStatus.IN_STOCK
    weight: Optional[float] = None
    weight_unit: str = "lb"
    barcode: Optional[str] = None
    options: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def margin(self) -> Optional[float]:
        """Calculate profit margin percentage."""
        if self.cost and self.cost > 0 and self.price > 0:
            return ((self.price - self.cost) / self.price) * 100
        return None

    @property
    def markup(self) -> Optional[float]:
        """Calculate markup percentage."""
        if self.cost and self.cost > 0:
            return ((self.price - self.cost) / self.cost) * 100
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sku": self.sku,
            "title": self.title,
            "price": self.price,
            "compare_at_price": self.compare_at_price,
            "cost": self.cost,
            "inventory_quantity": self.inventory_quantity,
            "inventory_status": self.inventory_status.value,
            "margin": self.margin,
            "markup": self.markup,
            "options": self.options,
        }


@dataclass
class Product:
    """Represents a product in the commerce system."""
    id: str = field(default_factory=lambda: str(uuid4()))
    platform_id: str = ""  # ID on the platform (Shopify, Medusa)
    storefront_key: str = ""
    platform: StorefrontPlatform = StorefrontPlatform.SHOPIFY

    # Basic info
    title: str = ""
    handle: str = ""
    description: str = ""
    vendor: Optional[str] = None
    product_type: Optional[str] = None

    # Variants
    variants: List[ProductVariant] = field(default_factory=list)

    # Categorization
    tags: List[str] = field(default_factory=list)
    collections: List[str] = field(default_factory=list)

    # Media
    images: List[Dict[str, Any]] = field(default_factory=list)

    # Pricing strategy
    pricing_strategy: PricingStrategy = PricingStrategy.COST_PLUS
    target_margin: float = 40.0

    # Status
    status: str = "active"  # active, draft, archived
    published: bool = True

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def primary_variant(self) -> Optional[ProductVariant]:
        """Get the primary (first) variant."""
        return self.variants[0] if self.variants else None

    @property
    def price(self) -> float:
        """Get price from primary variant."""
        return self.primary_variant.price if self.primary_variant else 0.0

    @property
    def cost(self) -> Optional[float]:
        """Get cost from primary variant."""
        return self.primary_variant.cost if self.primary_variant else None

    @property
    def total_inventory(self) -> int:
        """Get total inventory across all variants."""
        return sum(v.inventory_quantity for v in self.variants)

    @property
    def inventory_value(self) -> float:
        """Get total inventory value at cost."""
        return sum(
            (v.cost or 0) * v.inventory_quantity
            for v in self.variants
        )

    @property
    def margin(self) -> Optional[float]:
        """Get margin from primary variant."""
        return self.primary_variant.margin if self.primary_variant else None

    def get_inventory_status(self) -> InventoryStatus:
        """Determine overall inventory status."""
        total = self.total_inventory
        if total <= 0:
            return InventoryStatus.OUT_OF_STOCK
        elif total < 10:
            return InventoryStatus.LOW_STOCK
        else:
            return InventoryStatus.IN_STOCK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "platform_id": self.platform_id,
            "storefront_key": self.storefront_key,
            "platform": self.platform.value,
            "title": self.title,
            "handle": self.handle,
            "description": self.description[:200] if self.description else "",
            "vendor": self.vendor,
            "product_type": self.product_type,
            "price": self.price,
            "cost": self.cost,
            "margin": self.margin,
            "tags": self.tags,
            "collections": self.collections,
            "total_inventory": self.total_inventory,
            "inventory_status": self.get_inventory_status().value,
            "inventory_value": self.inventory_value,
            "variants": [v.to_dict() for v in self.variants],
            "image_count": len(self.images),
            "status": self.status,
            "published": self.published,
        }


@dataclass
class Collection:
    """Product collection/category."""
    id: str = field(default_factory=lambda: str(uuid4()))
    platform_id: str = ""
    storefront_key: str = ""
    title: str = ""
    handle: str = ""
    description: str = ""
    collection_type: str = "custom"  # custom, smart
    product_count: int = 0
    rules: List[Dict[str, Any]] = field(default_factory=list)  # For smart collections
    sort_order: str = "manual"
    published: bool = True
    image: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "platform_id": self.platform_id,
            "storefront_key": self.storefront_key,
            "title": self.title,
            "handle": self.handle,
            "description": self.description,
            "collection_type": self.collection_type,
            "product_count": self.product_count,
            "published": self.published,
        }


@dataclass
class OrderLineItem:
    """Line item in an order."""
    id: str = ""
    product_id: str = ""
    variant_id: str = ""
    title: str = ""
    variant_title: str = ""
    quantity: int = 1
    price: float = 0.0
    total: float = 0.0
    sku: Optional[str] = None
    fulfillment_status: Optional[str] = None


@dataclass
class Order:
    """Customer order."""
    id: str = field(default_factory=lambda: str(uuid4()))
    platform_id: str = ""
    storefront_key: str = ""
    order_number: str = ""

    # Customer
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None

    # Items
    line_items: List[OrderLineItem] = field(default_factory=list)

    # Financials
    subtotal: float = 0.0
    total_tax: float = 0.0
    total_shipping: float = 0.0
    total_discounts: float = 0.0
    total: float = 0.0
    currency: str = "USD"

    # Status
    status: OrderStatus = OrderStatus.PENDING
    financial_status: str = "pending"
    fulfillment_status: Optional[str] = None

    # Dates
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    fulfilled_at: Optional[datetime] = None

    # Shipping
    shipping_address: Optional[Dict[str, Any]] = None
    shipping_method: Optional[str] = None
    tracking_number: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.line_items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "platform_id": self.platform_id,
            "storefront_key": self.storefront_key,
            "order_number": self.order_number,
            "customer_email": self.customer_email,
            "item_count": self.item_count,
            "subtotal": self.subtotal,
            "total": self.total,
            "currency": self.currency,
            "status": self.status.value,
            "financial_status": self.financial_status,
            "fulfillment_status": self.fulfillment_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Storefront:
    """Represents a storefront configuration."""
    key: str = ""
    name: str = ""
    platform: StorefrontPlatform = StorefrontPlatform.SHOPIFY
    status: StorefrontStatus = StorefrontStatus.ACTIVE

    # Connection
    store_url: Optional[str] = None
    api_version: str = "2024-01"

    # Classification
    storefront_type: str = "general"  # general, niche, wholesale
    segments: List[str] = field(default_factory=list)
    niche_tags: List[str] = field(default_factory=list)

    # Metrics
    product_count: int = 0
    order_count: int = 0
    revenue_total: float = 0.0

    # Settings
    default_pricing_strategy: PricingStrategy = PricingStrategy.COST_PLUS
    default_target_margin: float = 40.0
    auto_sync_enabled: bool = True

    # Timestamps
    created_at: Optional[datetime] = None
    last_sync: Optional[datetime] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "platform": self.platform.value,
            "status": self.status.value,
            "store_url": self.store_url,
            "storefront_type": self.storefront_type,
            "segments": self.segments,
            "niche_tags": self.niche_tags,
            "product_count": self.product_count,
            "order_count": self.order_count,
            "revenue_total": self.revenue_total,
            "default_pricing_strategy": self.default_pricing_strategy.value,
            "default_target_margin": self.default_target_margin,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
        }


class StorefrontRegistry:
    """Registry for managing multiple storefronts."""

    def __init__(self, config_path: Optional[Path] = None):
        self._storefronts: Dict[str, Storefront] = {}
        self._config_path = config_path

        if config_path and config_path.exists():
            self._load_config()

    def register(self, storefront: Storefront) -> None:
        """Register a storefront."""
        self._storefronts[storefront.key] = storefront
        logger.info(f"Registered storefront: {storefront.key} ({storefront.platform.value})")

    def get(self, key: str) -> Optional[Storefront]:
        """Get a storefront by key."""
        return self._storefronts.get(key)

    def list_all(self) -> List[Storefront]:
        """List all storefronts."""
        return list(self._storefronts.values())

    def list_by_platform(self, platform: StorefrontPlatform) -> List[Storefront]:
        """List storefronts by platform."""
        return [s for s in self._storefronts.values() if s.platform == platform]

    def list_active(self) -> List[Storefront]:
        """List active storefronts."""
        return [s for s in self._storefronts.values() if s.status == StorefrontStatus.ACTIVE]

    def _load_config(self) -> None:
        """Load storefronts from config file."""
        try:
            with open(self._config_path) as f:
                config = json.load(f)

            for key, data in config.get("storefronts", {}).items():
                storefront = Storefront(
                    key=key,
                    name=data.get("name", key),
                    platform=StorefrontPlatform(data.get("platform", "shopify")),
                    status=StorefrontStatus(data.get("status", "active")),
                    store_url=data.get("store_url"),
                    storefront_type=data.get("type", "general"),
                    segments=data.get("segments", []),
                    niche_tags=data.get("niche_tags", []),
                )
                self.register(storefront)
        except Exception as e:
            logger.error(f"Failed to load storefront config: {e}")

    def save_config(self) -> None:
        """Save storefronts to config file."""
        if not self._config_path:
            return

        config = {
            "storefronts": {
                s.key: s.to_dict()
                for s in self._storefronts.values()
            }
        }

        with open(self._config_path, "w") as f:
            json.dump(config, f, indent=2)

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        storefronts = self.list_all()
        return {
            "total_storefronts": len(storefronts),
            "active_storefronts": len(self.list_active()),
            "by_platform": {
                p.value: len(self.list_by_platform(p))
                for p in StorefrontPlatform
            },
            "total_products": sum(s.product_count for s in storefronts),
            "total_revenue": sum(s.revenue_total for s in storefronts),
        }
