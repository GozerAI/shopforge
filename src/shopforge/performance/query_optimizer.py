"""Query optimizer for efficient data access patterns.

Provides filter reordering by selectivity, parallel ID resolution
with deduplication, and query plan generation.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# Estimated selectivity (lower = more selective = applied first)
_SELECTIVITY: Dict[str, float] = {
    "id": 0.01,
    "sku": 0.02,
    "platform_id": 0.03,
    "handle": 0.05,
    "barcode": 0.05,
    "customer_email": 0.08,
    "order_number": 0.08,
    "vendor": 0.15,
    "product_type": 0.20,
    "category": 0.20,
    "status": 0.25,
    "pricing_strategy": 0.25,
    "platform": 0.30,
    "tag": 0.35,
    "tags": 0.35,
    "price_min": 0.40,
    "price_max": 0.40,
    "price_range": 0.40,
    "name": 0.50,
    "title": 0.50,
    "description": 0.70,
    "published": 0.50,
    "inventory_status": 0.30,
}

_DEFAULT_SELECTIVITY = 0.50

# Strategy names
STRATEGY_INDEX_LOOKUP = "index_lookup"
STRATEGY_FILTERED_SCAN = "filtered_scan"
STRATEGY_FULL_SCAN = "full_scan"


@dataclass
class IndexSuggestion:
    """Suggests an index that would improve query performance."""
    field: str
    reason: str
    estimated_improvement: float  # Percentage improvement estimate
    priority: str = "medium"  # "low", "medium", "high"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "reason": self.reason,
            "estimated_improvement": round(self.estimated_improvement, 2),
            "priority": self.priority,
        }


@dataclass
class QueryPlan:
    """Describes an optimized query execution plan."""
    filters: List[Tuple[str, Any]] = field(default_factory=list)
    estimated_cost: float = 0.0
    strategy: str = STRATEGY_FULL_SCAN
    index_suggestions: List[IndexSuggestion] = field(default_factory=list)
    filter_order_rationale: List[str] = field(default_factory=list)
    estimated_rows_scanned: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filters": [{"field": f, "value": v} for f, v in self.filters],
            "estimated_cost": round(self.estimated_cost, 4),
            "strategy": self.strategy,
            "index_suggestions": [s.to_dict() for s in self.index_suggestions],
            "filter_order_rationale": self.filter_order_rationale,
            "estimated_rows_scanned": round(self.estimated_rows_scanned, 2),
        }


class QueryOptimizer:
    """Optimizes data access patterns for product and order queries.

    Features:
    - Filter reordering by selectivity (most selective first)
    - Query plan generation with cost estimation
    - Parallel ID resolution with deduplication
    - Index suggestions for slow queries
    """

    def __init__(
        self,
        catalog_size: int = 10_000,
        custom_selectivity: Optional[Dict[str, float]] = None,
        indexed_fields: Optional[Set[str]] = None,
    ):
        """
        Args:
            catalog_size: Estimated total number of records for cost estimation.
            custom_selectivity: Override selectivity values for specific fields.
            indexed_fields: Fields that have an index (lower cost for lookups).
        """
        self._catalog_size = catalog_size
        self._selectivity = dict(_SELECTIVITY)
        if custom_selectivity:
            self._selectivity.update(custom_selectivity)
        self._indexed_fields: Set[str] = indexed_fields or {"id", "sku", "platform_id", "handle"}
        self._query_history: List[QueryPlan] = []

    def optimize_product_query(self, filters: Dict[str, Any]) -> QueryPlan:
        """Optimize a product query by reordering filters by selectivity.

        Filters with lower selectivity values (more selective) are applied
        first to reduce the working set early.

        Args:
            filters: Dict of field -> value filter criteria.

        Returns:
            QueryPlan with optimized filter order, cost estimate, and suggestions.
        """
        if not filters:
            plan = QueryPlan(
                strategy=STRATEGY_FULL_SCAN,
                estimated_cost=float(self._catalog_size),
                estimated_rows_scanned=float(self._catalog_size),
            )
            self._query_history.append(plan)
            return plan

        # Score each filter by selectivity
        scored: List[Tuple[str, Any, float]] = []
        for fld, val in filters.items():
            sel = self._selectivity.get(fld, _DEFAULT_SELECTIVITY)
            # Indexed fields get a bonus (lower cost)
            if fld in self._indexed_fields:
                sel *= 0.1
            scored.append((fld, val, sel))

        # Sort by selectivity (most selective first)
        scored.sort(key=lambda x: x[2])

        ordered_filters = [(fld, val) for fld, val, _ in scored]

        # Estimate cost: multiply selectivities for compound filtering
        compound_selectivity = 1.0
        rationale = []
        for fld, val, sel in scored:
            compound_selectivity *= sel
            indexed_note = " (indexed)" if fld in self._indexed_fields else ""
            rationale.append(
                f"{fld}{indexed_note}: selectivity={sel:.3f}, "
                f"cumulative={compound_selectivity:.6f}"
            )

        estimated_rows = max(1.0, self._catalog_size * compound_selectivity)
        estimated_cost = estimated_rows

        # Determine strategy
        first_field = scored[0][0] if scored else None
        if first_field and first_field in self._indexed_fields:
            strategy = STRATEGY_INDEX_LOOKUP
            estimated_cost *= 0.5  # Index lookups are cheaper
        elif len(filters) > 0:
            strategy = STRATEGY_FILTERED_SCAN
        else:
            strategy = STRATEGY_FULL_SCAN

        # Generate index suggestions for non-indexed high-selectivity fields
        suggestions = []
        for fld, val, sel in scored:
            if fld not in self._indexed_fields and sel < 0.25:
                improvement = (1 - sel) * 100
                priority = "high" if sel < 0.10 else "medium"
                suggestions.append(IndexSuggestion(
                    field=fld,
                    reason=f"High-selectivity field ({sel:.2f}) used in query without index",
                    estimated_improvement=improvement,
                    priority=priority,
                ))

        plan = QueryPlan(
            filters=ordered_filters,
            estimated_cost=estimated_cost,
            strategy=strategy,
            index_suggestions=suggestions,
            filter_order_rationale=rationale,
            estimated_rows_scanned=estimated_rows,
        )
        self._query_history.append(plan)
        return plan

    def batch_resolve(
        self,
        ids: List[str],
        resolver: Callable[[str], Any],
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        """Resolve a batch of IDs in parallel with deduplication.

        Args:
            ids: List of IDs to resolve (duplicates are deduplicated).
            resolver: Callable that takes an ID and returns the resolved value.
            max_workers: Maximum number of parallel workers.

        Returns:
            Dict mapping ID -> resolved value. Failed resolutions are omitted.
        """
        unique_ids = list(dict.fromkeys(ids))  # Deduplicate preserving order
        results: Dict[str, Any] = {}

        if not unique_ids:
            return results

        # For small batches, run sequentially
        if len(unique_ids) <= 3:
            for uid in unique_ids:
                try:
                    results[uid] = resolver(uid)
                except Exception as e:
                    logger.warning(f"Failed to resolve ID '{uid}': {e}")
            return results

        # Parallel resolution
        with ThreadPoolExecutor(max_workers=min(max_workers, len(unique_ids))) as executor:
            future_to_id = {
                executor.submit(resolver, uid): uid
                for uid in unique_ids
            }
            for future in as_completed(future_to_id):
                uid = future_to_id[future]
                try:
                    results[uid] = future.result()
                except Exception as e:
                    logger.warning(f"Failed to resolve ID '{uid}': {e}")

        return results

    def analyze_query(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a query and return optimization recommendations.

        Args:
            filters: Query filter criteria.

        Returns:
            Dict with analysis results and recommendations.
        """
        plan = self.optimize_product_query(filters)
        recommendations = []

        if plan.strategy == STRATEGY_FULL_SCAN:
            recommendations.append("Add filters to avoid a full catalog scan")

        if plan.estimated_rows_scanned > self._catalog_size * 0.5:
            recommendations.append(
                f"Query scans ~{plan.estimated_rows_scanned:.0f}/{self._catalog_size} rows — "
                "consider adding more selective filters"
            )

        for suggestion in plan.index_suggestions:
            recommendations.append(
                f"Add index on '{suggestion.field}' for ~{suggestion.estimated_improvement:.0f}% improvement"
            )

        return {
            "plan": plan.to_dict(),
            "recommendations": recommendations,
            "estimated_cost": plan.estimated_cost,
        }

    def get_query_history(self) -> List[Dict[str, Any]]:
        """Return history of query plans generated."""
        return [p.to_dict() for p in self._query_history]

    def clear_history(self) -> None:
        """Clear query plan history."""
        self._query_history.clear()
