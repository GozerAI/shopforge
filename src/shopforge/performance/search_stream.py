"""Streaming product search with in-memory filtering and relevance scoring.

Provides paginated, filtered search over product catalogs with
relevance-based ranking and lazy iteration.
"""

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchFilter:
    """Describes a filter to apply to search results."""
    field: str  # "name", "category", "price_min", "price_max", "tag", "vendor", "status"
    value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "value": self.value}


@dataclass
class StreamChunk:
    """A page of search results."""
    items: List[Dict[str, Any]] = field(default_factory=list)
    page: int = 1
    total_pages: int = 1
    total_items: int = 0
    has_next: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "total_pages": self.total_pages,
            "total_items": self.total_items,
            "has_next": self.has_next,
            "count": len(self.items),
        }


def _relevance_score(item: Dict[str, Any], query: str) -> float:
    """Compute a relevance score for a product against a query.

    Scoring:
    - Exact title match: 100
    - Title starts with query: 80
    - Title contains query (case-insensitive): 60
    - Description contains query: 30
    - Tag matches query: 40
    - Category/product_type matches: 35
    - Vendor matches: 20
    """
    if not query:
        return 0.0

    score = 0.0
    q = query.lower().strip()
    title = str(item.get("title", "")).lower()
    description = str(item.get("description", "")).lower()
    tags = [str(t).lower() for t in item.get("tags", [])]
    category = str(item.get("product_type", "") or item.get("category", "")).lower()
    vendor = str(item.get("vendor", "")).lower()

    # Title scoring
    if title == q:
        score += 100
    elif title.startswith(q):
        score += 80
    elif q in title:
        score += 60

    # Word-level partial matching in title
    query_words = q.split()
    title_words = title.split()
    if len(query_words) > 1:
        matched_words = sum(1 for w in query_words if any(w in tw for tw in title_words))
        word_ratio = matched_words / len(query_words)
        score += word_ratio * 25

    # Description
    if q in description:
        score += 30

    # Tags
    for tag in tags:
        if q == tag:
            score += 40
            break
        elif q in tag:
            score += 25
            break

    # Category
    if q in category:
        score += 35

    # Vendor
    if q in vendor:
        score += 20

    return score


def _apply_filters(
    items: List[Dict[str, Any]], filters: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Apply filters to a list of product dicts."""
    if not filters:
        return items

    result = items

    # Name / title filter (substring, case-insensitive)
    name_filter = filters.get("name")
    if name_filter:
        name_lower = str(name_filter).lower()
        result = [
            p for p in result
            if name_lower in str(p.get("title", "")).lower()
        ]

    # Category / product_type
    category = filters.get("category")
    if category:
        cat_lower = str(category).lower()
        result = [
            p for p in result
            if cat_lower == str(p.get("product_type", "") or p.get("category", "")).lower()
        ]

    # Price range
    price_min = filters.get("price_min")
    if price_min is not None:
        result = [p for p in result if _get_price(p) >= float(price_min)]

    price_max = filters.get("price_max")
    if price_max is not None:
        result = [p for p in result if _get_price(p) <= float(price_max)]

    # Tag (any match)
    tag_filter = filters.get("tag") or filters.get("tags")
    if tag_filter:
        if isinstance(tag_filter, str):
            tag_filter = [tag_filter]
        tag_set = {t.lower() for t in tag_filter}
        result = [
            p for p in result
            if tag_set & {str(t).lower() for t in p.get("tags", [])}
        ]

    # Vendor
    vendor = filters.get("vendor")
    if vendor:
        vendor_lower = str(vendor).lower()
        result = [
            p for p in result
            if str(p.get("vendor", "")).lower() == vendor_lower
        ]

    # Status
    status = filters.get("status")
    if status:
        result = [
            p for p in result
            if str(p.get("status", "")).lower() == str(status).lower()
        ]

    return result


def _get_price(item: Dict[str, Any]) -> float:
    """Extract price from a product dict."""
    price = item.get("price", 0)
    if price is None:
        return 0.0
    try:
        return float(price)
    except (ValueError, TypeError):
        return 0.0


class SearchStream:
    """Streaming search engine for product catalogs.

    Supports in-memory filtering by name, category, price range, tags,
    and vendor. Results are ranked by relevance score.
    """

    def __init__(self, catalog: Optional[List[Dict[str, Any]]] = None):
        """
        Args:
            catalog: Initial product catalog (list of product dicts).
                     Can be updated later via set_catalog().
        """
        self._catalog: List[Dict[str, Any]] = catalog or []

    def set_catalog(self, catalog: List[Dict[str, Any]]) -> None:
        """Replace the product catalog."""
        self._catalog = catalog

    @property
    def catalog_size(self) -> int:
        return len(self._catalog)

    def search(
        self,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
        page_size: int = 20,
    ) -> Iterator[StreamChunk]:
        """Search products with filtering and pagination.

        Yields StreamChunk pages of results sorted by relevance.

        Args:
            query: Search query string (matched against title, description, tags).
            filters: Dict of filter criteria (name, category, price_min, price_max, tag, vendor, status).
            page_size: Number of items per page.

        Yields:
            StreamChunk for each page of results.
        """
        if page_size < 1:
            page_size = 1

        # Apply filters
        filtered = _apply_filters(self._catalog, filters)

        # Score and sort by relevance
        if query:
            scored = [
                (item, _relevance_score(item, query))
                for item in filtered
            ]
            # Only keep items with some relevance when query is provided
            scored = [(item, s) for item, s in scored if s > 0]
            scored.sort(key=lambda x: x[1], reverse=True)
            results = [item for item, _ in scored]
        else:
            results = filtered

        total_items = len(results)
        total_pages = max(1, math.ceil(total_items / page_size))

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * page_size
            end = start + page_size
            page_items = results[start:end]

            yield StreamChunk(
                items=page_items,
                page=page_num,
                total_pages=total_pages,
                total_items=total_items,
                has_next=page_num < total_pages,
            )

    def search_page(
        self,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> StreamChunk:
        """Get a specific page of search results.

        Args:
            query: Search query string.
            filters: Filter criteria dict.
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            StreamChunk for the requested page.
        """
        if page < 1:
            page = 1

        for chunk in self.search(query, filters, page_size):
            if chunk.page == page:
                return chunk

        # Page beyond results — return empty
        return StreamChunk(
            items=[],
            page=page,
            total_pages=0,
            total_items=0,
            has_next=False,
        )

    def count(
        self,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count matching results without pagination overhead."""
        filtered = _apply_filters(self._catalog, filters)
        if query:
            return sum(
                1 for item in filtered
                if _relevance_score(item, query) > 0
            )
        return len(filtered)
