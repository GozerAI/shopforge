"""Tests for shopforge.offline modules."""

import pytest

from shopforge.offline.catalog_browser import CatalogBrowser, BrowseResult, FacetCount
from shopforge.offline.order_processor import (
    OfflineOrderProcessor, OfflineOrder, OfflineOrderStatus, SyncResult,
)
from shopforge.offline.description_generator import (
    DescriptionGenerator, ProductDescription, DescriptionTemplate,
)


class TestCatalogBrowser:
    def _sample_products(self):
        return [
            {"sku": "P1", "name": "Laptop Pro", "category": "Electronics",
             "brand": "TechCo", "price": 999.99, "status": "active"},
            {"sku": "P2", "name": "Cotton T-Shirt", "category": "Clothing",
             "brand": "StyleBrand", "price": 29.99, "status": "active"},
            {"sku": "P3", "name": "Yoga Mat", "category": "Sports",
             "brand": "FitGear", "price": 49.99, "status": "active"},
            {"sku": "P4", "name": "Coffee Maker", "category": "Home",
             "brand": "BrewCo", "price": 79.99, "status": "discontinued"},
        ]

    def test_load_and_size(self):
        browser = CatalogBrowser()
        count = browser.load(self._sample_products())
        assert count == 4
        assert browser.size == 4

    def test_browse_all(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse()
        assert result.total == 4
        assert len(result.items) == 4

    def test_browse_with_query(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(query="laptop")
        assert result.total == 1
        assert result.items[0]["sku"] == "P1"

    def test_browse_with_filter(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(filters={"category": "Electronics"})
        assert result.total == 1

    def test_browse_with_price_range(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(filters={"price": {"min": 40, "max": 100}})
        assert all(40 <= item["price"] <= 100 for item in result.items)

    def test_browse_with_list_filter(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(filters={"status": ["active"]})
        assert result.total == 3

    def test_pagination(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(page=1, page_size=2)
        assert len(result.items) == 2
        assert result.total_pages == 2

    def test_sorting(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(sort_by="price", sort_desc=True)
        prices = [item["price"] for item in result.items]
        assert prices == sorted(prices, reverse=True)

    def test_facets(self):
        browser = CatalogBrowser(self._sample_products())
        result = browser.browse(include_facets=True)
        assert len(result.facets) > 0


class TestOfflineOrderProcessor:
    def test_capture_order(self):
        proc = OfflineOrderProcessor()
        order = proc.capture("CUST-1", [
            {"sku": "P1", "price": 10.0, "quantity": 2},
        ])
        assert isinstance(order, OfflineOrder)
        assert order.total == 20.0
        assert proc.queue_size == 1

    def test_sync_success(self):
        proc = OfflineOrderProcessor(sync_fn=lambda o: True)
        proc.capture("C1", [{"sku": "A", "price": 5.0, "quantity": 1}])
        result = proc.sync()
        assert result.synced == 1
        assert result.failed == 0
        assert proc.queue_size == 0

    def test_sync_failure(self):
        def fail_sync(o):
            raise RuntimeError("Network down")
        proc = OfflineOrderProcessor(sync_fn=fail_sync)
        proc.capture("C1", [{"sku": "A", "price": 5.0, "quantity": 1}])
        result = proc.sync()
        assert result.failed == 1
        assert proc.queue_size == 1

    def test_sync_conflict(self):
        def conflict_sync(o):
            raise ValueError("Inventory conflict")
        proc = OfflineOrderProcessor(sync_fn=conflict_sync)
        proc.capture("C1", [{"sku": "A", "price": 5.0, "quantity": 1}])
        result = proc.sync()
        assert result.conflicts == 1

    def test_retry_failed(self):
        call_count = 0
        def retry_sync(o):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Fail first time")
            return True
        proc = OfflineOrderProcessor(sync_fn=retry_sync)
        proc.capture("C1", [{"sku": "A", "price": 5.0, "quantity": 1}])
        proc.sync()
        count = proc.retry_failed()
        assert count == 1
        result = proc.sync()
        assert result.synced == 1

    def test_no_sync_fn_raises(self):
        proc = OfflineOrderProcessor()
        proc.capture("C1", [{"sku": "A", "price": 5.0, "quantity": 1}])
        with pytest.raises(RuntimeError):
            proc.sync()

    def test_order_to_dict(self):
        proc = OfflineOrderProcessor()
        order = proc.capture("C1", [{"sku": "X", "price": 1.0, "quantity": 1}])
        d = order.to_dict()
        assert d["customer_id"] == "C1"
        assert d["status"] == "queued"


class TestDescriptionGenerator:
    def test_generate_standard(self):
        gen = DescriptionGenerator()
        desc = gen.generate("SKU-1", {
            "name": "Widget Pro", "brand": "WidgetCo",
            "description": "A premium widget for professionals.",
            "price": 49.99, "category": "Electronics",
        })
        assert isinstance(desc, ProductDescription)
        assert "Widget Pro" in desc.full_description
        assert len(desc.short_description) <= 160

    def test_generate_minimal(self):
        gen = DescriptionGenerator()
        desc = gen.generate("SKU-2", {
            "name": "Basic Item", "description": "Simple product.",
        }, template_name="minimal")
        assert "Basic Item" in desc.full_description

    def test_bullet_points(self):
        gen = DescriptionGenerator()
        desc = gen.generate("SKU-3", {
            "name": "Gadget", "brand": "GadgetCo",
            "description": "A cool gadget.", "price": 19.99,
            "features": ["Waterproof", "Lightweight", "Durable"],
        })
        assert len(desc.bullet_points) == 3

    def test_unknown_template_raises(self):
        gen = DescriptionGenerator()
        with pytest.raises(ValueError, match="Unknown template"):
            gen.generate("X", {}, template_name="nonexistent")

    def test_add_template(self):
        gen = DescriptionGenerator()
        gen.add_template(DescriptionTemplate(
            name="custom", template="Buy {name} now!",
            required_fields=["name"],
        ))
        desc = gen.generate("SKU-4", {"name": "Thing"}, "custom")
        assert "Buy Thing now!" in desc.full_description

    def test_batch_generate(self):
        gen = DescriptionGenerator()
        products = [
            {"sku": "A", "name": "Alpha", "brand": "B", "description": "D", "price": 10.0},
            {"sku": "B", "name": "Beta", "brand": "B", "description": "D", "price": 20.0},
        ]
        results = gen.batch_generate(products)
        assert len(results) == 2
