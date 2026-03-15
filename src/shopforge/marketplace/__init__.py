"""
Shopforge Marketplace — Premium template and plugin marketplace.

Provides template marketplace, plugin marketplace, and premium support
tier upsell logic for revenue generation. All marketplace features are
gated behind LicenseGate entitlements.

Backlog items: #301, #312, #323, #429
"""

from shopforge.marketplace.templates import (
    TemplateMarketplace,
    MarketplaceTemplate,
    TemplateCategory,
    TemplateTier,
    TemplatePurchase,
)
from shopforge.marketplace.plugins import (
    PluginMarketplace,
    MarketplacePlugin,
    PluginCategory,
    PluginTier,
    PluginInstallation,
)
from shopforge.marketplace.premium_support import (
    PremiumSupportManager,
    SupportTier,
    SupportTicket,
    SupportEntitlement,
    UpsellRecommendation,
)

__all__ = [
    # Templates
    "TemplateMarketplace",
    "MarketplaceTemplate",
    "TemplateCategory",
    "TemplateTier",
    "TemplatePurchase",
    # Plugins
    "PluginMarketplace",
    "MarketplacePlugin",
    "PluginCategory",
    "PluginTier",
    "PluginInstallation",
    # Premium Support
    "PremiumSupportManager",
    "SupportTier",
    "SupportTicket",
    "SupportEntitlement",
    "UpsellRecommendation",
]
