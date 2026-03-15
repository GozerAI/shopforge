"""Tests for the premium template marketplace."""

import pytest

from shopforge.marketplace.templates import (
    TemplateMarketplace,
    MarketplaceTemplate,
    TemplateCategory,
    TemplateTier,
    TemplatePurchase,
    CreatorProfile,
    TemplateReview,
    _TEMPLATE_PRICING,
    _MARKETPLACE_COMMISSION_PCT,
)


@pytest.fixture
def marketplace():
    return TemplateMarketplace()


@pytest.fixture
def sample_template():
    return MarketplaceTemplate(
        name="Test Template",
        slug="test-template",
        description="A test template",
        category=TemplateCategory.FASHION,
        tier=TemplateTier.PRO,
        features=["lookbook", "wishlist"],
        author_id="creator-1",
        author_name="Test Creator",
    )


@pytest.fixture
def seeded_marketplace(marketplace):
    marketplace.seed_catalog()
    return marketplace


# --- MarketplaceTemplate dataclass ---


class TestMarketplaceTemplate:
    def test_auto_pricing_from_tier(self):
        t = MarketplaceTemplate(tier=TemplateTier.PRO)
        assert t.price_cents == _TEMPLATE_PRICING[TemplateTier.PRO]

    def test_free_tier_zero_price(self):
        t = MarketplaceTemplate(tier=TemplateTier.FREE)
        assert t.price_cents == 0

    def test_explicit_price_overrides_tier(self):
        t = MarketplaceTemplate(tier=TemplateTier.PRO, price_cents=5000)
        assert t.price_cents == 5000

    def test_price_dollars(self):
        t = MarketplaceTemplate(tier=TemplateTier.STARTER)
        assert t.price_dollars == _TEMPLATE_PRICING[TemplateTier.STARTER] / 100.0

    def test_commission_calculation(self):
        t = MarketplaceTemplate(tier=TemplateTier.PRO)
        expected = int(t.price_cents * _MARKETPLACE_COMMISSION_PCT / 100)
        assert t.commission_cents == expected

    def test_creator_payout(self):
        t = MarketplaceTemplate(tier=TemplateTier.PRO)
        assert t.creator_payout_cents == t.price_cents - t.commission_cents

    def test_to_dict_keys(self):
        t = MarketplaceTemplate(name="X", slug="x")
        d = t.to_dict()
        assert "id" in d
        assert d["name"] == "X"
        assert d["slug"] == "x"
        assert "price_cents" in d
        assert "price_dollars" in d
        assert "category" in d

    def test_all_categories_defined(self):
        assert len(TemplateCategory) >= 10

    def test_all_tiers_defined(self):
        assert len(TemplateTier) == 4


# --- TemplateMarketplace ---


class TestTemplateMarketplace:
    def test_add_template(self, marketplace, sample_template):
        tid = marketplace.add_template(sample_template)
        assert marketplace.get_template(tid) is sample_template

    def test_catalog_size(self, marketplace, sample_template):
        marketplace.add_template(sample_template)
        assert marketplace.catalog_size == 1

    def test_unpublished_not_in_catalog(self, marketplace):
        t = MarketplaceTemplate(published=False)
        marketplace.add_template(t)
        assert marketplace.catalog_size == 0

    def test_browse_returns_published(self, seeded_marketplace):
        results = seeded_marketplace.browse()
        assert len(results) > 0
        assert all(r["published"] for r in results)

    def test_browse_filter_category(self, seeded_marketplace):
        results = seeded_marketplace.browse(category="fashion")
        assert all(r["category"] == "fashion" for r in results)

    def test_browse_filter_tier(self, seeded_marketplace):
        results = seeded_marketplace.browse(tier="free")
        assert all(r["tier"] == "free" for r in results)

    def test_browse_sort_by_price_low(self, seeded_marketplace):
        results = seeded_marketplace.browse(sort_by="price_low")
        prices = [r["price_cents"] for r in results]
        assert prices == sorted(prices)

    def test_browse_sort_by_rating(self, seeded_marketplace):
        results = seeded_marketplace.browse(sort_by="rating")
        ratings = [r["rating"] for r in results]
        assert ratings == sorted(ratings, reverse=True)

    def test_browse_limit(self, seeded_marketplace):
        results = seeded_marketplace.browse(limit=2)
        assert len(results) <= 2

    def test_seed_catalog(self, marketplace):
        count = marketplace.seed_catalog()
        assert count >= 6
        assert marketplace.catalog_size >= 6


class TestTemplatePurchase:
    def test_purchase_template(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        purchase = seeded_marketplace.purchase_template(tid, "store-1", "buyer-1")
        assert purchase.template_id == tid
        assert purchase.status == "completed"
        assert purchase.amount_cents > 0 or purchase.amount_cents == 0

    def test_purchase_increments_install_count(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        before = seeded_marketplace.get_template(tid).install_count
        seeded_marketplace.purchase_template(tid, "store-1", "buyer-1")
        after = seeded_marketplace.get_template(tid).install_count
        assert after == before + 1

    def test_duplicate_purchase_raises(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        seeded_marketplace.purchase_template(tid, "store-1", "buyer-1")
        with pytest.raises(ValueError, match="already purchased"):
            seeded_marketplace.purchase_template(tid, "store-1", "buyer-1")

    def test_purchase_nonexistent_raises(self, seeded_marketplace):
        with pytest.raises(ValueError, match="not found"):
            seeded_marketplace.purchase_template("bad-id", "s", "b")

    def test_activate_template(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        purchase = seeded_marketplace.purchase_template(tid, "s", "b")
        result = seeded_marketplace.activate_template(purchase.id)
        assert result["success"] is True

    def test_activate_twice_raises(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        purchase = seeded_marketplace.purchase_template(tid, "s", "b")
        seeded_marketplace.activate_template(purchase.id)
        with pytest.raises(ValueError, match="already activated"):
            seeded_marketplace.activate_template(purchase.id)

    def test_revenue_tracking(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        paid = [t for t in templates if t["price_cents"] > 0]
        if paid:
            seeded_marketplace.purchase_template(paid[0]["id"], "s1", "b1")
            assert seeded_marketplace.total_revenue_dollars > 0
            assert seeded_marketplace.total_commission_dollars > 0

    def test_storefront_templates(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        seeded_marketplace.purchase_template(tid, "store-abc", "b1")
        results = seeded_marketplace.get_storefront_templates("store-abc")
        assert len(results) == 1


class TestTemplateReviews:
    def test_submit_review(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        review = seeded_marketplace.submit_review(tid, "user-1", 4.5, "Great!", "Love it")
        assert review.rating == 4.5
        assert review.template_id == tid

    def test_review_updates_template_rating(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        seeded_marketplace.submit_review(tid, "u1", 5.0)
        seeded_marketplace.submit_review(tid, "u2", 3.0)
        t = seeded_marketplace.get_template(tid)
        assert t.review_count == 2
        assert t.rating == pytest.approx(4.0, abs=0.01)

    def test_review_invalid_rating_raises(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        with pytest.raises(ValueError, match="between 1.0 and 5.0"):
            seeded_marketplace.submit_review(tid, "u1", 6.0)

    def test_verified_purchase_flag(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        seeded_marketplace.purchase_template(tid, "s1", "buyer-1")
        review = seeded_marketplace.submit_review(tid, "buyer-1", 5.0)
        assert review.verified_purchase is True

    def test_non_buyer_review_not_verified(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        review = seeded_marketplace.submit_review(tid, "random-user", 5.0)
        assert review.verified_purchase is False

    def test_get_template_reviews(self, seeded_marketplace):
        templates = seeded_marketplace.browse()
        tid = templates[0]["id"]
        seeded_marketplace.submit_review(tid, "u1", 5.0)
        seeded_marketplace.submit_review(tid, "u2", 4.0)
        reviews = seeded_marketplace.get_template_reviews(tid)
        assert len(reviews) == 2


class TestCreatorDashboard:
    def test_creator_auto_created(self, marketplace, sample_template):
        marketplace.add_template(sample_template)
        dashboard = marketplace.get_creator_dashboard("creator-1")
        assert dashboard["creator"]["name"] == "Test Creator"

    def test_creator_sales_tracked(self, marketplace, sample_template):
        marketplace.add_template(sample_template)
        marketplace.purchase_template(sample_template.id, "s1", "b1")
        dashboard = marketplace.get_creator_dashboard("creator-1")
        assert dashboard["total_sales"] == 1
        assert dashboard["total_revenue_dollars"] > 0

    def test_creator_payout(self, marketplace, sample_template):
        marketplace.add_template(sample_template)
        marketplace.purchase_template(sample_template.id, "s1", "b1")
        result = marketplace.process_creator_payout("creator-1")
        assert result["success"] is True
        assert result["payout_cents"] > 0

    def test_creator_payout_clears_pending(self, marketplace, sample_template):
        marketplace.add_template(sample_template)
        marketplace.purchase_template(sample_template.id, "s1", "b1")
        marketplace.process_creator_payout("creator-1")
        dashboard = marketplace.get_creator_dashboard("creator-1")
        assert dashboard["pending_payout_dollars"] == 0

    def test_no_pending_payout_raises(self, marketplace, sample_template):
        marketplace.add_template(sample_template)
        with pytest.raises(ValueError, match="No pending payout"):
            marketplace.process_creator_payout("creator-1")


class TestMarketplaceReports:
    def test_revenue_report(self, seeded_marketplace):
        report = seeded_marketplace.get_revenue_report()
        assert "total_revenue_cents" in report
        assert "catalog_size" in report
        assert "by_tier" in report
        assert "by_category" in report

    def test_stats(self, seeded_marketplace):
        stats = seeded_marketplace.get_stats()
        assert stats["published_templates"] > 0
        assert "revenue_dollars" in stats
        assert "total_creators" in stats

    def test_featured_templates(self, seeded_marketplace):
        featured = seeded_marketplace.get_featured()
        assert len(featured) > 0
        assert all(r["featured"] for r in featured)
