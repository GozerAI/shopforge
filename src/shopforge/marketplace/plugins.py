"""Plugin Marketplace -- Premium plugin/extension marketplace. Backlog #312, #429."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from shopforge.licensing import license_gate
logger = logging.getLogger(__name__)
MARKETPLACE_FEATURE = "std.shopforge.advanced"
PREMIUM_PLUGINS_FEATURE = "std.shopforge.enterprise"
class PluginCategory(Enum):
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    SEO = "seo"
    PAYMENTS = "payments"
    SHIPPING = "shipping"
    INVENTORY = "inventory"
    CUSTOMER_SERVICE = "customer_service"
    SOCIAL_COMMERCE = "social_commerce"
    AUTOMATION = "automation"
    SECURITY = "security"
    REPORTING = "reporting"
    INTEGRATION = "integration"
class PluginTier(Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"
_PLUGIN_PRICING_MONTHLY = {PluginTier.FREE: 0, PluginTier.BASIC: 999, PluginTier.PRO: 2999, PluginTier.ENTERPRISE: 9999}
@dataclass
class MarketplacePlugin:
    """A plugin listing in the marketplace."""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    slug: str = ""
    description: str = ""
    category: PluginCategory = PluginCategory.INTEGRATION
    tier: PluginTier = PluginTier.BASIC
    price_monthly_cents: int = 0
    currency: str = "USD"
    features: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    author_name: str = "GozerAI"
    install_count: int = 0
    rating: float = 0.0
    review_count: int = 0
    published: bool = True
    featured: bool = False
    version: str = "1.0.0"
    webhook_events: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    def __post_init__(self):
        if self.price_monthly_cents == 0 and self.tier != PluginTier.FREE:
            self.price_monthly_cents = _PLUGIN_PRICING_MONTHLY.get(self.tier, 0)
    @property
    def price_monthly_dollars(self): return self.price_monthly_cents / 100.0
    @property
    def price_yearly_cents(self): return int(self.price_monthly_cents * 10)
    def to_dict(self):
        return {"id": self.id, "name": self.name, "slug": self.slug, "description": self.description, "category": self.category.value, "tier": self.tier.value, "price_monthly_cents": self.price_monthly_cents, "price_monthly_dollars": self.price_monthly_dollars, "price_yearly_cents": self.price_yearly_cents, "currency": self.currency, "features": self.features, "permissions": self.permissions, "author_name": self.author_name, "install_count": self.install_count, "rating": self.rating, "review_count": self.review_count, "published": self.published, "featured": self.featured, "version": self.version, "created_at": self.created_at.isoformat() if self.created_at else None}
@dataclass
class PluginInstallation:
    """Record of a plugin installation."""
    id: str = field(default_factory=lambda: str(uuid4()))
    plugin_id: str = ""
    plugin_name: str = ""
    storefront_key: str = ""
    buyer_id: str = ""
    billing_cycle: str = "monthly"
    amount_cents: int = 0
    status: str = "active"
    config: Dict[str, Any] = field(default_factory=dict)
    installed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    def to_dict(self):
        return {"id": self.id, "plugin_id": self.plugin_id, "plugin_name": self.plugin_name, "storefront_key": self.storefront_key, "buyer_id": self.buyer_id, "billing_cycle": self.billing_cycle, "amount_cents": self.amount_cents, "status": self.status, "installed_at": self.installed_at.isoformat() if self.installed_at else None}
class PluginMarketplace:
    """Premium plugin marketplace for Shopforge storefronts."""
    def __init__(self):
        self._plugins: Dict[str, MarketplacePlugin] = {}
        self._installations: Dict[str, PluginInstallation] = {}
        self._mrr_cents: int = 0
    @property
    def catalog_size(self): return len([p for p in self._plugins.values() if p.published])
    @property
    def monthly_recurring_revenue_cents(self): return self._mrr_cents
    @property
    def monthly_recurring_revenue_dollars(self): return self._mrr_cents / 100.0
    def add_plugin(self, plugin):
        self._plugins[plugin.id] = plugin
        return plugin.id
    def get_plugin(self, plugin_id): return self._plugins.get(plugin_id)
    def browse(self, category=None, tier=None, sort_by="popular", limit=50):
        """Browse the plugin marketplace."""
        license_gate.gate(MARKETPLACE_FEATURE)
        ps = [p for p in self._plugins.values() if p.published]
        if category:
            try:
                ce = PluginCategory(category)
                ps = [p for p in ps if p.category == ce]
            except ValueError: pass
        if tier:
            try:
                te = PluginTier(tier)
                ps = [p for p in ps if p.tier == te]
            except ValueError: pass
        sort_map = {"popular": (lambda p: p.install_count, True), "newest": (lambda p: p.created_at, True), "price_low": (lambda p: p.price_monthly_cents, False), "rating": (lambda p: p.rating, True)}
        fn, rev = sort_map.get(sort_by, sort_map["popular"])
        ps.sort(key=fn, reverse=rev)
        return [p.to_dict() for p in ps[:limit]]
    def install_plugin(self, plugin_id, storefront_key, buyer_id, billing_cycle="monthly", config=None):
        """Install a plugin on a storefront."""
        license_gate.gate(MARKETPLACE_FEATURE)
        plugin = self._plugins.get(plugin_id)
        if not plugin: raise ValueError(f"Plugin not found: {plugin_id}")
        if plugin.tier == PluginTier.ENTERPRISE: license_gate.gate(PREMIUM_PLUGINS_FEATURE)
        for inst in self._installations.values():
            if inst.plugin_id == plugin_id and inst.storefront_key == storefront_key and inst.status == "active":
                raise ValueError("Plugin already installed on this storefront")
        amount = plugin.price_monthly_cents
        if billing_cycle == "yearly": amount = plugin.price_yearly_cents
        installation = PluginInstallation(plugin_id=plugin_id, plugin_name=plugin.name, storefront_key=storefront_key, buyer_id=buyer_id, billing_cycle=billing_cycle, amount_cents=amount, config=config or {})
        self._installations[installation.id] = installation
        if billing_cycle == "monthly": self._mrr_cents += plugin.price_monthly_cents
        else: self._mrr_cents += plugin.price_monthly_cents
        plugin.install_count += 1
        return installation
    def uninstall_plugin(self, installation_id, reason=""):
        """Uninstall a plugin."""
        inst = self._installations.get(installation_id)
        if not inst: raise ValueError(f"Installation not found: {installation_id}")
        if inst.status != "active": raise ValueError("Plugin not active")
        inst.status = "cancelled"
        plugin = self._plugins.get(inst.plugin_id)
        if plugin:
            self._mrr_cents -= plugin.price_monthly_cents
            if plugin.install_count > 0: plugin.install_count -= 1
        return {"success": True, "installation_id": installation_id, "reason": reason}
    def get_storefront_plugins(self, storefront_key):
        return [inst.to_dict() for inst in self._installations.values() if inst.storefront_key == storefront_key and inst.status == "active"]
    def update_plugin_config(self, installation_id, config):
        """Update plugin configuration."""
        inst = self._installations.get(installation_id)
        if not inst: raise ValueError(f"Installation not found: {installation_id}")
        inst.config.update(config)
        return {"success": True, "config": inst.config}
    def seed_catalog(self):
        """Seed with built-in plugins."""
        _P, _C, _T = MarketplacePlugin, PluginCategory, PluginTier
        items = [
            _P(name="Advanced Analytics", slug="advanced-analytics", description="Deep analytics with cohort analysis and LTV tracking.", category=_C.ANALYTICS, tier=_T.PRO, features=["cohort_analysis", "ltv_tracking", "funnel_analysis", "custom_dashboards"], featured=True, rating=4.8, review_count=89, install_count=1240),
            _P(name="SEO Optimizer", slug="seo-optimizer", description="Automated SEO optimization for product pages.", category=_C.SEO, tier=_T.BASIC, features=["meta_tags", "sitemap", "schema_markup", "keyword_tracking"], rating=4.6, review_count=156, install_count=2100),
            _P(name="Smart Shipping", slug="smart-shipping", description="Multi-carrier shipping with rate optimization.", category=_C.SHIPPING, tier=_T.PRO, features=["multi_carrier", "rate_shopping", "label_generation", "tracking"], featured=True, rating=4.7, review_count=67, install_count=890),
            _P(name="Social Commerce", slug="social-commerce", description="Sell directly on Instagram, TikTok, and Facebook.", category=_C.SOCIAL_COMMERCE, tier=_T.PRO, features=["instagram_shop", "tiktok_shop", "facebook_catalog", "social_checkout"], featured=True, rating=4.5, review_count=112, install_count=1560),
            _P(name="Inventory Sync", slug="inventory-sync", description="Real-time inventory sync across channels.", category=_C.INVENTORY, tier=_T.BASIC, features=["multi_channel_sync", "low_stock_alerts", "reorder_automation"], rating=4.4, review_count=78, install_count=980),
            _P(name="Payment Gateway Pro", slug="payment-gateway-pro", description="Extended payment options with BNPL and crypto.", category=_C.PAYMENTS, tier=_T.ENTERPRISE, features=["bnpl_integration", "crypto_payments", "subscription_billing", "multi_currency"], rating=4.9, review_count=34, install_count=320),
            _P(name="Email Marketing", slug="email-marketing", description="Automated email campaigns and flows.", category=_C.MARKETING, tier=_T.BASIC, features=["drip_campaigns", "abandoned_cart", "segmentation", "templates"], rating=4.3, review_count=201, install_count=2800),
            _P(name="Security Shield", slug="security-shield", description="Advanced fraud detection and security monitoring.", category=_C.SECURITY, tier=_T.PRO, features=["fraud_detection", "bot_protection", "vulnerability_scanning"], rating=4.8, review_count=45, install_count=670),
        ]
        for p in items: self.add_plugin(p)
        return len(items)
    def get_revenue_report(self):
        active = [i for i in self._installations.values() if i.status == "active"]
        cancelled = [i for i in self._installations.values() if i.status == "cancelled"]
        return {"mrr_cents": self._mrr_cents, "mrr_dollars": self.monthly_recurring_revenue_dollars, "arr_dollars": self.monthly_recurring_revenue_dollars * 12, "active_installations": len(active), "cancelled_installations": len(cancelled), "churn_rate": len(cancelled) / max(len(self._installations), 1) * 100, "catalog_size": self.catalog_size}
    def get_stats(self):
        ps = list(self._plugins.values())
        return {"total_plugins": len(ps), "published_plugins": self.catalog_size, "total_installations": len(self._installations), "active_installations": len([i for i in self._installations.values() if i.status == "active"]), "mrr_dollars": self.monthly_recurring_revenue_dollars, "by_tier": {t.value: len([p for p in ps if p.tier == t]) for t in PluginTier}, "by_category": {c.value: len([p for p in ps if p.category == c]) for c in PluginCategory if any(p.category == c for p in ps)}}
