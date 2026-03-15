"""
Premium Template Marketplace.

Full marketplace for storefront templates with listing, purchasing,
creator dashboards, ratings, and revenue sharing.

Backlog item: #301
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from shopforge.licensing import license_gate

logger = logging.getLogger(__name__)

MARKETPLACE_FEATURE = "std.shopforge.advanced"
PREMIUM_TEMPLATES_FEATURE = "std.shopforge.enterprise"


class TemplateCategory(Enum):
    FASHION = "fashion"
    ELECTRONICS = "electronics"
    FOOD_BEVERAGE = "food_beverage"
    HEALTH_BEAUTY = "health_beauty"
    HOME_GARDEN = "home_garden"
    SPORTS = "sports"
    DIGITAL_PRODUCTS = "digital_products"
    JEWELRY = "jewelry"
    GENERAL = "general"
    LUXURY = "luxury"


class TemplateTier(Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    PREMIUM = "premium"


_TEMPLATE_PRICING = {
    TemplateTier.FREE: 0,
    TemplateTier.STARTER: 4900,
    TemplateTier.PRO: 9900,
    TemplateTier.PREMIUM: 19900,
}

# Revenue share: marketplace keeps this %, creator gets the rest
_MARKETPLACE_COMMISSION_PCT = 30


@dataclass
class MarketplaceTemplate:
    """A storefront template listing."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    slug: str = ""
    description: str = ""
    category: TemplateCategory = TemplateCategory.GENERAL
    tier: TemplateTier = TemplateTier.STARTER
    price_cents: int = 0
    currency: str = "USD"
    features: List[str] = field(default_factory=list)
    preview_url: str = ""
    author_id: str = "gozerai"
    author_name: str = "GozerAI"
    install_count: int = 0
    rating: float = 0.0
    review_count: int = 0
    published: bool = True
    featured: bool = False
    version: str = "1.0.0"
    sections: List[str] = field(default_factory=list)
    responsive: bool = True
    customization_options: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.price_cents == 0 and self.tier != TemplateTier.FREE:
            self.price_cents = _TEMPLATE_PRICING.get(self.tier, 0)

    @property
    def price_dollars(self) -> float:
        return self.price_cents / 100.0

    @property
    def commission_cents(self) -> int:
        return int(self.price_cents * _MARKETPLACE_COMMISSION_PCT / 100)

    @property
    def creator_payout_cents(self) -> int:
        return self.price_cents - self.commission_cents

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "category": self.category.value,
            "tier": self.tier.value,
            "price_cents": self.price_cents,
            "price_dollars": self.price_dollars,
            "currency": self.currency,
            "features": self.features,
            "preview_url": self.preview_url,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "install_count": self.install_count,
            "rating": self.rating,
            "review_count": self.review_count,
            "published": self.published,
            "featured": self.featured,
            "version": self.version,
            "sections": self.sections,
            "responsive": self.responsive,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class TemplatePurchase:
    """Record of a template purchase."""

    id: str = field(default_factory=lambda: str(uuid4()))
    template_id: str = ""
    template_name: str = ""
    storefront_key: str = ""
    buyer_id: str = ""
    amount_cents: int = 0
    commission_cents: int = 0
    creator_payout_cents: int = 0
    status: str = "completed"
    purchased_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    activated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "template_name": self.template_name,
            "storefront_key": self.storefront_key,
            "buyer_id": self.buyer_id,
            "amount_cents": self.amount_cents,
            "commission_cents": self.commission_cents,
            "creator_payout_cents": self.creator_payout_cents,
            "status": self.status,
            "purchased_at": self.purchased_at.isoformat() if self.purchased_at else None,
            "activated": self.activated,
        }


@dataclass
class CreatorProfile:
    """Template creator profile for revenue sharing."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    email: str = ""
    templates_published: int = 0
    total_sales: int = 0
    total_revenue_cents: int = 0
    total_payout_cents: int = 0
    pending_payout_cents: int = 0
    commission_rate_pct: int = _MARKETPLACE_COMMISSION_PCT
    active: bool = True
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "templates_published": self.templates_published,
            "total_sales": self.total_sales,
            "total_revenue_cents": self.total_revenue_cents,
            "total_payout_cents": self.total_payout_cents,
            "pending_payout_cents": self.pending_payout_cents,
            "commission_rate_pct": self.commission_rate_pct,
            "active": self.active,
        }


@dataclass
class TemplateReview:
    """User review for a template."""

    id: str = field(default_factory=lambda: str(uuid4()))
    template_id: str = ""
    reviewer_id: str = ""
    rating: float = 5.0
    title: str = ""
    body: str = ""
    verified_purchase: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "reviewer_id": self.reviewer_id,
            "rating": self.rating,
            "title": self.title,
            "body": self.body,
            "verified_purchase": self.verified_purchase,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TemplateMarketplace:
    """Premium template marketplace for Shopforge storefronts."""

    def __init__(self):
        self._templates: Dict[str, MarketplaceTemplate] = {}
        self._purchases: Dict[str, TemplatePurchase] = {}
        self._creators: Dict[str, CreatorProfile] = {}
        self._reviews: Dict[str, TemplateReview] = {}
        self._total_revenue_cents: int = 0
        self._total_commission_cents: int = 0

    @property
    def catalog_size(self) -> int:
        return len([t for t in self._templates.values() if t.published])

    @property
    def total_revenue_dollars(self) -> float:
        return self._total_revenue_cents / 100.0

    @property
    def total_commission_dollars(self) -> float:
        return self._total_commission_cents / 100.0

    def add_template(self, template: MarketplaceTemplate) -> str:
        """Add a template to the marketplace catalog."""
        self._templates[template.id] = template
        # Track creator stats
        if template.author_id not in self._creators:
            self._creators[template.author_id] = CreatorProfile(
                id=template.author_id, name=template.author_name
            )
        self._creators[template.author_id].templates_published += 1
        return template.id

    def get_template(self, template_id: str) -> Optional[MarketplaceTemplate]:
        return self._templates.get(template_id)

    def browse(
        self,
        category: Optional[str] = None,
        tier: Optional[str] = None,
        sort_by: str = "popular",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Browse the template marketplace. Requires Pro license."""
        license_gate.gate(MARKETPLACE_FEATURE)

        templates = [t for t in self._templates.values() if t.published]

        if category:
            try:
                cat_enum = TemplateCategory(category)
                templates = [t for t in templates if t.category == cat_enum]
            except ValueError:
                pass

        if tier:
            try:
                tier_enum = TemplateTier(tier)
                templates = [t for t in templates if t.tier == tier_enum]
            except ValueError:
                pass

        sort_map = {
            "popular": (lambda t: t.install_count, True),
            "newest": (lambda t: t.created_at, True),
            "price_low": (lambda t: t.price_cents, False),
            "price_high": (lambda t: t.price_cents, True),
            "rating": (lambda t: t.rating, True),
        }
        fn, rev = sort_map.get(sort_by, sort_map["popular"])
        templates.sort(key=fn, reverse=rev)
        return [t.to_dict() for t in templates[:limit]]

    def purchase_template(
        self,
        template_id: str,
        storefront_key: str,
        buyer_id: str,
    ) -> TemplatePurchase:
        """Purchase a template for a storefront."""
        license_gate.gate(MARKETPLACE_FEATURE)

        template = self._templates.get(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        if template.tier == TemplateTier.PREMIUM:
            license_gate.gate(PREMIUM_TEMPLATES_FEATURE)

        # Check for duplicate purchase
        for p in self._purchases.values():
            if (
                p.template_id == template_id
                and p.storefront_key == storefront_key
                and p.status == "completed"
            ):
                raise ValueError("Template already purchased for this storefront")

        commission = template.commission_cents
        payout = template.creator_payout_cents

        purchase = TemplatePurchase(
            template_id=template_id,
            template_name=template.name,
            storefront_key=storefront_key,
            buyer_id=buyer_id,
            amount_cents=template.price_cents,
            commission_cents=commission,
            creator_payout_cents=payout,
        )

        self._purchases[purchase.id] = purchase
        self._total_revenue_cents += template.price_cents
        self._total_commission_cents += commission
        template.install_count += 1

        # Update creator earnings
        creator = self._creators.get(template.author_id)
        if creator:
            creator.total_sales += 1
            creator.total_revenue_cents += template.price_cents
            creator.pending_payout_cents += payout

        return purchase

    def activate_template(self, purchase_id: str) -> Dict[str, Any]:
        """Activate a purchased template on the storefront."""
        purchase = self._purchases.get(purchase_id)
        if not purchase:
            raise ValueError(f"Purchase not found: {purchase_id}")
        if purchase.activated:
            raise ValueError("Template already activated")

        purchase.activated = True
        return {
            "success": True,
            "purchase_id": purchase_id,
            "template_id": purchase.template_id,
            "storefront_key": purchase.storefront_key,
        }

    def submit_review(
        self,
        template_id: str,
        reviewer_id: str,
        rating: float,
        title: str = "",
        body: str = "",
    ) -> TemplateReview:
        """Submit a review for a purchased template."""
        template = self._templates.get(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        if rating < 1.0 or rating > 5.0:
            raise ValueError("Rating must be between 1.0 and 5.0")

        # Check if buyer has purchased this template
        verified = any(
            p.template_id == template_id
            and p.buyer_id == reviewer_id
            and p.status == "completed"
            for p in self._purchases.values()
        )

        review = TemplateReview(
            template_id=template_id,
            reviewer_id=reviewer_id,
            rating=rating,
            title=title,
            body=body,
            verified_purchase=verified,
        )

        self._reviews[review.id] = review

        # Recalculate template rating
        template_reviews = [
            r for r in self._reviews.values() if r.template_id == template_id
        ]
        template.review_count = len(template_reviews)
        template.rating = (
            sum(r.rating for r in template_reviews) / len(template_reviews)
        )

        return review

    def get_template_reviews(self, template_id: str) -> List[Dict[str, Any]]:
        """Get all reviews for a template."""
        reviews = [r for r in self._reviews.values() if r.template_id == template_id]
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in reviews]

    def get_storefront_templates(self, storefront_key: str) -> List[Dict[str, Any]]:
        """Get all templates purchased for a storefront."""
        purchases = [
            p
            for p in self._purchases.values()
            if p.storefront_key == storefront_key and p.status == "completed"
        ]
        return [p.to_dict() for p in purchases]

    def get_creator_dashboard(self, creator_id: str) -> Dict[str, Any]:
        """Get creator revenue dashboard."""
        creator = self._creators.get(creator_id)
        if not creator:
            raise ValueError(f"Creator not found: {creator_id}")

        templates = [
            t for t in self._templates.values() if t.author_id == creator_id
        ]
        return {
            "creator": creator.to_dict(),
            "templates": [t.to_dict() for t in templates],
            "total_sales": creator.total_sales,
            "total_revenue_dollars": creator.total_revenue_cents / 100.0,
            "pending_payout_dollars": creator.pending_payout_cents / 100.0,
        }

    def process_creator_payout(self, creator_id: str) -> Dict[str, Any]:
        """Process pending payout for a creator."""
        creator = self._creators.get(creator_id)
        if not creator:
            raise ValueError(f"Creator not found: {creator_id}")

        if creator.pending_payout_cents == 0:
            raise ValueError("No pending payout")

        payout_amount = creator.pending_payout_cents
        creator.total_payout_cents += payout_amount
        creator.pending_payout_cents = 0

        return {
            "success": True,
            "creator_id": creator_id,
            "payout_cents": payout_amount,
            "payout_dollars": payout_amount / 100.0,
        }

    def seed_catalog(self) -> int:
        """Seed with built-in templates."""
        _T, _C, _Tr = MarketplaceTemplate, TemplateCategory, TemplateTier
        items = [
            _T(
                name="Luxe Fashion",
                slug="luxe-fashion",
                description="Premium fashion storefront with lookbook and size guide.",
                category=_C.FASHION,
                tier=_Tr.PRO,
                features=["lookbook", "size_guide", "quick_view", "wishlist"],
                sections=["hero", "featured_collection", "lookbook", "instagram_feed"],
                featured=True,
                rating=4.8,
                review_count=120,
                install_count=1850,
            ),
            _T(
                name="Tech Hub",
                slug="tech-hub",
                description="Modern electronics store with comparison tables and spec sheets.",
                category=_C.ELECTRONICS,
                tier=_Tr.PRO,
                features=["comparison_table", "spec_sheets", "3d_preview", "reviews"],
                sections=["hero", "deals", "categories", "comparison"],
                rating=4.6,
                review_count=89,
                install_count=1420,
            ),
            _T(
                name="Fresh Market",
                slug="fresh-market",
                description="Clean food & beverage storefront with recipe integration.",
                category=_C.FOOD_BEVERAGE,
                tier=_Tr.STARTER,
                features=["recipe_integration", "nutritional_info", "subscription_box"],
                sections=["hero", "featured_products", "recipes", "about"],
                rating=4.4,
                review_count=67,
                install_count=980,
            ),
            _T(
                name="Minimal",
                slug="minimal",
                description="Free minimalist template for any product category.",
                category=_C.GENERAL,
                tier=_Tr.FREE,
                features=["responsive", "minimal_design"],
                sections=["hero", "products", "about"],
                rating=4.2,
                review_count=210,
                install_count=5200,
            ),
            _T(
                name="Diamond Elite",
                slug="diamond-elite",
                description="Ultra-premium template for luxury and jewelry brands.",
                category=_C.LUXURY,
                tier=_Tr.PREMIUM,
                features=[
                    "parallax_hero",
                    "virtual_try_on",
                    "appointment_booking",
                    "vip_access",
                    "custom_animations",
                ],
                sections=["parallax_hero", "collection", "virtual_try_on", "vip", "gallery"],
                featured=True,
                rating=4.9,
                review_count=34,
                install_count=280,
            ),
            _T(
                name="Wellness Pro",
                slug="wellness-pro",
                description="Health & beauty storefront with ingredient highlights.",
                category=_C.HEALTH_BEAUTY,
                tier=_Tr.PRO,
                features=["ingredient_explorer", "before_after", "quiz_funnel", "subscriptions"],
                sections=["hero", "bestsellers", "ingredients", "testimonials"],
                rating=4.7,
                review_count=56,
                install_count=760,
            ),
        ]
        for t in items:
            self.add_template(t)
        return len(items)

    def get_featured(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get featured templates."""
        featured = [
            t for t in self._templates.values() if t.published and t.featured
        ]
        featured.sort(key=lambda t: t.rating, reverse=True)
        return [t.to_dict() for t in featured[:limit]]

    def get_revenue_report(self) -> Dict[str, Any]:
        """Get marketplace revenue report."""
        completed_purchases = [
            p for p in self._purchases.values() if p.status == "completed"
        ]
        refunded_purchases = [
            p for p in self._purchases.values() if p.status == "refunded"
        ]

        return {
            "total_revenue_cents": self._total_revenue_cents,
            "total_revenue_dollars": self.total_revenue_dollars,
            "total_commission_cents": self._total_commission_cents,
            "total_commission_dollars": self.total_commission_dollars,
            "total_purchases": len(completed_purchases),
            "refunded_purchases": len(refunded_purchases),
            "catalog_size": self.catalog_size,
            "avg_template_price_cents": (
                self._total_revenue_cents // max(len(completed_purchases), 1)
            ),
            "by_tier": {
                tier.value: len(
                    [t for t in self._templates.values() if t.tier == tier]
                )
                for tier in TemplateTier
            },
            "by_category": {
                cat.value: len(
                    [
                        t
                        for t in self._templates.values()
                        if t.category == cat and t.published
                    ]
                )
                for cat in TemplateCategory
                if any(t.category == cat for t in self._templates.values())
            },
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_templates": len(self._templates),
            "published_templates": self.catalog_size,
            "total_purchases": len(self._purchases),
            "total_reviews": len(self._reviews),
            "total_creators": len(self._creators),
            "revenue_dollars": self.total_revenue_dollars,
            "commission_dollars": self.total_commission_dollars,
        }
