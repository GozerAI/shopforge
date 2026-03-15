"""Premium Support Tier -- Support tiers and upsell logic. Backlog #323."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from shopforge.licensing import license_gate
logger = logging.getLogger(__name__)
ADVANCED_FEATURE = "std.shopforge.advanced"
ENTERPRISE_FEATURE = "std.shopforge.enterprise"
class SupportTier(Enum):
    COMMUNITY = "community"
    BASIC = "basic"
    PRIORITY = "priority"
    ENTERPRISE = "enterprise"
_SUPPORT_PRICING_MONTHLY = {SupportTier.COMMUNITY: 0, SupportTier.BASIC: 4900, SupportTier.PRIORITY: 14900, SupportTier.ENTERPRISE: 49900}
_SUPPORT_SLA = {SupportTier.COMMUNITY: {"response_hours": 72, "channels": ["forum"], "dedicated_rep": False, "onboarding": False},
    SupportTier.BASIC: {"response_hours": 24, "channels": ["email", "forum"], "dedicated_rep": False, "onboarding": False},
    SupportTier.PRIORITY: {"response_hours": 4, "channels": ["email", "chat", "phone"], "dedicated_rep": False, "onboarding": True},
    SupportTier.ENTERPRISE: {"response_hours": 1, "channels": ["email", "chat", "phone", "slack"], "dedicated_rep": True, "onboarding": True}}
@dataclass
class SupportEntitlement:
    """Current support entitlement for a customer."""
    id: str = field(default_factory=lambda: str(uuid4()))
    customer_id: str = ""
    tier: SupportTier = SupportTier.COMMUNITY
    price_monthly_cents: int = 0
    sla: Dict[str, Any] = field(default_factory=dict)
    active: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    tickets_used: int = 0
    tickets_limit: int = 0
    def __post_init__(self):
        if not self.sla: self.sla = _SUPPORT_SLA.get(self.tier, {})
        if self.price_monthly_cents == 0 and self.tier != SupportTier.COMMUNITY:
            self.price_monthly_cents = _SUPPORT_PRICING_MONTHLY.get(self.tier, 0)
        limits = {SupportTier.COMMUNITY: 2, SupportTier.BASIC: 10, SupportTier.PRIORITY: 50, SupportTier.ENTERPRISE: 999}
        if self.tickets_limit == 0: self.tickets_limit = limits.get(self.tier, 2)
    @property
    def can_submit_ticket(self): return self.tickets_used < self.tickets_limit
    def to_dict(self):
        return {"id": self.id, "customer_id": self.customer_id, "tier": self.tier.value, "price_monthly_cents": self.price_monthly_cents, "sla": self.sla, "active": self.active, "tickets_used": self.tickets_used, "tickets_limit": self.tickets_limit, "can_submit_ticket": self.can_submit_ticket, "started_at": self.started_at.isoformat() if self.started_at else None}
@dataclass
class SupportTicket:
    """A support ticket."""
    id: str = field(default_factory=lambda: str(uuid4()))
    customer_id: str = ""
    tier: SupportTier = SupportTier.COMMUNITY
    subject: str = ""
    description: str = ""
    priority: str = "normal"
    status: str = "open"
    channel: str = "email"
    response_due_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    def to_dict(self):
        return {"id": self.id, "customer_id": self.customer_id, "tier": self.tier.value, "subject": self.subject, "priority": self.priority, "status": self.status, "channel": self.channel, "response_due_at": self.response_due_at.isoformat() if self.response_due_at else None, "created_at": self.created_at.isoformat()}
@dataclass
class UpsellRecommendation:
    """A recommendation to upsell a customer to a higher tier."""
    id: str = field(default_factory=lambda: str(uuid4()))
    customer_id: str = ""
    current_tier: SupportTier = SupportTier.COMMUNITY
    recommended_tier: SupportTier = SupportTier.BASIC
    reason: str = ""
    monthly_increase_cents: int = 0
    benefits: List[str] = field(default_factory=list)
    urgency: str = "normal"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    accepted: Optional[bool] = None
    def to_dict(self):
        return {"id": self.id, "customer_id": self.customer_id, "current_tier": self.current_tier.value, "recommended_tier": self.recommended_tier.value, "reason": self.reason, "monthly_increase_cents": self.monthly_increase_cents, "monthly_increase_dollars": self.monthly_increase_cents / 100, "benefits": self.benefits, "urgency": self.urgency, "accepted": self.accepted}
class PremiumSupportManager:
    """Manages support tiers, tickets, and upsell recommendations."""
    def __init__(self):
        self._entitlements: Dict[str, SupportEntitlement] = {}
        self._tickets: Dict[str, SupportTicket] = {}
        self._recommendations: Dict[str, UpsellRecommendation] = {}
        self._mrr_cents: int = 0
    @property
    def mrr_dollars(self): return self._mrr_cents / 100.0
    def get_or_create_entitlement(self, customer_id, tier=None):
        if customer_id in self._entitlements: return self._entitlements[customer_id]
        ent = SupportEntitlement(customer_id=customer_id, tier=tier or SupportTier.COMMUNITY)
        self._entitlements[customer_id] = ent
        if ent.tier != SupportTier.COMMUNITY: self._mrr_cents += ent.price_monthly_cents
        return ent
    def upgrade_tier(self, customer_id, new_tier_value):
        """Upgrade a customer to a higher support tier."""
        license_gate.gate(ADVANCED_FEATURE)
        tier_map = {t.value: t for t in SupportTier}
        new_tier = tier_map.get(new_tier_value)
        if not new_tier: raise ValueError(f"Invalid tier: {new_tier_value}")
        if new_tier == SupportTier.ENTERPRISE: license_gate.gate(ENTERPRISE_FEATURE)
        ent = self.get_or_create_entitlement(customer_id)
        tier_order = list(SupportTier)
        if tier_order.index(new_tier) <= tier_order.index(ent.tier):
            raise ValueError("Cannot downgrade tier")
        old_price = ent.price_monthly_cents
        ent.tier = new_tier
        ent.price_monthly_cents = _SUPPORT_PRICING_MONTHLY.get(new_tier, 0)
        ent.sla = _SUPPORT_SLA.get(new_tier, {})
        limits = {SupportTier.COMMUNITY: 2, SupportTier.BASIC: 10, SupportTier.PRIORITY: 50, SupportTier.ENTERPRISE: 999}
        ent.tickets_limit = limits.get(new_tier, 2)
        self._mrr_cents += (ent.price_monthly_cents - old_price)
        return ent
    def submit_ticket(self, customer_id, subject, description, channel="email", priority="normal"):
        """Submit a support ticket."""
        ent = self.get_or_create_entitlement(customer_id)
        if not ent.can_submit_ticket:
            raise ValueError(f"Ticket limit reached for {ent.tier.value} tier")
        allowed = ent.sla.get("channels", ["forum"])
        if channel not in allowed:
            raise ValueError(f"Channel not available on {ent.tier.value} tier")
        hrs = ent.sla.get("response_hours", 72)
        ticket = SupportTicket(customer_id=customer_id, tier=ent.tier, subject=subject, description=description, priority=priority, channel=channel, response_due_at=datetime.now(timezone.utc) + timedelta(hours=hrs))
        self._tickets[ticket.id] = ticket
        ent.tickets_used += 1
        return ticket
    def resolve_ticket(self, ticket_id):
        ticket = self._tickets.get(ticket_id)
        if not ticket: raise ValueError(f"Ticket not found: {ticket_id}")
        ticket.status = "resolved"
        ticket.resolved_at = datetime.now(timezone.utc)
        return ticket
    def get_customer_tickets(self, customer_id):
        return [t.to_dict() for t in self._tickets.values() if t.customer_id == customer_id]
    def generate_upsell_recommendations(self):
        """Analyze usage patterns and generate upsell recommendations."""
        recs = []
        for cid, ent in self._entitlements.items():
            if ent.tier == SupportTier.ENTERPRISE: continue
            tier_order = list(SupportTier)
            next_idx = tier_order.index(ent.tier) + 1
            if next_idx >= len(tier_order): continue
            next_tier = tier_order[next_idx]
            reasons, benefits = [], []
            urgency = "low"
            usage_pct = ent.tickets_used / max(ent.tickets_limit, 1) * 100
            if usage_pct >= 80:
                reasons.append(f"Used {usage_pct:.0f}% of ticket quota")
                benefits.append("Higher ticket limit")
                urgency = "high"
            elif usage_pct >= 50:
                reasons.append(f"Moderate usage ({usage_pct:.0f}% of quota)")
                urgency = "normal"
            cust_tickets = [t for t in self._tickets.values() if t.customer_id == cid]
            if any(t.priority == "critical" for t in cust_tickets):
                reasons.append("Has critical tickets")
                benefits.append("Faster SLA response")
                urgency = "high"
            next_sla = _SUPPORT_SLA.get(next_tier, {})
            cur_sla = ent.sla
            if next_sla.get("response_hours", 72) < cur_sla.get("response_hours", 72):
                benefits.append(f"{next_sla.get('response_hours')}h response vs {cur_sla.get('response_hours')}h")
            if next_sla.get("dedicated_rep") and not cur_sla.get("dedicated_rep"):
                benefits.append("Dedicated support rep")
            if next_sla.get("onboarding") and not cur_sla.get("onboarding"):
                benefits.append("Guided onboarding")
            new_ch = set(next_sla.get("channels", [])) - set(cur_sla.get("channels", []))
            if new_ch: benefits.append(f"New channels: {', '.join(new_ch)}")
            if not reasons: reasons.append("Proactive upgrade opportunity")
            increase = _SUPPORT_PRICING_MONTHLY.get(next_tier, 0) - ent.price_monthly_cents
            rec = UpsellRecommendation(customer_id=cid, current_tier=ent.tier, recommended_tier=next_tier, reason="; ".join(reasons), monthly_increase_cents=increase, benefits=benefits, urgency=urgency)
            self._recommendations[rec.id] = rec
            recs.append(rec)
        return [r.to_dict() for r in recs]
    def accept_recommendation(self, rec_id):
        rec = self._recommendations.get(rec_id)
        if not rec: raise ValueError(f"Recommendation not found: {rec_id}")
        if rec.accepted is not None: raise ValueError("Already processed")
        rec.accepted = True
        ent = self.upgrade_tier(rec.customer_id, rec.recommended_tier.value)
        return {"success": True, "new_tier": ent.tier.value, "new_price": ent.price_monthly_cents}
    def decline_recommendation(self, rec_id):
        rec = self._recommendations.get(rec_id)
        if not rec: raise ValueError(f"Recommendation not found: {rec_id}")
        rec.accepted = False
        return {"success": True, "recommendation_id": rec_id}
    def get_revenue_report(self):
        active = [e for e in self._entitlements.values() if e.active and e.tier != SupportTier.COMMUNITY]
        return {"mrr_cents": self._mrr_cents, "mrr_dollars": self.mrr_dollars, "arr_dollars": self.mrr_dollars * 12, "paying_customers": len(active), "total_customers": len(self._entitlements), "conversion_rate": len(active) / max(len(self._entitlements), 1) * 100, "by_tier": {t.value: len([e for e in self._entitlements.values() if e.tier == t]) for t in SupportTier}, "total_tickets": len(self._tickets), "open_tickets": len([t for t in self._tickets.values() if t.status == "open"])}
    def get_stats(self):
        return {"total_entitlements": len(self._entitlements), "total_tickets": len(self._tickets), "mrr_dollars": self.mrr_dollars, "by_tier": {t.value: len([e for e in self._entitlements.values() if e.tier == t]) for t in SupportTier}}
