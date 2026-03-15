"""
Shopforge Offline -- Offline-capable commerce operations for catalog browsing,
order processing, and AI-free product description generation.
"""

from shopforge.offline.catalog_browser import (
    CatalogBrowser, BrowseResult, FacetCount,
)
from shopforge.offline.order_processor import (
    OfflineOrderProcessor, OfflineOrder, SyncResult,
)
from shopforge.offline.description_generator import (
    DescriptionGenerator, ProductDescription, DescriptionTemplate,
)

__all__ = [
    "CatalogBrowser", "BrowseResult", "FacetCount",
    "OfflineOrderProcessor", "OfflineOrder", "SyncResult",
    "DescriptionGenerator", "ProductDescription", "DescriptionTemplate",
]
