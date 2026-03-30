"""
Pricing Engine - Dynamic pricing and margin optimization.

Provides pricing optimization, margin analysis, and pricing
recommendations for the commerce operations module.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from shopforge.core import (
    PricingStrategy,
    Product,
    ProductVariant,
)

logger = logging.getLogger(__name__)


@dataclass
class PricingRecommendation:
    """Pricing recommendation for a product."""
    id: str = field(default_factory=lambda: str(uuid4()))
    product_id: str = ""
    variant_id: str = ""
    product_title: str = ""

    # Current state
    current_price: float = 0.0
    current_cost: Optional[float] = None
    current_margin: Optional[float] = None

    # Recommendation
    recommended_price: float = 0.0
    recommended_margin: float = 0.0
    strategy: PricingStrategy = PricingStrategy.COST_PLUS

    # Analysis
    price_change: float = 0.0
    price_change_pct: float = 0.0
    reasoning: str = ""
    confidence: float = 0.8

    # Competitive context
    market_average: Optional[float] = None
    competitor_prices: List[float] = field(default_factory=list)

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "variant_id": self.variant_id,
            "product_title": self.product_title,
            "current_price": self.current_price,
            "current_cost": self.current_cost,
            "current_margin": self.current_margin,
            "recommended_price": self.recommended_price,
            "recommended_margin": self.recommended_margin,
            "strategy": self.strategy.value,
            "price_change": self.price_change,
            "price_change_pct": self.price_change_pct,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
        }


@dataclass
class MarginAnalysis:
    """Margin analysis for a product or storefront."""
    entity_type: str = "product"  # product, storefront, portfolio
    entity_id: str = ""
    entity_name: str = ""

    # Metrics
    total_revenue: float = 0.0
    total_cost: float = 0.0
    gross_profit: float = 0.0
    gross_margin: float = 0.0

    # Distribution
    margin_distribution: Dict[str, int] = field(default_factory=dict)
    products_by_margin: Dict[str, List[str]] = field(default_factory=dict)

    # Alerts
    negative_margin_count: int = 0
    low_margin_count: int = 0
    healthy_margin_count: int = 0
    high_margin_count: int = 0

    # Recommendations
    improvement_potential: float = 0.0
    recommendations: List[str] = field(default_factory=list)

    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "total_revenue": round(self.total_revenue, 2),
            "total_cost": round(self.total_cost, 2),
            "gross_profit": round(self.gross_profit, 2),
            "gross_margin": round(self.gross_margin, 2),
            "margin_distribution": self.margin_distribution,
            "negative_margin_count": self.negative_margin_count,
            "low_margin_count": self.low_margin_count,
            "healthy_margin_count": self.healthy_margin_count,
            "high_margin_count": self.high_margin_count,
            "improvement_potential": round(self.improvement_potential, 2),
            "recommendations": self.recommendations,
        }


class MarginAnalyzer:
    """Analyzes product and portfolio margins."""

    # Margin thresholds
    MARGIN_THRESHOLDS = {
        "negative": (-100, 0),
        "low": (0, 20),
        "medium": (20, 40),
        "healthy": (40, 60),
        "high": (60, 100),
    }

    # Category target margins
    CATEGORY_TARGETS = {
        "apparel": 50.0,
        "electronics": 25.0,
        "accessories": 60.0,
        "home": 45.0,
        "health": 40.0,
        "default": 40.0,
    }

    def analyze_product(self, product: Product) -> Optional[MarginAnalysis]:
        """Analyze a single product's margin."""
        if not product.variants:
            return None

        total_revenue = sum(v.price * v.inventory_quantity for v in product.variants)
        total_cost = sum((v.cost or 0) * v.inventory_quantity for v in product.variants)

        if total_revenue == 0:
            return None

        gross_profit = total_revenue - total_cost
        gross_margin = (gross_profit / total_revenue) * 100 if total_revenue > 0 else 0

        analysis = MarginAnalysis(
            entity_type="product",
            entity_id=product.id,
            entity_name=product.title,
            total_revenue=total_revenue,
            total_cost=total_cost,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
        )

        # Categorize margin
        if gross_margin < 0:
            analysis.negative_margin_count = 1
            analysis.recommendations.append("CRITICAL: Product is losing money. Increase price or reduce cost.")
        elif gross_margin < 20:
            analysis.low_margin_count = 1
            analysis.recommendations.append("Low margin - consider price optimization")
        elif gross_margin < 40:
            analysis.healthy_margin_count = 1
        else:
            analysis.high_margin_count = 1

        return analysis

    def analyze_portfolio(
        self,
        products: List[Product],
        name: str = "Portfolio",
    ) -> MarginAnalysis:
        """Analyze a portfolio of products."""
        analysis = MarginAnalysis(
            entity_type="portfolio",
            entity_name=name,
        )

        products_with_data = []
        for product in products:
            if product.cost is not None:
                products_with_data.append(product)
                margin = product.margin or 0

                # Count by category
                if margin < 0:
                    analysis.negative_margin_count += 1
                    if "negative" not in analysis.products_by_margin:
                        analysis.products_by_margin["negative"] = []
                    analysis.products_by_margin["negative"].append(product.title)
                elif margin < 20:
                    analysis.low_margin_count += 1
                    if "low" not in analysis.products_by_margin:
                        analysis.products_by_margin["low"] = []
                    analysis.products_by_margin["low"].append(product.title)
                elif margin < 40:
                    analysis.healthy_margin_count += 1
                else:
                    analysis.high_margin_count += 1

        if not products_with_data:
            analysis.recommendations.append("No products with cost data available")
            return analysis

        # Calculate totals
        analysis.total_revenue = sum(
            p.price * p.total_inventory for p in products_with_data
        )
        analysis.total_cost = sum(
            (p.cost or 0) * p.total_inventory for p in products_with_data
        )
        analysis.gross_profit = analysis.total_revenue - analysis.total_cost
        analysis.gross_margin = (
            (analysis.gross_profit / analysis.total_revenue) * 100
            if analysis.total_revenue > 0 else 0
        )

        # Margin distribution
        analysis.margin_distribution = {
            "negative": analysis.negative_margin_count,
            "low": analysis.low_margin_count,
            "healthy": analysis.healthy_margin_count,
            "high": analysis.high_margin_count,
        }

        # Calculate improvement potential
        target_margin = 40.0
        if analysis.gross_margin < target_margin:
            potential_profit = analysis.total_revenue * (target_margin / 100)
            analysis.improvement_potential = potential_profit - analysis.gross_profit

        # Generate recommendations
        if analysis.negative_margin_count > 0:
            analysis.recommendations.append(
                f"CRITICAL: {analysis.negative_margin_count} products losing money"
            )
        if analysis.low_margin_count > 5:
            analysis.recommendations.append(
                f"Review pricing for {analysis.low_margin_count} low-margin products"
            )
        if analysis.gross_margin < 30:
            analysis.recommendations.append(
                "Overall portfolio margin below healthy threshold"
            )
        if analysis.improvement_potential > 1000:
            analysis.recommendations.append(
                f"Potential ${analysis.improvement_potential:,.2f} profit improvement available"
            )

        return analysis


class PricingEngine:
    """
    Dynamic pricing engine for commerce operations.

    Provides pricing recommendations based on various strategies
    including cost-plus, competitive, and value-based pricing.
    """

    # Price rounding rules
    PRICE_POINTS = {
        "budget": (0, 25, 0.99),  # End in .99
        "mid": (25, 100, 0.99),  # End in .99
        "premium": (100, 500, 0.00),  # Round numbers
        "luxury": (500, float("inf"), 0.00),  # Round numbers
    }

    def __init__(self):
        self.margin_analyzer = MarginAnalyzer()
        self._recommendations: List[PricingRecommendation] = []

    def calculate_price(
        self,
        cost: float,
        target_margin: float,
        strategy: PricingStrategy = PricingStrategy.COST_PLUS,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, str]:
        """
        Calculate recommended price.

        Args:
            cost: Product cost
            target_margin: Target margin percentage
            strategy: Pricing strategy to use
            market_context: Optional competitive/market data

        Returns:
            Tuple of (recommended_price, reasoning)
        """
        if cost <= 0:
            return 0.0, "Cannot calculate price without cost data"

        # Clamp margin to safe range
        target_margin = max(0.0, min(99.0, target_margin))

        if strategy == PricingStrategy.COST_PLUS:
            # Price = Cost / (1 - margin%)
            price = cost / (1 - target_margin / 100)
            reasoning = f"Cost-plus: {target_margin}% margin on ${cost:.2f} cost"

        elif strategy == PricingStrategy.COMPETITIVE:
            # Use market average if available
            market_avg = market_context.get("market_average") if market_context else None
            if market_avg:
                price = market_avg * 0.95  # Slightly below market
                reasoning = f"Competitive: 5% below market average ${market_avg:.2f}"
            else:
                price = cost * 1.5  # Default 50% markup
                reasoning = "Competitive: Default 50% markup (no market data)"

        elif strategy == PricingStrategy.VALUE_BASED:
            # Premium on top of cost-plus
            base = cost / (1 - target_margin / 100)
            price = base * 1.2  # 20% value premium
            reasoning = f"Value-based: {target_margin}% margin + 20% value premium"

        elif strategy == PricingStrategy.LOSS_LEADER:
            # Minimal margin for volume
            price = cost * 1.1  # 10% markup
            reasoning = "Loss leader: Minimal 10% markup for volume"

        elif strategy == PricingStrategy.PREMIUM:
            # High margin premium pricing
            price = cost / (1 - 0.6)  # 60% margin
            reasoning = "Premium: 60% target margin"

        elif strategy == PricingStrategy.PENETRATION:
            # Low price for market entry
            price = cost * 1.2  # 20% markup
            reasoning = "Penetration: Low 20% markup for market entry"

        elif strategy == PricingStrategy.DYNAMIC:
            price, reasoning = self._calculate_dynamic_price(
                cost, target_margin, market_context,
            )

        else:
            price = cost / (1 - target_margin / 100)
            reasoning = f"Default: {target_margin}% margin"

        # Round to nice price point
        price = self._round_to_price_point(price)

        return price, reasoning

    def _round_to_price_point(self, price: float) -> float:
        """Round price to psychological price point."""
        if price < 10:
            return round(price, 2)
        elif price < 25:
            return round(price) - 0.01  # $24.99 style
        elif price < 100:
            return round(price / 5) * 5 - 0.01  # Round to 5, subtract penny
        elif price < 500:
            return round(price / 10) * 10 - 1  # Round to 10, subtract dollar
        else:
            return round(price / 50) * 50  # Round to 50

    def _calculate_dynamic_price(
        self,
        cost: float,
        target_margin: float,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, str]:
        """
        Calculate a dynamic price based on demand signals, competitor data,
        and inventory pressure.

        market_context keys:
            demand_score (0-100): how hot the product is right now
            competitor_avg: average competitor price
            inventory_days: days of inventory remaining
            trend_velocity (-1 to 1): trend momentum
        """
        ctx = market_context or {}
        base_price = cost / (1 - target_margin / 100)
        factors = []

        # Demand multiplier: high demand → price up, low → price down
        demand = ctx.get("demand_score", 50)
        demand_mult = 1.0 + (demand - 50) / 200  # ±25% range
        factors.append(f"demand={demand}")

        # Competitor anchoring
        comp_avg = ctx.get("competitor_avg")
        comp_mult = 1.0
        if comp_avg and comp_avg > 0:
            # Stay within 10% of competitor average
            ratio = comp_avg / base_price if base_price > 0 else 1.0
            comp_mult = max(0.9, min(1.1, ratio))
            factors.append(f"comp_avg=${comp_avg:.2f}")

        # Inventory pressure: low stock → price up, excess → discount
        inv_days = ctx.get("inventory_days")
        inv_mult = 1.0
        if inv_days is not None:
            if inv_days < 7:
                inv_mult = 1.10  # Low stock premium
                factors.append("low_stock_premium")
            elif inv_days > 90:
                inv_mult = 0.90  # Excess stock discount
                factors.append("excess_stock_discount")

        # Trend velocity: rising trends → premium
        velocity = ctx.get("trend_velocity", 0)
        trend_mult = 1.0 + velocity * 0.1  # ±10%
        if velocity != 0:
            factors.append(f"velocity={velocity:.2f}")

        price = base_price * demand_mult * comp_mult * inv_mult * trend_mult

        # Bounds: never below cost, never more than 3x base
        price = max(cost * 1.05, min(base_price * 3.0, price))

        reasoning = f"Dynamic: base ${base_price:.2f} adjusted by {', '.join(factors)}"

        return price, reasoning

    def generate_recommendations(
        self,
        products: List[Product],
        target_margin: float = 40.0,
        strategy: PricingStrategy = PricingStrategy.COST_PLUS,
        min_change_pct: float = 5.0,
    ) -> List[PricingRecommendation]:
        """
        Generate pricing recommendations for products.

        Args:
            products: Products to analyze
            target_margin: Target margin percentage
            strategy: Pricing strategy to use
            min_change_pct: Minimum price change to recommend

        Returns:
            List of pricing recommendations
        """
        recommendations = []

        for product in products:
            if not product.cost or product.cost <= 0:
                continue

            for variant in product.variants:
                if not variant.cost or variant.cost <= 0:
                    continue

                # Calculate recommended price
                rec_price, reasoning = self.calculate_price(
                    variant.cost,
                    target_margin,
                    strategy,
                )

                # Calculate change
                price_change = rec_price - variant.price
                price_change_pct = (price_change / variant.price) * 100 if variant.price > 0 else 0

                # Skip if change is too small
                if abs(price_change_pct) < min_change_pct:
                    continue

                # Calculate expected margin
                expected_margin = ((rec_price - variant.cost) / rec_price) * 100 if rec_price > 0 else 0

                rec = PricingRecommendation(
                    product_id=product.id,
                    variant_id=variant.id,
                    product_title=product.title,
                    current_price=variant.price,
                    current_cost=variant.cost,
                    current_margin=variant.margin,
                    recommended_price=rec_price,
                    recommended_margin=expected_margin,
                    strategy=strategy,
                    price_change=price_change,
                    price_change_pct=price_change_pct,
                    reasoning=reasoning,
                    confidence=0.8 if variant.cost else 0.5,
                )
                recommendations.append(rec)

        # Sort by potential impact
        recommendations.sort(key=lambda r: abs(r.price_change), reverse=True)

        self._recommendations = recommendations
        return recommendations

    def get_pricing_summary(
        self,
        products: List[Product],
    ) -> Dict[str, Any]:
        """Get pricing summary for a set of products."""
        # Portfolio analysis
        analysis = self.margin_analyzer.analyze_portfolio(products)

        # Generate recommendations
        recommendations = self.generate_recommendations(products)

        # Calculate potential impact
        total_increase = sum(
            r.price_change for r in recommendations
            if r.price_change > 0
        )
        total_decrease = sum(
            r.price_change for r in recommendations
            if r.price_change < 0
        )

        return {
            "portfolio_analysis": analysis.to_dict(),
            "recommendations_count": len(recommendations),
            "price_increase_recommendations": len([r for r in recommendations if r.price_change > 0]),
            "price_decrease_recommendations": len([r for r in recommendations if r.price_change < 0]),
            "potential_revenue_impact": {
                "increases": round(total_increase, 2),
                "decreases": round(total_decrease, 2),
                "net": round(total_increase + total_decrease, 2),
            },
            "top_recommendations": [r.to_dict() for r in recommendations[:10]],
        }

    def optimize_for_storefront(
        self,
        products: List[Product],
        storefront_key: str,
        storefront_strategy: str = "competitive",
        base_markup: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Optimize pricing for a specific storefront.

        Args:
            products: Products to optimize
            storefront_key: Storefront identifier
            storefront_strategy: Pricing strategy for this storefront
            base_markup: Additional markup for this storefront

        Returns:
            Optimization results
        """
        strategy_map = {
            "competitive": PricingStrategy.COMPETITIVE,
            "premium": PricingStrategy.PREMIUM,
            "value": PricingStrategy.VALUE_BASED,
            "penetration": PricingStrategy.PENETRATION,
        }
        strategy = strategy_map.get(storefront_strategy, PricingStrategy.COST_PLUS)

        # Generate base recommendations
        recommendations = self.generate_recommendations(
            products,
            target_margin=40.0 + base_markup,
            strategy=strategy,
        )

        # Apply storefront-specific adjustments
        for rec in recommendations:
            if base_markup > 0:
                rec.recommended_price *= (1 + base_markup / 100)
                rec.recommended_price = self._round_to_price_point(rec.recommended_price)
                rec.reasoning += f" + {base_markup}% storefront markup"

        return {
            "storefront": storefront_key,
            "strategy": strategy.value,
            "base_markup": base_markup,
            "products_analyzed": len(products),
            "recommendations": len(recommendations),
            "price_changes": [r.to_dict() for r in recommendations],
        }
