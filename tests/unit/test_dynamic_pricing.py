"""Tests for dynamic pricing strategy."""

import pytest
from shopforge.core import PricingStrategy
from shopforge.pricing import PricingEngine


class TestDynamicPricing:
    @pytest.fixture
    def engine(self):
        return PricingEngine()

    def test_dynamic_base_case(self, engine):
        """No context = same as cost-plus."""
        price, reason = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
        )
        assert price > 0
        assert "Dynamic" in reason

    def test_dynamic_high_demand(self, engine):
        """High demand drives price up."""
        low_price, _ = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"demand_score": 20},
        )
        high_price, _ = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"demand_score": 90},
        )
        assert high_price > low_price

    def test_dynamic_competitor_anchoring(self, engine):
        """Price stays near competitor average."""
        price, reason = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"competitor_avg": 25.0},
        )
        assert "comp_avg" in reason

    def test_dynamic_low_stock_premium(self, engine):
        """Low inventory adds premium."""
        normal_price, _ = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"inventory_days": 30},
        )
        low_stock_price, reason = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"inventory_days": 3},
        )
        assert low_stock_price > normal_price
        assert "low_stock_premium" in reason

    def test_dynamic_excess_stock_discount(self, engine):
        """Excess inventory triggers discount."""
        normal_price, _ = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"inventory_days": 30},
        )
        excess_price, reason = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"inventory_days": 120},
        )
        assert excess_price < normal_price
        assert "excess_stock_discount" in reason

    def test_dynamic_trend_velocity(self, engine):
        """Rising trend increases price."""
        falling_price, _ = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"trend_velocity": -0.5},
        )
        rising_price, _ = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={"trend_velocity": 0.8},
        )
        assert rising_price > falling_price

    def test_dynamic_zero_cost(self, engine):
        """Zero cost returns zero price."""
        price, reason = engine.calculate_price(
            cost=0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
        )
        assert price == 0.0

    def test_dynamic_combined_signals(self, engine):
        """Multiple signals compound correctly."""
        price, reason = engine.calculate_price(
            cost=10.0, target_margin=50.0,
            strategy=PricingStrategy.DYNAMIC,
            market_context={
                "demand_score": 80,
                "competitor_avg": 22.0,
                "inventory_days": 5,
                "trend_velocity": 0.6,
            },
        )
        assert price > 0
        assert "demand=80" in reason
        assert "low_stock_premium" in reason
