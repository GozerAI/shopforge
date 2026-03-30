"""Keyword-based product categorization with taxonomy support.

Scores products against a configurable category taxonomy using weighted
keyword matching on name, description, and tag fields.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class CategoryMatch:
    """A single category match result."""
    category: str
    subcategory: str
    score: float
    matched_keywords: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "subcategory": self.subcategory,
            "score": round(self.score, 4),
            "matched_keywords": self.matched_keywords,
        }


@dataclass
class CategoryTaxonomy:
    """Hierarchical category definition with keywords."""
    name: str
    subcategories: Dict[str, List[str]] = field(default_factory=dict)

    def all_keywords(self) -> Set[str]:
        kw: Set[str] = set()
        for keywords in self.subcategories.values():
            kw.update(k.lower() for k in keywords)
        return kw


DEFAULT_TAXONOMY: List[CategoryTaxonomy] = [
    CategoryTaxonomy(
        name="Electronics",
        subcategories={
            "Computers": ["laptop", "desktop", "pc", "computer", "notebook", "chromebook"],
            "Mobile": ["phone", "smartphone", "tablet", "ipad", "cellular", "mobile"],
            "Audio": ["headphone", "speaker", "earbuds", "soundbar", "microphone", "audio"],
            "Accessories": ["charger", "cable", "adapter", "case", "mount", "stand"],
        },
    ),
    CategoryTaxonomy(
        name="Clothing",
        subcategories={
            "Tops": ["shirt", "blouse", "sweater", "hoodie", "jacket", "coat", "top"],
            "Bottoms": ["pants", "jeans", "shorts", "skirt", "trousers", "leggings"],
            "Footwear": ["shoe", "boot", "sneaker", "sandal", "slipper", "heel"],
            "Accessories": ["hat", "scarf", "glove", "belt", "tie", "watch", "jewelry"],
        },
    ),
    CategoryTaxonomy(
        name="Home & Garden",
        subcategories={
            "Furniture": ["chair", "table", "desk", "sofa", "couch", "bed", "shelf"],
            "Kitchen": ["knife", "pan", "pot", "blender", "mixer", "cookware", "utensil"],
            "Garden": ["plant", "seed", "soil", "pot", "garden", "lawn", "mower", "hose"],
            "Decor": ["lamp", "rug", "curtain", "pillow", "vase", "candle", "frame"],
        },
    ),
    CategoryTaxonomy(
        name="Sports & Outdoors",
        subcategories={
            "Fitness": ["dumbbell", "treadmill", "yoga", "mat", "resistance", "weight"],
            "Outdoor": ["tent", "backpack", "hiking", "camping", "sleeping bag", "compass"],
            "Team Sports": ["ball", "bat", "racket", "goal", "jersey", "cleat"],
            "Water Sports": ["kayak", "paddle", "wetsuit", "snorkel", "swim", "surfboard"],
        },
    ),
    CategoryTaxonomy(
        name="Health & Beauty",
        subcategories={
            "Skincare": ["moisturizer", "serum", "cleanser", "sunscreen", "cream", "lotion"],
            "Haircare": ["shampoo", "conditioner", "brush", "dryer", "straightener", "gel"],
            "Wellness": ["vitamin", "supplement", "protein", "probiotic", "omega", "collagen"],
        },
    ),
    CategoryTaxonomy(
        name="Food & Beverage",
        subcategories={
            "Snacks": ["chip", "cookie", "candy", "nut", "bar", "cracker", "popcorn"],
            "Beverages": ["coffee", "tea", "juice", "water", "soda", "energy drink", "wine"],
            "Pantry": ["flour", "sugar", "oil", "sauce", "spice", "pasta", "rice", "grain"],
        },
    ),
]

_WORD_RE = re.compile(r"[a-z0-9]+")


class ProductCategorizer:
    """Categorizes products by scoring keyword overlap against a taxonomy.

    Weights: name matches score 3x, description 1x, tags 2x.
    """

    NAME_WEIGHT = 3.0
    DESC_WEIGHT = 1.0
    TAG_WEIGHT = 2.0

    def __init__(self, taxonomy: Optional[List[CategoryTaxonomy]] = None,
                 min_score: float = 1.0):
        self._taxonomy = taxonomy or DEFAULT_TAXONOMY
        self._min_score = min_score

    def _tokenize(self, text: str) -> Set[str]:
        return set(_WORD_RE.findall(text.lower()))

    def categorize(self, name: str, description: str = "",
                   tags: Optional[List[str]] = None) -> List[CategoryMatch]:
        """Return ranked list of matching categories for a product."""
        name_tokens = self._tokenize(name)
        desc_tokens = self._tokenize(description)
        tag_tokens = self._tokenize(" ".join(tags)) if tags else set()

        matches: List[CategoryMatch] = []

        for cat in self._taxonomy:
            for subcat, keywords in cat.subcategories.items():
                score = 0.0
                matched: List[str] = []
                for kw in keywords:
                    kw_lower = kw.lower()
                    kw_tokens = set(kw_lower.split())
                    hit = False
                    if kw_tokens & name_tokens:
                        score += self.NAME_WEIGHT
                        hit = True
                    if kw_tokens & desc_tokens:
                        score += self.DESC_WEIGHT
                        hit = True
                    if kw_tokens & tag_tokens:
                        score += self.TAG_WEIGHT
                        hit = True
                    if hit:
                        matched.append(kw_lower)
                if score >= self._min_score:
                    matches.append(CategoryMatch(
                        category=cat.name,
                        subcategory=subcat,
                        score=score,
                        matched_keywords=matched,
                    ))

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    def best_match(self, name: str, description: str = "",
                   tags: Optional[List[str]] = None) -> Optional[CategoryMatch]:
        """Return the single best category match, or None."""
        matches = self.categorize(name, description, tags)
        return matches[0] if matches else None

    def batch_categorize(self, products: List[Dict[str, Any]]) -> Dict[str, List[CategoryMatch]]:
        """Categorize multiple products.

        Each product dict should have: sku, name, description (opt), tags (opt).
        Returns {sku: [CategoryMatch, ...]}.
        """
        results: Dict[str, List[CategoryMatch]] = {}
        for prod in products:
            sku = prod["sku"]
            matches = self.categorize(
                name=prod.get("name", ""),
                description=prod.get("description", ""),
                tags=prod.get("tags"),
            )
            results[sku] = matches
        return results
