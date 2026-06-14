"""
Shopforge Autonomy -- Autonomous commerce optimization modules.
"""

from shopforge.autonomy.inventory_optimizer import (
    InventoryOptimizer, ReorderPoint, SafetyStockLevel, EOQResult,
)
from shopforge.autonomy.pricing_recommender import (
    PricingRecommender, DemandCurve, PriceRecommendation,
)
from shopforge.autonomy.product_categorizer import (
    ProductCategorizer, CategoryMatch, CategoryTaxonomy,
)
from shopforge.autonomy.order_router import (
    FulfillmentRouter, FulfillmentCenter, RoutingDecision,
)
from shopforge.autonomy.customer_segmenter import (
    CustomerSegmenter, RFMScore, CustomerSegment, SegmentationResult,
)

__all__ = [
    "InventoryOptimizer", "ReorderPoint", "SafetyStockLevel", "EOQResult",
    "PricingRecommender", "DemandCurve", "PriceRecommendation",
    "ProductCategorizer", "CategoryMatch", "CategoryTaxonomy",
    "FulfillmentRouter", "FulfillmentCenter", "RoutingDecision",
    "CustomerSegmenter", "RFMScore", "CustomerSegment", "SegmentationResult",
]
