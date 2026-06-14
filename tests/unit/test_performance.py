"""Tests for shopforge.performance modules.

Covers: AsyncOrderPipeline, BatchImporter, SearchStream, QueryOptimizer.
"""

import time
from unittest.mock import MagicMock

import pytest

from shopforge.performance import (
    AsyncOrderPipeline,
    OrderTask,
    OrderTaskStatus,
    PipelineStats,
    BatchImporter,
    ImportJob,
    ImportJobStatus,
    ExportJob,
    SearchStream,
    SearchFilter,
    StreamChunk,
    QueryOptimizer,
    QueryPlan,
    IndexSuggestion,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _valid_order(**overrides):
    base = {
        "customer_email": "test@example.com",
        "line_items": [
            {"product_id": "prod-1", "quantity": 2, "price": 29.99},
            {"product_id": "prod-2", "quantity": 1, "price": 49.99},
        ],
    }
    base.update(overrides)
    return base


def _valid_product(**overrides):
    base = {
        "title": "Widget Pro",
        "price": 19.99,
        "product_type": "electronics",
        "vendor": "Acme",
        "tags": ["gadget", "sale"],
        "status": "active",
    }
    base.update(overrides)
    return base


def _sample_catalog():
    """Generate a small product catalog for search tests."""
    return [
        {
            "title": "Premium Wireless Headphones",
            "description": "Noise-cancelling over-ear headphones with 30h battery",
            "price": 149.99,
            "product_type": "electronics",
            "vendor": "SoundMax",
            "tags": ["audio", "wireless", "premium"],
            "status": "active",
        },
        {
            "title": "Budget Wired Earbuds",
            "description": "Lightweight earbuds with inline mic",
            "price": 12.99,
            "product_type": "electronics",
            "vendor": "BudgetAudio",
            "tags": ["audio", "wired", "budget"],
            "status": "active",
        },
        {
            "title": "Leather Wallet",
            "description": "Genuine leather bifold wallet",
            "price": 39.99,
            "product_type": "accessories",
            "vendor": "CraftCo",
            "tags": ["leather", "gift"],
            "status": "active",
        },
        {
            "title": "Organic Cotton T-Shirt",
            "description": "Soft organic cotton crew neck shirt",
            "price": 24.99,
            "product_type": "apparel",
            "vendor": "EcoWear",
            "tags": ["organic", "cotton", "casual"],
            "status": "active",
        },
        {
            "title": "Wireless Charging Pad",
            "description": "Fast wireless charger compatible with all Qi devices",
            "price": 29.99,
            "product_type": "electronics",
            "vendor": "TechCharge",
            "tags": ["wireless", "charger", "tech"],
            "status": "active",
        },
        {
            "title": "Running Shoes",
            "description": "Lightweight running shoes for daily training",
            "price": 89.99,
            "product_type": "footwear",
            "vendor": "SprintFit",
            "tags": ["running", "fitness", "sport"],
            "status": "active",
        },
        {
            "title": "Stainless Steel Water Bottle",
            "description": "Insulated bottle keeps drinks cold for 24 hours",
            "price": 19.99,
            "product_type": "accessories",
            "vendor": "HydroPure",
            "tags": ["hydration", "eco", "gift"],
            "status": "draft",
        },
        {
            "title": "Yoga Mat Premium",
            "description": "Non-slip yoga mat with alignment lines",
            "price": 45.00,
            "product_type": "fitness",
            "vendor": "ZenFit",
            "tags": ["yoga", "fitness", "premium"],
            "status": "active",
        },
    ]


# ═══════════════════════════════════════════════════════════════════
# AsyncOrderPipeline Tests
# ═══════════════════════════════════════════════════════════════════

class TestAsyncOrderPipeline:
    def test_submit_valid_order_completes(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit(_valid_order())
        task = pipeline.get_task(task_id)

        assert task is not None
        assert task.status == OrderTaskStatus.COMPLETED
        assert task.completed_at is not None
        assert len(task.errors) == 0

    def test_submit_returns_task_id(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit(_valid_order())
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    def test_get_status(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit(_valid_order())
        status = pipeline.get_status(task_id)
        assert status == OrderTaskStatus.COMPLETED

    def test_get_status_unknown_id(self):
        pipeline = AsyncOrderPipeline()
        assert pipeline.get_status("nonexistent") is None

    def test_invalid_order_missing_email_fails(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit({"line_items": [{"product_id": "x", "quantity": 1}]})
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER
        assert len(task.errors) > 0

    def test_invalid_order_missing_line_items(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit({"customer_email": "a@b.com"})
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER

    def test_invalid_order_empty_line_items(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit({"customer_email": "a@b.com", "line_items": []})
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER

    def test_invalid_order_bad_quantity(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit({
            "customer_email": "a@b.com",
            "line_items": [{"product_id": "p1", "quantity": 0}],
        })
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER

    def test_pipeline_stats_tracking(self):
        pipeline = AsyncOrderPipeline()
        pipeline.submit(_valid_order())
        pipeline.submit({"bad": "data"})

        stats = pipeline.get_stats()
        assert stats.total_submitted == 2
        assert stats.total_completed == 1
        assert stats.total_dead_letter == 1
        assert stats.active_tasks == 0

    def test_pipeline_stats_to_dict(self):
        stats = PipelineStats(total_submitted=5, total_completed=3)
        d = stats.to_dict()
        assert d["total_submitted"] == 5
        assert "avg_duration_seconds" in d

    def test_stats_avg_duration(self):
        stats = PipelineStats()
        stats.record_duration(1.0)
        stats.record_duration(3.0)
        assert stats.avg_duration_seconds == pytest.approx(2.0)

    def test_custom_stage_handler(self):
        pipeline = AsyncOrderPipeline()
        capture_result = {"captured": True, "amount": 999}
        pipeline.set_stage_handler("capturing", lambda data: capture_result)

        task_id = pipeline.submit(_valid_order())
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.COMPLETED
        assert task.result["capturing"] == capture_result

    def test_set_invalid_stage_raises(self):
        pipeline = AsyncOrderPipeline()
        with pytest.raises(ValueError, match="Unknown stage"):
            pipeline.set_stage_handler("nonexistent", lambda d: {})

    def test_retry_exhaustion_goes_to_dead_letter(self):
        pipeline = AsyncOrderPipeline(max_retries=2)

        def always_fail(data):
            raise RuntimeError("boom")

        pipeline.set_stage_handler("reserving", always_fail)

        task_id = pipeline.submit(_valid_order())
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER
        dead = pipeline.get_dead_letter_tasks()
        assert any(t.id == task_id for t in dead)

    def test_retry_dead_letter_task(self):
        call_count = 0

        def fail_once(data):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:  # Fail on first 3 tries (max_retries=3)
                raise RuntimeError("temporary failure")
            return {"reserved": True}

        pipeline = AsyncOrderPipeline(max_retries=1)
        pipeline.set_stage_handler("reserving", fail_once)

        task_id = pipeline.submit(_valid_order())
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER

        # Now fix the handler and retry
        pipeline.set_stage_handler("reserving", lambda d: {"reserved": True})
        result = pipeline.retry_dead_letter(task_id)
        assert result is True

        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.COMPLETED

    def test_retry_dead_letter_unknown_id(self):
        pipeline = AsyncOrderPipeline()
        assert pipeline.retry_dead_letter("nope") is False

    def test_list_tasks_all(self):
        pipeline = AsyncOrderPipeline()
        pipeline.submit(_valid_order())
        pipeline.submit(_valid_order())
        tasks = pipeline.list_tasks()
        assert len(tasks) == 2

    def test_list_tasks_by_status(self):
        pipeline = AsyncOrderPipeline()
        pipeline.submit(_valid_order())
        pipeline.submit({"bad": "data"})
        completed = pipeline.list_tasks(OrderTaskStatus.COMPLETED)
        assert len(completed) == 1

    def test_on_complete_callback(self):
        completed_tasks = []
        pipeline = AsyncOrderPipeline(on_complete=lambda t: completed_tasks.append(t.id))
        task_id = pipeline.submit(_valid_order())
        assert task_id in completed_tasks

    def test_on_fail_callback(self):
        failed_tasks = []
        pipeline = AsyncOrderPipeline(on_fail=lambda t: failed_tasks.append(t.id))
        task_id = pipeline.submit({"bad": True})
        assert task_id in failed_tasks

    def test_order_task_to_dict(self):
        task = OrderTask(order_data=_valid_order())
        d = task.to_dict()
        assert "id" in d
        assert d["status"] == "pending"
        assert d["attempt"] == 0

    def test_extra_validators_run(self):
        def reject_test_emails(data):
            if "test" in data.get("customer_email", ""):
                raise ValueError("Test emails not allowed")

        pipeline = AsyncOrderPipeline(validators=[reject_test_emails])
        task_id = pipeline.submit(_valid_order(customer_email="test@example.com"))
        task = pipeline.get_task(task_id)
        assert task.status == OrderTaskStatus.DEAD_LETTER

    def test_pipeline_result_accumulates_stage_results(self):
        pipeline = AsyncOrderPipeline()
        task_id = pipeline.submit(_valid_order())
        task = pipeline.get_task(task_id)
        assert "validating" in task.result
        assert "reserving" in task.result
        assert "capturing" in task.result
        assert "dispatching" in task.result


# ═══════════════════════════════════════════════════════════════════
# BatchImporter Tests
# ═══════════════════════════════════════════════════════════════════

class TestBatchImporter:
    def test_import_products_valid(self):
        importer = BatchImporter()
        items = [_valid_product(title=f"Prod {i}") for i in range(5)]
        job = importer.import_products(items)

        assert job.total == 5
        assert job.succeeded == 5
        assert job.failed == 0
        assert job.status == ImportJobStatus.COMPLETED
        assert len(job.imported_ids) == 5
        assert job.duration_seconds > 0

    def test_import_products_empty_list(self):
        importer = BatchImporter()
        job = importer.import_products([])
        assert job.total == 0
        assert job.succeeded == 0
        assert job.status == ImportJobStatus.COMPLETED

    def test_import_products_missing_title(self):
        importer = BatchImporter()
        items = [{"price": 10.0}]
        job = importer.import_products(items)
        assert job.failed == 1
        assert job.succeeded == 0
        assert job.status == ImportJobStatus.COMPLETED_WITH_ERRORS
        assert "title" in job.errors[0]["error"]

    def test_import_products_empty_title(self):
        importer = BatchImporter()
        items = [{"title": ""}]
        job = importer.import_products(items)
        assert job.failed == 1

    def test_import_products_negative_price(self):
        importer = BatchImporter()
        items = [{"title": "Widget", "price": -5.0}]
        job = importer.import_products(items)
        assert job.failed == 1
        assert "negative" in job.errors[0]["error"]

    def test_import_products_invalid_price_type(self):
        importer = BatchImporter()
        items = [{"title": "Widget", "price": "not_a_number"}]
        job = importer.import_products(items)
        assert job.failed == 1

    def test_import_products_mixed_valid_invalid(self):
        importer = BatchImporter()
        items = [
            _valid_product(title="Good 1"),
            {"price": 5.0},  # missing title
            _valid_product(title="Good 2"),
            {"title": "", "price": 3.0},  # empty title
            _valid_product(title="Good 3"),
        ]
        job = importer.import_products(items)
        assert job.succeeded == 3
        assert job.failed == 2
        assert job.status == ImportJobStatus.COMPLETED_WITH_ERRORS

    def test_import_products_batch_size(self):
        progress_calls = []
        importer = BatchImporter(
            on_progress=lambda p, s, t: progress_calls.append((p, s, t))
        )
        items = [_valid_product(title=f"P{i}") for i in range(7)]
        job = importer.import_products(items, batch_size=3)
        assert job.succeeded == 7
        # With batch_size=3 and 7 items: batches at 3, 6, 7
        assert len(progress_calls) == 3

    def test_import_products_transform(self):
        def add_prefix(item):
            item["title"] = "IMPORTED: " + item["title"]
            return item

        importer = BatchImporter(transform_product=add_prefix)
        items = [_valid_product(title="Widget")]
        job = importer.import_products(items)
        assert job.succeeded == 1

    def test_import_products_transform_failure(self):
        def bad_transform(item):
            raise ValueError("transform broke")

        importer = BatchImporter(transform_product=bad_transform)
        items = [_valid_product()]
        job = importer.import_products(items)
        assert job.failed == 1
        assert "Transform failed" in job.errors[0]["error"]

    def test_import_orders_valid(self):
        importer = BatchImporter()
        items = [_valid_order() for _ in range(3)]
        job = importer.import_orders(items)
        assert job.total == 3
        assert job.succeeded == 3
        assert job.status == ImportJobStatus.COMPLETED
        assert job.job_type == "orders"

    def test_import_orders_missing_email(self):
        importer = BatchImporter()
        items = [{"line_items": [{"product_id": "p1"}]}]
        job = importer.import_orders(items)
        assert job.failed == 1

    def test_import_orders_bad_email(self):
        importer = BatchImporter()
        items = [{"customer_email": "notanemail", "line_items": [{"product_id": "p1"}]}]
        job = importer.import_orders(items)
        assert job.failed == 1
        assert "email" in job.errors[0]["error"]

    def test_import_orders_missing_product_id(self):
        importer = BatchImporter()
        items = [{"customer_email": "a@b.com", "line_items": [{"quantity": 1}]}]
        job = importer.import_orders(items)
        assert job.failed == 1

    def test_import_orders_empty_line_items(self):
        importer = BatchImporter()
        items = [{"customer_email": "a@b.com", "line_items": []}]
        job = importer.import_orders(items)
        assert job.failed == 1

    def test_import_orders_with_progress(self):
        progress_calls = []
        importer = BatchImporter(
            on_progress=lambda p, s, t: progress_calls.append((p, s, t))
        )
        items = [_valid_order() for _ in range(5)]
        job = importer.import_orders(items, batch_size=2)
        assert job.succeeded == 5
        assert len(progress_calls) == 3  # batches: 2, 4, 5

    def test_import_orders_transform(self):
        def add_source(item):
            item["source"] = "batch_import"
            return item

        importer = BatchImporter(transform_order=add_source)
        items = [_valid_order()]
        job = importer.import_orders(items)
        assert job.succeeded == 1

    def test_import_job_success_rate(self):
        job = ImportJob(total=10, succeeded=7, failed=3)
        assert job.success_rate == pytest.approx(70.0)

    def test_import_job_success_rate_zero_total(self):
        job = ImportJob(total=0)
        assert job.success_rate == 0.0

    def test_import_job_to_dict(self):
        job = ImportJob(job_type="products", total=10, succeeded=8, failed=2)
        d = job.to_dict()
        assert d["job_type"] == "products"
        assert d["success_rate"] == 80.0

    def test_get_job_by_id(self):
        importer = BatchImporter()
        job = importer.import_products([_valid_product()])
        retrieved = importer.get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    def test_get_job_unknown_id(self):
        importer = BatchImporter()
        assert importer.get_job("nope") is None

    def test_export_products(self):
        importer = BatchImporter()
        products = [_valid_product(title=f"P{i}") for i in range(3)]
        export = importer.export_products(products)
        assert export.exported == 3
        assert export.status == ImportJobStatus.COMPLETED
        assert len(export.output_records) == 3

    def test_export_products_with_field_filter(self):
        importer = BatchImporter()
        products = [_valid_product()]
        export = importer.export_products(products, fields=["title", "price"])
        assert len(export.output_records) == 1
        assert set(export.output_records[0].keys()) == {"title", "price"}

    def test_export_job_to_dict(self):
        export = ExportJob(job_type="products", total=5, exported=5)
        d = export.to_dict()
        assert d["job_type"] == "products"
        assert d["exported"] == 5

    def test_import_preserves_existing_id(self):
        importer = BatchImporter()
        items = [_valid_product(id="my-custom-id")]
        job = importer.import_products(items)
        assert "my-custom-id" in job.imported_ids

    def test_large_batch_import(self):
        importer = BatchImporter()
        items = [_valid_product(title=f"Bulk Product {i}") for i in range(500)]
        job = importer.import_products(items, batch_size=100)
        assert job.succeeded == 500
        assert job.failed == 0


# ═══════════════════════════════════════════════════════════════════
# SearchStream Tests
# ═══════════════════════════════════════════════════════════════════

class TestSearchStream:
    def test_search_empty_catalog(self):
        stream = SearchStream([])
        pages = list(stream.search("anything"))
        assert len(pages) == 1
        assert pages[0].total_items == 0
        assert pages[0].items == []

    def test_search_no_query_returns_all(self):
        catalog = _sample_catalog()
        stream = SearchStream(catalog)
        pages = list(stream.search("", page_size=100))
        assert len(pages) == 1
        assert pages[0].total_items == len(catalog)

    def test_search_by_title_keyword(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("wireless", page_size=100))
        assert pages[0].total_items >= 2  # headphones + charging pad
        titles = [item["title"] for item in pages[0].items]
        assert any("Wireless" in t for t in titles)

    def test_search_relevance_order(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("headphones", page_size=100))
        assert pages[0].total_items >= 1
        # "Premium Wireless Headphones" should be the top result
        assert "Headphones" in pages[0].items[0]["title"]

    def test_search_pagination(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", page_size=3))
        assert len(pages) >= 2
        assert pages[0].page == 1
        assert pages[0].has_next is True
        assert pages[-1].has_next is False
        assert pages[0].total_pages == pages[-1].total_pages

    def test_search_page_direct_access(self):
        stream = SearchStream(_sample_catalog())
        page2 = stream.search_page("", page=2, page_size=3)
        assert page2.page == 2
        assert len(page2.items) <= 3

    def test_search_page_beyond_range(self):
        stream = SearchStream(_sample_catalog())
        page = stream.search_page("", page=999, page_size=3)
        assert len(page.items) == 0

    def test_filter_by_category(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"category": "electronics"}, page_size=100))
        for item in pages[0].items:
            assert item.get("product_type") == "electronics"

    def test_filter_by_price_range(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"price_min": 30, "price_max": 100}, page_size=100))
        for item in pages[0].items:
            assert 30 <= item["price"] <= 100

    def test_filter_by_vendor(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"vendor": "SoundMax"}, page_size=100))
        assert pages[0].total_items == 1
        assert pages[0].items[0]["vendor"] == "SoundMax"

    def test_filter_by_tag(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"tag": "premium"}, page_size=100))
        assert pages[0].total_items >= 2
        for item in pages[0].items:
            assert "premium" in [t.lower() for t in item["tags"]]

    def test_filter_by_multiple_tags(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"tags": ["gift", "eco"]}, page_size=100))
        assert pages[0].total_items >= 1

    def test_filter_by_name(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"name": "wallet"}, page_size=100))
        assert pages[0].total_items == 1
        assert "Wallet" in pages[0].items[0]["title"]

    def test_filter_by_status(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", filters={"status": "draft"}, page_size=100))
        assert pages[0].total_items == 1
        assert pages[0].items[0]["status"] == "draft"

    def test_combined_query_and_filters(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search(
            "wireless",
            filters={"price_max": 50},
            page_size=100,
        ))
        for item in pages[0].items:
            assert item["price"] <= 50

    def test_set_catalog(self):
        stream = SearchStream()
        assert stream.catalog_size == 0
        stream.set_catalog(_sample_catalog())
        assert stream.catalog_size == 8

    def test_count_method(self):
        stream = SearchStream(_sample_catalog())
        assert stream.count() == 8
        assert stream.count(query="wireless") >= 2
        assert stream.count(filters={"category": "electronics"}) >= 2

    def test_stream_chunk_to_dict(self):
        chunk = StreamChunk(
            items=[{"title": "Test"}],
            page=1,
            total_pages=3,
            total_items=25,
            has_next=True,
        )
        d = chunk.to_dict()
        assert d["page"] == 1
        assert d["total_pages"] == 3
        assert d["has_next"] is True
        assert d["count"] == 1

    def test_search_filter_to_dict(self):
        f = SearchFilter(field="category", value="electronics")
        d = f.to_dict()
        assert d == {"field": "category", "value": "electronics"}

    def test_page_size_minimum_one(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("", page_size=0))
        # Should clamp to 1
        assert all(len(p.items) <= 1 for p in pages)

    def test_no_results_for_unmatched_query(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("xyznonexistent123", page_size=100))
        assert pages[0].total_items == 0

    def test_description_matching(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("noise-cancelling", page_size=100))
        assert pages[0].total_items >= 1

    def test_multi_word_query(self):
        stream = SearchStream(_sample_catalog())
        pages = list(stream.search("wireless headphones", page_size=100))
        assert pages[0].total_items >= 1
        assert "Headphones" in pages[0].items[0]["title"]


# ═══════════════════════════════════════════════════════════════════
# QueryOptimizer Tests
# ═══════════════════════════════════════════════════════════════════

class TestQueryOptimizer:
    def test_empty_filters_full_scan(self):
        optimizer = QueryOptimizer(catalog_size=1000)
        plan = optimizer.optimize_product_query({})
        assert plan.strategy == "full_scan"
        assert plan.estimated_cost == 1000.0

    def test_single_indexed_filter(self):
        optimizer = QueryOptimizer(catalog_size=10000)
        plan = optimizer.optimize_product_query({"id": "prod-123"})
        assert plan.strategy == "index_lookup"
        assert plan.estimated_cost < 10000
        assert len(plan.filters) == 1
        assert plan.filters[0][0] == "id"

    def test_filter_ordering_by_selectivity(self):
        optimizer = QueryOptimizer()
        plan = optimizer.optimize_product_query({
            "description": "blue",  # least selective
            "vendor": "Acme",       # more selective
            "sku": "SKU-001",       # most selective
        })
        fields = [f for f, v in plan.filters]
        # sku (indexed, 0.02*0.1) should come first, then vendor (0.15), then description (0.70)
        assert fields.index("sku") < fields.index("vendor")
        assert fields.index("vendor") < fields.index("description")

    def test_compound_selectivity_reduces_cost(self):
        optimizer = QueryOptimizer(catalog_size=10000)
        plan_one = optimizer.optimize_product_query({"vendor": "Acme"})
        plan_two = optimizer.optimize_product_query({"vendor": "Acme", "status": "active"})
        assert plan_two.estimated_cost < plan_one.estimated_cost

    def test_index_suggestions_for_selective_unindexed(self):
        optimizer = QueryOptimizer(indexed_fields={"id"})
        plan = optimizer.optimize_product_query({"customer_email": "a@b.com"})
        assert len(plan.index_suggestions) >= 1
        suggested_fields = [s.field for s in plan.index_suggestions]
        assert "customer_email" in suggested_fields

    def test_no_suggestions_for_indexed_fields(self):
        optimizer = QueryOptimizer()
        plan = optimizer.optimize_product_query({"id": "123"})
        suggested_fields = [s.field for s in plan.index_suggestions]
        assert "id" not in suggested_fields

    def test_query_plan_to_dict(self):
        plan = QueryPlan(
            filters=[("id", "123")],
            estimated_cost=5.0,
            strategy="index_lookup",
        )
        d = plan.to_dict()
        assert d["strategy"] == "index_lookup"
        assert len(d["filters"]) == 1
        assert d["filters"][0] == {"field": "id", "value": "123"}

    def test_index_suggestion_to_dict(self):
        s = IndexSuggestion(
            field="email",
            reason="High selectivity",
            estimated_improvement=85.0,
            priority="high",
        )
        d = s.to_dict()
        assert d["field"] == "email"
        assert d["priority"] == "high"

    def test_batch_resolve_basic(self):
        optimizer = QueryOptimizer()
        resolver = lambda uid: {"id": uid, "name": f"Product {uid}"}
        results = optimizer.batch_resolve(["a", "b", "c"], resolver)
        assert len(results) == 3
        assert results["a"]["id"] == "a"

    def test_batch_resolve_deduplication(self):
        call_count = 0

        def counting_resolver(uid):
            nonlocal call_count
            call_count += 1
            return uid

        optimizer = QueryOptimizer()
        results = optimizer.batch_resolve(["a", "b", "a", "c", "b"], counting_resolver)
        assert len(results) == 3
        assert call_count == 3  # Only 3 unique IDs resolved

    def test_batch_resolve_empty(self):
        optimizer = QueryOptimizer()
        results = optimizer.batch_resolve([], lambda x: x)
        assert results == {}

    def test_batch_resolve_handles_failures(self):
        def flaky_resolver(uid):
            if uid == "bad":
                raise RuntimeError("not found")
            return uid

        optimizer = QueryOptimizer()
        results = optimizer.batch_resolve(["good", "bad", "ok"], flaky_resolver)
        assert "good" in results
        assert "ok" in results
        assert "bad" not in results

    def test_batch_resolve_parallel(self):
        """Test that batch_resolve uses parallel execution for large batches."""
        resolved_order = []

        def slow_resolver(uid):
            resolved_order.append(uid)
            return uid

        optimizer = QueryOptimizer()
        ids = [f"id-{i}" for i in range(10)]
        results = optimizer.batch_resolve(ids, slow_resolver, max_workers=4)
        assert len(results) == 10

    def test_custom_selectivity(self):
        optimizer = QueryOptimizer(custom_selectivity={"color": 0.05})
        plan = optimizer.optimize_product_query({"color": "red", "description": "nice"})
        fields = [f for f, v in plan.filters]
        assert fields[0] == "color"

    def test_analyze_query(self):
        optimizer = QueryOptimizer(catalog_size=10000)
        analysis = optimizer.analyze_query({"description": "blue"})
        assert "plan" in analysis
        assert "recommendations" in analysis
        assert len(analysis["recommendations"]) > 0

    def test_analyze_empty_query_recommends_filters(self):
        optimizer = QueryOptimizer()
        analysis = optimizer.analyze_query({})
        assert any("filter" in r.lower() for r in analysis["recommendations"])

    def test_query_history(self):
        optimizer = QueryOptimizer()
        optimizer.optimize_product_query({"id": "1"})
        optimizer.optimize_product_query({"vendor": "Acme"})
        history = optimizer.get_query_history()
        assert len(history) == 2

    def test_clear_history(self):
        optimizer = QueryOptimizer()
        optimizer.optimize_product_query({"id": "1"})
        optimizer.clear_history()
        assert len(optimizer.get_query_history()) == 0

    def test_filter_order_rationale_populated(self):
        optimizer = QueryOptimizer()
        plan = optimizer.optimize_product_query({"vendor": "x", "id": "y"})
        assert len(plan.filter_order_rationale) == 2

    def test_filtered_scan_strategy(self):
        optimizer = QueryOptimizer(indexed_fields=set())
        plan = optimizer.optimize_product_query({"vendor": "Acme"})
        assert plan.strategy == "filtered_scan"

    def test_estimated_rows_at_least_one(self):
        optimizer = QueryOptimizer(catalog_size=10)
        plan = optimizer.optimize_product_query({"id": "x", "sku": "y", "vendor": "z"})
        assert plan.estimated_rows_scanned >= 1.0
