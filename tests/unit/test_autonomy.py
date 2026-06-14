"""Tests for shopforge.autonomy modules."""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

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
    FulfillmentRouter, FulfillmentCenter, RoutingDecision, _haversine,
)
from shopforge.autonomy.customer_segmenter import (
    CustomerSegmenter, RFMScore, CustomerSegment, SegmentationResult,
)

class TestInventoryOptimizer:
    def setup_method(self):
        self.optimizer = InventoryOptimizer()

    def test_safety_stock_calculation(self):
        daily_sales = [90, 110, 100, 95, 105, 100, 98, 102]
        result = self.optimizer.calculate_safety_stock(
            "PROD-1", "VAR-1", "SKU-001", daily_sales, lead_time_days=5.0,
        )
        assert isinstance(result, SafetyStockLevel)
        assert result.sku == "SKU-001"
        assert result.safety_stock > 0

    def test_reorder_point(self):
        daily_sales = [50, 55, 45, 60, 40, 50, 52, 48]
        result = self.optimizer.calculate_reorder_point(
            "PROD-2", "VAR-2", "SKU-002", daily_sales,
            current_stock=100, lead_time_days=3.0,
        )
        assert isinstance(result, ReorderPoint)
        assert result.reorder_point > 0
        assert result.safety_stock > 0

    def test_eoq_calculation(self):
        result = self.optimizer.calculate_eoq(
            "PROD-3", "VAR-3", "SKU-003", annual_demand=10000,
            unit_cost=20.0, order_cost=50.0,
        )
        assert isinstance(result, EOQResult)
        assert result.eoq > 0

    def test_eoq_to_dict(self):
        result = self.optimizer.calculate_eoq("P", "V", "SKU-004", 5000, 20.0, order_cost=25.0)
        d = result.to_dict()
        assert "sku" in d
        assert "eoq" in d

    def test_analyze_inventory(self):
        products = [{"id": "P1", "variants": [
            {"id": "V1", "sku": "SKU-005", "inventory_quantity": 5, "cost": 10.0},
        ]}]
        sales = {"SKU-005": [200, 190, 210, 195, 205]}
        result = self.optimizer.analyze_inventory(products, sales)
        assert "reorder_alerts" in result
        assert "eoq_recommendations" in result



class TestPricingRecommender:
    def setup_method(self):
        self.recommender = PricingRecommender(min_observations=3)

    def test_estimate_demand_insufficient_data(self):
        result = self.recommender.estimate_demand("SKU-1", [(10.0, 5.0)])
        assert result is None

    def test_estimate_demand_valid(self):
        obs = [(10.0, 100.0), (12.0, 80.0), (15.0, 60.0),
               (8.0, 130.0), (20.0, 40.0)]
        curve = self.recommender.estimate_demand("SKU-2", obs)
        assert curve is not None
        assert curve.sku == "SKU-2"
        assert curve.elasticity > 0
        assert 0 <= curve.r_squared <= 1

    def test_demand_curve_estimate_quantity(self):
        curve = DemandCurve(sku="T", elasticity=1.5, intercept=1000.0,
                           r_squared=0.9, sample_size=10)
        q = curve.estimate_quantity(10.0)
        assert q > 0
        assert curve.estimate_quantity(0) == 0.0

    def test_recommend_price(self):
        curve = DemandCurve(sku="SKU-3", elasticity=1.2, intercept=500.0,
                           r_squared=0.85, sample_size=20)
        rec = self.recommender.recommend_price(curve, current_price=25.0)
        assert isinstance(rec, PriceRecommendation)
        assert rec.recommended_price > 0

    def test_batch_recommend(self):
        products = [
            {"sku": "A", "current_price": 20.0,
             "observations": [(15, 100), (18, 80), (20, 65), (22, 50), (25, 35)]},
            {"sku": "B", "current_price": 10.0,
             "observations": [(8, 200), (10, 150), (12, 110), (14, 80), (16, 55)]},
        ]
        results = self.recommender.batch_recommend(products)
        assert len(results) == 2


class TestProductCategorizer:
    def setup_method(self):
        self.cat = ProductCategorizer()

    def test_categorize_electronics(self):
        matches = self.cat.categorize("Wireless Bluetooth Speaker",
                                      "High quality audio speaker")
        assert len(matches) > 0
        assert matches[0].category == "Electronics"

    def test_categorize_clothing(self):
        matches = self.cat.categorize("Cotton T-Shirt", tags=["shirt", "clothing"])
        assert any(m.category == "Clothing" for m in matches)

    def test_best_match(self):
        match = self.cat.best_match("Running Shoe", "Lightweight sneaker")
        assert match is not None
        assert match.category == "Clothing"
        assert match.subcategory == "Footwear"

    def test_no_match(self):
        match = self.cat.best_match("Abstract Concept XYZ123")
        assert match is None

    def test_batch_categorize(self):
        products = [
            {"sku": "P1", "name": "Laptop Computer"},
            {"sku": "P2", "name": "Yoga Mat"},
        ]
        results = self.cat.batch_categorize(products)
        assert "P1" in results
        assert "P2" in results


class TestFulfillmentRouter:
    def setup_method(self):
        self.centers = [
            FulfillmentCenter("FC1", "East Coast", 40.7, -74.0,
                            capacity_remaining=500, avg_ship_days=2.0, cost_per_order=4.50),
            FulfillmentCenter("FC2", "West Coast", 34.0, -118.2,
                            capacity_remaining=300, avg_ship_days=3.0, cost_per_order=5.00),
            FulfillmentCenter("FC3", "Central", 41.8, -87.6,
                            capacity_remaining=800, avg_ship_days=2.5, cost_per_order=3.75),
        ]
        self.router = FulfillmentRouter(centers=self.centers)

    def test_haversine_distance(self):
        dist = _haversine(40.7, -74.0, 34.0, -118.2)
        assert 3900 < dist < 4000

    def test_route_selects_best(self):
        decision = self.router.route("ORD-1", dest_lat=42.0, dest_lon=-71.0)
        assert decision is not None
        assert isinstance(decision, RoutingDecision)
        assert decision.selected_center_id in ("FC1", "FC3")

    def test_route_no_eligible(self):
        router = FulfillmentRouter(centers=[
            FulfillmentCenter("FC1", "Test", 40.0, -74.0, supported_regions=["EU"]),
        ])
        decision = router.route("ORD-2", 40.0, -74.0, region="US")
        assert decision is None

    def test_batch_route(self):
        orders = [
            {"order_id": "O1", "latitude": 40.7, "longitude": -74.0},
            {"order_id": "O2", "latitude": 34.0, "longitude": -118.2},
        ]
        results = self.router.batch_route(orders)
        assert len(results) == 2

    def test_add_remove_center(self):
        router = FulfillmentRouter()
        fc = FulfillmentCenter("NEW", "New", 0.0, 0.0)
        router.add_center(fc)
        assert len(router.centers) == 1
        assert router.remove_center("NEW")
        assert len(router.centers) == 0


class TestCustomerSegmenter:
    def setup_method(self):
        self.segmenter = CustomerSegmenter()
        self.now = datetime(2026, 3, 13, tzinfo=timezone.utc)

    def _make_customers(self):
        return [
            {"customer_id": "C1", "last_order_date": self.now - timedelta(days=1),
             "order_count": 50, "total_spent": 5000.0},
            {"customer_id": "C2", "last_order_date": self.now - timedelta(days=30),
             "order_count": 10, "total_spent": 800.0},
            {"customer_id": "C3", "last_order_date": self.now - timedelta(days=180),
             "order_count": 2, "total_spent": 50.0},
            {"customer_id": "C4", "last_order_date": self.now - timedelta(days=7),
             "order_count": 25, "total_spent": 2000.0},
            {"customer_id": "C5", "last_order_date": self.now - timedelta(days=365),
             "order_count": 1, "total_spent": 20.0},
        ]

    def test_compute_rfm(self):
        customers = self._make_customers()
        rfm_list = self.segmenter.compute_rfm(customers, self.now)
        assert len(rfm_list) == 5
        for rfm in rfm_list:
            assert 1 <= rfm.r_score <= 5
            assert 1 <= rfm.f_score <= 5
            assert 1 <= rfm.m_score <= 5

    def test_segment(self):
        customers = self._make_customers()
        results = self.segmenter.segment(customers, self.now)
        assert len(results) == 5
        segments = {r.customer_id: r.segment for r in results}
        assert segments["C1"] in ("VIP", "Loyal")
        assert segments["C5"] in ("Dormant", "At-Risk")

    def test_segment_summary(self):
        customers = self._make_customers()
        results = self.segmenter.segment(customers, self.now)
        summary = self.segmenter.segment_summary(results)
        assert sum(summary.values()) == 5

    def test_empty_customers(self):
        results = self.segmenter.compute_rfm([])
        assert results == []
