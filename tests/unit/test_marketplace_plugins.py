"""Tests for the premium plugin marketplace."""

import pytest

from shopforge.marketplace.plugins import (
    PluginMarketplace,
    MarketplacePlugin,
    PluginCategory,
    PluginTier,
    PluginInstallation,
)


@pytest.fixture
def marketplace():
    return PluginMarketplace()


@pytest.fixture
def seeded_marketplace(marketplace):
    marketplace.seed_catalog()
    return marketplace


@pytest.fixture
def sample_plugin():
    return MarketplacePlugin(
        name="Test Plugin",
        slug="test-plugin",
        category=PluginCategory.ANALYTICS,
        tier=PluginTier.PRO,
        features=["dashboard", "export"],
    )


class TestMarketplacePlugin:
    def test_auto_pricing(self):
        p = MarketplacePlugin(tier=PluginTier.PRO)
        assert p.price_monthly_cents == 2999

    def test_free_tier_zero(self):
        p = MarketplacePlugin(tier=PluginTier.FREE)
        assert p.price_monthly_cents == 0

    def test_yearly_price(self):
        p = MarketplacePlugin(tier=PluginTier.PRO)
        assert p.price_yearly_cents == int(p.price_monthly_cents * 10)

    def test_to_dict(self):
        p = MarketplacePlugin(name="X")
        d = p.to_dict()
        assert d["name"] == "X"
        assert "price_monthly_dollars" in d


class TestPluginMarketplace:
    def test_add_plugin(self, marketplace, sample_plugin):
        pid = marketplace.add_plugin(sample_plugin)
        assert marketplace.get_plugin(pid) is sample_plugin

    def test_catalog_size(self, seeded_marketplace):
        assert seeded_marketplace.catalog_size >= 8

    def test_browse(self, seeded_marketplace):
        results = seeded_marketplace.browse()
        assert len(results) > 0

    def test_browse_filter_category(self, seeded_marketplace):
        results = seeded_marketplace.browse(category="analytics")
        assert all(r["category"] == "analytics" for r in results)

    def test_browse_filter_tier(self, seeded_marketplace):
        results = seeded_marketplace.browse(tier="basic")
        assert all(r["tier"] == "basic" for r in results)

    def test_browse_sort_price_low(self, seeded_marketplace):
        results = seeded_marketplace.browse(sort_by="price_low")
        prices = [r["price_monthly_cents"] for r in results]
        assert prices == sorted(prices)

    def test_install_plugin(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        pid = plugins[0]["id"]
        inst = seeded_marketplace.install_plugin(pid, "store-1", "buyer-1")
        assert inst.plugin_id == pid
        assert inst.status == "active"

    def test_install_duplicate_raises(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        pid = plugins[0]["id"]
        seeded_marketplace.install_plugin(pid, "store-1", "buyer-1")
        with pytest.raises(ValueError, match="already installed"):
            seeded_marketplace.install_plugin(pid, "store-1", "buyer-1")

    def test_install_nonexistent_raises(self, marketplace):
        with pytest.raises(ValueError, match="not found"):
            marketplace.install_plugin("bad", "s", "b")

    def test_uninstall_plugin(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        pid = plugins[0]["id"]
        inst = seeded_marketplace.install_plugin(pid, "store-1", "buyer-1")
        result = seeded_marketplace.uninstall_plugin(inst.id)
        assert result["success"] is True

    def test_uninstall_inactive_raises(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        pid = plugins[0]["id"]
        inst = seeded_marketplace.install_plugin(pid, "store-1", "buyer-1")
        seeded_marketplace.uninstall_plugin(inst.id)
        with pytest.raises(ValueError, match="not active"):
            seeded_marketplace.uninstall_plugin(inst.id)

    def test_storefront_plugins(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        pid = plugins[0]["id"]
        seeded_marketplace.install_plugin(pid, "store-xyz", "b")
        results = seeded_marketplace.get_storefront_plugins("store-xyz")
        assert len(results) == 1

    def test_update_config(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        pid = plugins[0]["id"]
        inst = seeded_marketplace.install_plugin(pid, "s", "b")
        result = seeded_marketplace.update_plugin_config(inst.id, {"key": "val"})
        assert result["config"]["key"] == "val"

    def test_mrr_tracking(self, seeded_marketplace):
        plugins = seeded_marketplace.browse()
        paid = [p for p in plugins if p["price_monthly_cents"] > 0]
        if paid:
            seeded_marketplace.install_plugin(paid[0]["id"], "s1", "b1")
            assert seeded_marketplace.monthly_recurring_revenue_cents > 0

    def test_revenue_report(self, seeded_marketplace):
        report = seeded_marketplace.get_revenue_report()
        assert "mrr_cents" in report
        assert "active_installations" in report

    def test_stats(self, seeded_marketplace):
        stats = seeded_marketplace.get_stats()
        assert stats["published_plugins"] > 0
        assert "by_tier" in stats
