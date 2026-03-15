"""Demand-aware pricing recommendations.

Uses log-linear demand estimation (Q = a * P^(-e)) with revenue and margin
optimization to suggest optimal price points per product.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DemandCurve:
    """Estimated demand curve parameters for a product."""
    sku: str
    elasticity: float
    intercept: float
    r_squared: float
    sample_size: int

    def estimate_quantity(self, price: float) -> float:
        if price <= 0:
            return 0.0
        return self.intercept * (price ** (-self.elasticity))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "elasticity": round(self.elasticity, 4),
            "intercept": round(self.intercept, 4),
            "r_squared": round(self.r_squared, 4),
            "sample_size": self.sample_size,
        }


@dataclass
class PriceRecommendation:
    """Recommended price for a product."""
    sku: str
    current_price: float
    recommended_price: float
    estimated_revenue_change_pct: float
    estimated_margin_change_pct: float
    confidence: float
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "current_price": round(self.current_price, 2),
            "recommended_price": round(self.recommended_price, 2),
            "estimated_revenue_change_pct": round(self.estimated_revenue_change_pct, 2),
            "estimated_margin_change_pct": round(self.estimated_margin_change_pct, 2),
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
        }


class PricingRecommender:
    """Generates data-driven price recommendations from historical sales data.

    Uses log-linear regression on (price, quantity) observations to estimate
    demand elasticity, then finds the price that maximizes revenue or margin.
    """

    def __init__(self, min_observations: int = 5, price_step: float = 0.01,
                 price_range_pct: float = 0.50):
        self._min_obs = min_observations
        self._price_step = price_step
        self._price_range_pct = price_range_pct

    def estimate_demand(self, sku: str,
                        observations: List[Tuple[float, float]]) -> Optional[DemandCurve]:
        """Fit a log-linear demand curve from (price, quantity) pairs."""
        valid = [(p, q) for p, q in observations if p > 0 and q > 0]
        if len(valid) < self._min_obs:
            logger.debug("SKU %s: only %d valid observations (need %d)",
                         sku, len(valid), self._min_obs)
            return None

        n = len(valid)
        ln_prices = [math.log(p) for p, _ in valid]
        ln_quantities = [math.log(q) for _, q in valid]

        sum_x = sum(ln_prices)
        sum_y = sum(ln_quantities)
        sum_xy = sum(x * y for x, y in zip(ln_prices, ln_quantities))
        sum_x2 = sum(x * x for x in ln_prices)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-12:
            return None

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept_ln = (sum_y - slope * sum_x) / n

        elasticity = -slope
        intercept = math.exp(intercept_ln)

        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in ln_quantities)
        ss_res = sum(
            (y - (intercept_ln + slope * x)) ** 2
            for x, y in zip(ln_prices, ln_quantities)
        )
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return DemandCurve(
            sku=sku,
            elasticity=max(0.0, elasticity),
            intercept=intercept,
            r_squared=max(0.0, min(1.0, r_squared)),
            sample_size=n,
        )

    def recommend_price(self, curve: DemandCurve, current_price: float,
                        unit_cost: float = 0.0,
                        optimize: str = "revenue") -> PriceRecommendation:
        """Find the price that maximizes revenue or margin within a search range."""
        lo = current_price * (1.0 - self._price_range_pct)
        hi = current_price * (1.0 + self._price_range_pct)
        lo = max(lo, unit_cost + self._price_step) if unit_cost > 0 else max(lo, self._price_step)

        best_price = current_price
        best_value = -math.inf

        p = lo
        while p <= hi:
            q = curve.estimate_quantity(p)
            if optimize == "margin":
                val = (p - unit_cost) * q
            else:
                val = p * q
            if val > best_value:
                best_value = val
                best_price = p
            p += self._price_step

        cur_q = curve.estimate_quantity(current_price)
        new_q = curve.estimate_quantity(best_price)
        cur_rev = current_price * cur_q
        new_rev = best_price * new_q
        rev_change = ((new_rev - cur_rev) / cur_rev * 100) if cur_rev > 0 else 0.0

        cur_margin = (current_price - unit_cost) * cur_q
        new_margin = (best_price - unit_cost) * new_q
        margin_change = ((new_margin - cur_margin) / cur_margin * 100) if cur_margin > 0 else 0.0

        confidence = curve.r_squared * min(1.0, curve.sample_size / 30.0)

        if abs(best_price - current_price) < self._price_step * 2:
            reasoning = "Current price is near-optimal"
        elif best_price > current_price:
            reasoning = f"Inelastic demand (e={curve.elasticity:.2f}) supports higher price"
        else:
            reasoning = f"Elastic demand (e={curve.elasticity:.2f}) favours lower price for volume"

        return PriceRecommendation(
            sku=curve.sku,
            current_price=current_price,
            recommended_price=round(best_price, 2),
            estimated_revenue_change_pct=rev_change,
            estimated_margin_change_pct=margin_change,
            confidence=confidence,
            reasoning=reasoning,
        )

    def batch_recommend(self, products: List[Dict[str, Any]],
                        optimize: str = "revenue") -> List[PriceRecommendation]:
        """Generate recommendations for multiple products.

        Each product dict must contain:
          - sku: str
          - current_price: float
          - observations: list of (price, quantity) tuples
          - unit_cost: float (optional, default 0)
        """
        results: List[PriceRecommendation] = []
        for prod in products:
            sku = prod["sku"]
            curve = self.estimate_demand(sku, prod["observations"])
            if curve is None:
                logger.info("SKU %s: insufficient data for recommendation", sku)
                continue
            rec = self.recommend_price(
                curve,
                current_price=prod["current_price"],
                unit_cost=prod.get("unit_cost", 0.0),
                optimize=optimize,
            )
            results.append(rec)
        return results
