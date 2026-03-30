"""Offline catalog browser with faceted filtering and pagination.

Operates on an in-memory product list -- no database or network required.
Supports text search, faceted filtering, sorting, and pagination.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class FacetCount:
    """Count of products matching a facet value."""
    field_name: str
    value: str
    count: int

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field_name, "value": self.value, "count": self.count}


@dataclass
class BrowseResult:
    """Paginated browse result."""
    items: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int
    facets: List[FacetCount] = field(default_factory=list)

    @property
    def total_pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "facets": [f.to_dict() for f in self.facets],
        }


_WORD_RE = re.compile(r"\w+", re.UNICODE)


class CatalogBrowser:
    """In-memory catalog browser with search, facets, and pagination."""

    def __init__(self, products: Optional[List[Dict[str, Any]]] = None):
        self._products: List[Dict[str, Any]] = list(products) if products else []
        self._facet_fields: List[str] = ["category", "brand", "status"]

    def load(self, products: List[Dict[str, Any]]) -> int:
        """Replace the catalog. Returns count loaded."""
        self._products = list(products)
        return len(self._products)

    def add(self, product: Dict[str, Any]) -> None:
        self._products.append(product)

    @property
    def size(self) -> int:
        return len(self._products)

    def set_facet_fields(self, fields: List[str]) -> None:
        self._facet_fields = list(fields)

    def _matches_query(self, product: Dict[str, Any], query: str) -> bool:
        if not query:
            return True
        query_lower = query.lower()
        searchable = " ".join(
            str(product.get(f, "")) for f in ["name", "description", "category", "brand", "sku"]
        ).lower()
        return query_lower in searchable

    def _matches_filters(self, product: Dict[str, Any],
                         filters: Dict[str, Any]) -> bool:
        for key, value in filters.items():
            prod_val = product.get(key)
            if isinstance(value, list):
                if prod_val not in value:
                    return False
            elif isinstance(value, dict):
                if "min" in value and (prod_val is None or prod_val < value["min"]):
                    return False
                if "max" in value and (prod_val is None or prod_val > value["max"]):
                    return False
            else:
                if prod_val != value:
                    return False
        return True

    def _compute_facets(self, products: List[Dict[str, Any]]) -> List[FacetCount]:
        facets: List[FacetCount] = []
        for field_name in self._facet_fields:
            counts: Dict[str, int] = {}
            for p in products:
                val = p.get(field_name)
                if val is not None:
                    key = str(val)
                    counts[key] = counts.get(key, 0) + 1
            for value, count in sorted(counts.items(), key=lambda x: -x[1]):
                facets.append(FacetCount(field_name=field_name, value=value, count=count))
        return facets

    def browse(self, query: str = "", filters: Optional[Dict[str, Any]] = None,
               sort_by: str = "name", sort_desc: bool = False,
               page: int = 1, page_size: int = 20,
               include_facets: bool = True) -> BrowseResult:
        """Search, filter, sort, and paginate the catalog."""
        filters = filters or {}
        matched = [
            p for p in self._products
            if self._matches_query(p, query) and self._matches_filters(p, filters)
        ]

        facets = self._compute_facets(matched) if include_facets else []

        def sort_key(p: Dict[str, Any]) -> Any:
            v = p.get(sort_by, "")
            if isinstance(v, str):
                return v.lower()
            return v if v is not None else 0

        matched.sort(key=sort_key, reverse=sort_desc)

        total = len(matched)
        start = (page - 1) * page_size
        end = start + page_size
        items = matched[start:end]

        return BrowseResult(
            items=items, total=total, page=page,
            page_size=page_size, facets=facets,
        )
