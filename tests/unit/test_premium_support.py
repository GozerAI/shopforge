"""Tests for premium support tier upsell."""

import pytest

from shopforge.marketplace.premium_support import (
    PremiumSupportManager,
    SupportTier,
    SupportTicket,
    SupportEntitlement,
    UpsellRecommendation,
)


@pytest.fixture
def manager():
    return PremiumSupportManager()


class TestSupportEntitlement:
    def test_community_entitlement(self, manager):
        ent = manager.get_or_create_entitlement("c1")
        assert ent.tier == SupportTier.COMMUNITY
        assert ent.tickets_limit == 2

    def test_basic_entitlement(self, manager):
        ent = manager.get_or_create_entitlement("c1", tier=SupportTier.BASIC)
        assert ent.tier == SupportTier.BASIC
        assert ent.tickets_limit == 10

    def test_get_existing_entitlement(self, manager):
        ent1 = manager.get_or_create_entitlement("c1")
        ent2 = manager.get_or_create_entitlement("c1")
        assert ent1.id == ent2.id


class TestSupportTickets:
    def test_submit_ticket(self, manager):
        manager.get_or_create_entitlement("c1", tier=SupportTier.BASIC)
        ticket = manager.submit_ticket("c1", "Help", "Need help", "email")
        assert ticket.status == "open"
        assert ticket.response_due_at is not None

    def test_ticket_limit_enforced(self, manager):
        manager.get_or_create_entitlement("c1")  # community: 2 tickets
        manager.submit_ticket("c1", "T1", "D", "forum")
        manager.submit_ticket("c1", "T2", "D", "forum")
        with pytest.raises(ValueError, match="Ticket limit"):
            manager.submit_ticket("c1", "T3", "D", "forum")

    def test_channel_restriction(self, manager):
        manager.get_or_create_entitlement("c1")  # community: forum only
        with pytest.raises(ValueError, match="Channel not available"):
            manager.submit_ticket("c1", "T1", "D", "phone")

    def test_resolve_ticket(self, manager):
        manager.get_or_create_entitlement("c1", tier=SupportTier.BASIC)
        ticket = manager.submit_ticket("c1", "T", "D", "email")
        resolved = manager.resolve_ticket(ticket.id)
        assert resolved.status == "resolved"

    def test_get_customer_tickets(self, manager):
        manager.get_or_create_entitlement("c1", tier=SupportTier.BASIC)
        manager.submit_ticket("c1", "T1", "D", "email")
        manager.submit_ticket("c1", "T2", "D", "email")
        tickets = manager.get_customer_tickets("c1")
        assert len(tickets) == 2


class TestSupportUpgrade:
    def test_upgrade_tier(self, manager):
        manager.get_or_create_entitlement("c1")
        ent = manager.upgrade_tier("c1", "basic")
        assert ent.tier == SupportTier.BASIC

    def test_upgrade_tracks_mrr(self, manager):
        manager.get_or_create_entitlement("c1")
        manager.upgrade_tier("c1", "basic")
        assert manager.mrr_dollars > 0

    def test_downgrade_raises(self, manager):
        manager.get_or_create_entitlement("c1", tier=SupportTier.PRIORITY)
        with pytest.raises(ValueError, match="Cannot downgrade"):
            manager.upgrade_tier("c1", "basic")


class TestUpsellRecommendations:
    def test_generate_recommendations(self, manager):
        manager.get_or_create_entitlement("c1")
        recs = manager.generate_upsell_recommendations()
        assert len(recs) > 0
        assert recs[0]["current_tier"] == "community"

    def test_high_usage_high_urgency(self, manager):
        ent = manager.get_or_create_entitlement("c1", tier=SupportTier.BASIC)
        # Use 9/10 tickets
        for i in range(9):
            manager.submit_ticket("c1", f"T{i}", "D", "email")
        recs = manager.generate_upsell_recommendations()
        c1_recs = [r for r in recs if r["customer_id"] == "c1"]
        assert any(r["urgency"] == "high" for r in c1_recs)

    def test_accept_recommendation(self, manager):
        manager.get_or_create_entitlement("c1")
        recs = manager.generate_upsell_recommendations()
        rec_id = recs[0]["id"]
        result = manager.accept_recommendation(rec_id)
        assert result["success"] is True
        assert result["new_tier"] == "basic"

    def test_decline_recommendation(self, manager):
        manager.get_or_create_entitlement("c1")
        recs = manager.generate_upsell_recommendations()
        rec_id = recs[0]["id"]
        result = manager.decline_recommendation(rec_id)
        assert result["success"] is True

    def test_double_accept_raises(self, manager):
        manager.get_or_create_entitlement("c1")
        recs = manager.generate_upsell_recommendations()
        rec_id = recs[0]["id"]
        manager.accept_recommendation(rec_id)
        with pytest.raises(ValueError, match="Already processed"):
            manager.accept_recommendation(rec_id)

    def test_enterprise_no_recommendations(self, manager):
        manager.get_or_create_entitlement("c1", tier=SupportTier.ENTERPRISE)
        recs = manager.generate_upsell_recommendations()
        c1_recs = [r for r in recs if r["customer_id"] == "c1"]
        assert len(c1_recs) == 0


class TestRevenueReport:
    def test_revenue_report_structure(self, manager):
        manager.get_or_create_entitlement("c1", tier=SupportTier.BASIC)
        report = manager.get_revenue_report()
        assert "mrr_cents" in report
        assert "paying_customers" in report
        assert "by_tier" in report

    def test_stats(self, manager):
        stats = manager.get_stats()
        assert "total_entitlements" in stats
        assert "mrr_dollars" in stats
