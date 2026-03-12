"""
Shopforge - Commerce Operations.

Provides multi-storefront management including Shopify and Medusa integration
for commerce operations. Enables pricing optimization, inventory control,
and sales analytics.

Primary Owners: CRO (Axiom), CFO (Ledger)
Secondary Owners: CMO (Echo), COO (Conductor)
"""

from shopforge.core import (
    StorefrontPlatform,
    StorefrontStatus,
    PricingStrategy,
    InventoryStatus,
    Product,
    ProductVariant,
    Collection,
    Order,
    Storefront,
)
from shopforge.shopify import (
    ShopifyClient,
    ShopifyStorefront,
)
from shopforge.shopify import RateLimiter
from shopforge.medusa import (
    MedusaClient,
    MedusaStorefront,
    NicheStorefront,
    OrderRouter,
)
from shopforge.pricing import (
    PricingEngine,
    PricingRecommendation,
    MarginAnalyzer,
)
from shopforge.trends import TrendEnricher
from shopforge.audit import AuditEntry, AuditLog
from shopforge.service import CommerceService

__all__ = [
    # Core
    "StorefrontPlatform",
    "StorefrontStatus",
    "PricingStrategy",
    "InventoryStatus",
    "Product",
    "ProductVariant",
    "Collection",
    "Order",
    "Storefront",
    # Shopify
    "ShopifyClient",
    "ShopifyStorefront",
    "RateLimiter",
    # Medusa
    "MedusaClient",
    "MedusaStorefront",
    "NicheStorefront",
    "OrderRouter",
    # Pricing
    "PricingEngine",
    "PricingRecommendation",
    "MarginAnalyzer",
    # Trends
    "TrendEnricher",
    # Audit
    "AuditEntry",
    "AuditLog",
    # Service
    "CommerceService",
]
