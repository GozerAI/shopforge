"""Tests for audit logging."""

import json
import pytest
from shopforge.audit import AuditEntry, AuditLog


class TestAuditEntry:
    def test_price_change(self):
        entry = AuditEntry(old_price=10.0, new_price=12.0)
        assert entry.price_change == 2.0

    def test_price_change_pct(self):
        entry = AuditEntry(old_price=100.0, new_price=120.0)
        assert entry.price_change_pct == 20.0

    def test_price_change_none_when_missing(self):
        entry = AuditEntry(old_price=None, new_price=12.0)
        assert entry.price_change is None
        assert entry.price_change_pct is None

    def test_to_dict(self):
        entry = AuditEntry(
            product_id="p1",
            product_title="Widget",
            old_price=10.0,
            new_price=12.0,
            strategy="dynamic",
            actor="CRO",
        )
        d = entry.to_dict()
        assert d["product_id"] == "p1"
        assert d["old_price"] == 10.0
        assert d["new_price"] == 12.0
        assert d["price_change"] == 2.0
        assert d["price_change_pct"] == 20.0
        assert d["actor"] == "CRO"


class TestAuditLog:
    def test_record(self):
        log = AuditLog()
        entry = log.record(product_id="p1", old_price=10.0, new_price=12.0)
        assert entry.product_id == "p1"
        assert len(log.get_entries()) == 1

    def test_record_with_metadata(self):
        log = AuditLog()
        entry = log.record(product_id="p1", old_price=10.0, new_price=12.0, storefront="main")
        assert entry.metadata["storefront"] == "main"

    def test_filter_by_product(self):
        log = AuditLog()
        log.record(product_id="p1", old_price=10.0, new_price=12.0)
        log.record(product_id="p2", old_price=20.0, new_price=22.0)
        entries = log.get_entries(product_id="p1")
        assert len(entries) == 1
        assert entries[0].product_id == "p1"

    def test_filter_by_actor(self):
        log = AuditLog()
        log.record(product_id="p1", actor="CRO")
        log.record(product_id="p2", actor="system")
        entries = log.get_entries(actor="CRO")
        assert len(entries) == 1

    def test_filter_by_action(self):
        log = AuditLog()
        log.record(product_id="p1", action="price_change")
        log.record(product_id="p2", action="strategy_change")
        entries = log.get_entries(action="price_change")
        assert len(entries) == 1

    def test_entries_returned_newest_first(self):
        log = AuditLog()
        log.record(product_id="first")
        log.record(product_id="second")
        entries = log.get_entries()
        assert entries[0].product_id == "second"

    def test_max_entries_eviction(self):
        log = AuditLog(max_entries=5)
        for i in range(10):
            log.record(product_id=f"p{i}")
        assert len(log.get_entries(limit=100)) == 5

    def test_get_summary(self):
        log = AuditLog()
        log.record(product_id="p1", old_price=10.0, new_price=12.0, actor="CRO")
        log.record(product_id="p2", old_price=20.0, new_price=18.0, actor="system")
        summary = log.get_summary()
        assert summary["total_entries"] == 2
        assert summary["price_increases"] == 1
        assert summary["price_decreases"] == 1
        assert summary["actors"]["CRO"] == 1
        assert summary["actors"]["system"] == 1

    def test_get_summary_empty(self):
        log = AuditLog()
        summary = log.get_summary()
        assert summary["total_entries"] == 0

    def test_clear(self):
        log = AuditLog()
        log.record(product_id="p1")
        log.clear()
        assert len(log.get_entries()) == 0

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "audit.json")
        log = AuditLog(persist_path=path)
        log.record(product_id="p1", old_price=10.0, new_price=12.0)
        log.record(product_id="p2", old_price=20.0, new_price=18.0)

        # Load from file
        log2 = AuditLog(persist_path=path)
        entries = log2.get_entries()
        assert len(entries) == 2
