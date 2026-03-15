"""Template-based product description generator.

Generates product descriptions from structured data using configurable
templates. No LLM or network required -- pure string interpolation with
optional rule-based enhancement (adjective injection, bullet formatting).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DescriptionTemplate:
    """A named description template with placeholders."""
    name: str
    template: str
    required_fields: List[str] = field(default_factory=list)
    style: str = "paragraph"

    def validate(self, data: Dict[str, Any]) -> List[str]:
        """Return list of missing required fields."""
        return [f for f in self.required_fields if f not in data or not data[f]]


@dataclass
class ProductDescription:
    """Generated description output."""
    sku: str
    template_name: str
    short_description: str
    full_description: str
    bullet_points: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "template_name": self.template_name,
            "short_description": self.short_description,
            "full_description": self.full_description,
            "bullet_points": self.bullet_points,
        }


DEFAULT_TEMPLATES: List[DescriptionTemplate] = [
    DescriptionTemplate(
        name="standard",
        template=(
            "Introducing the {name} by {brand}. "
            "{description} "
            "Available in {category} for ${price:.2f}."
        ),
        required_fields=["name", "brand", "description", "price"],
        style="paragraph",
    ),
    DescriptionTemplate(
        name="minimal",
        template="{name} - {description}",
        required_fields=["name", "description"],
        style="short",
    ),
    DescriptionTemplate(
        name="detailed",
        template=(
            "{name} by {brand}\n\n"
            "{description}\n\n"
            "Category: {category}\n"
            "Price: \n"
            "Features: {features}"
        ),
        required_fields=["name", "brand", "description", "price"],
        style="paragraph",
    ),
]

_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::([^}]+))?\}")

_QUALITY_ADJECTIVES = {
    "Electronics": ["high-performance", "precision-engineered", "cutting-edge"],
    "Clothing": ["premium", "comfortable", "stylish"],
    "Home & Garden": ["elegant", "durable", "beautifully crafted"],
    "Sports & Outdoors": ["rugged", "lightweight", "professional-grade"],
    "Health & Beauty": ["nourishing", "gentle", "dermatologist-tested"],
    "Food & Beverage": ["artisanal", "naturally sourced", "delicious"],
}


class DescriptionGenerator:
    """Generates product descriptions from templates and product data."""

    def __init__(self, templates: Optional[List[DescriptionTemplate]] = None,
                 max_short_length: int = 160,
                 inject_adjectives: bool = True):
        self._templates = {t.name: t for t in (templates or DEFAULT_TEMPLATES)}
        self._max_short = max_short_length
        self._inject_adj = inject_adjectives

    def add_template(self, template: DescriptionTemplate) -> None:
        self._templates[template.name] = template

    def _interpolate(self, template_str: str, data: Dict[str, Any]) -> str:
        """Replace {field} and {field:format} placeholders."""
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            fmt = match.group(2)
            val = data.get(key, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            if fmt:
                try:
                    return format(val, fmt)
                except (ValueError, TypeError):
                    return str(val)
            return str(val)
        return _PLACEHOLDER_RE.sub(replacer, template_str)

    def _make_bullets(self, data: Dict[str, Any]) -> List[str]:
        """Extract bullet points from features or highlights fields."""
        bullets: List[str] = []
        for key in ("features", "highlights", "specs"):
            val = data.get(key)
            if isinstance(val, list):
                bullets.extend(str(v) for v in val if v)
            elif isinstance(val, str) and val:
                bullets.extend(line.strip("- ") for line in val.split("\n") if line.strip())
        return bullets

    def _inject_category_adjective(self, text: str, category: str) -> str:
        if not self._inject_adj:
            return text
        adjectives = _QUALITY_ADJECTIVES.get(category, [])
        if not adjectives:
            return text
        adj = adjectives[hash(text) % len(adjectives)]
        pattern = re.compile(r"(the|a|an)\s+", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            pos = match.end()
            return text[:pos] + adj + " " + text[pos:]
        return text

    def _truncate(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        truncated = text[:max_len - 3].rsplit(" ", 1)[0]
        return truncated + "..."

    def generate(self, sku: str, data: Dict[str, Any],
                 template_name: str = "standard") -> ProductDescription:
        """Generate a product description from structured data."""
        template = self._templates.get(template_name)
        if template is None:
            raise ValueError(f"Unknown template: {template_name}")

        missing = template.validate(data)
        if missing:
            logger.warning("SKU %s: missing fields %s for template %s",
                          sku, missing, template_name)

        full = self._interpolate(template.template, data)
        category = data.get("category", "")
        if category:
            full = self._inject_category_adjective(full, category)

        bullets = self._make_bullets(data)
        short = self._truncate(full.split("\n")[0], self._max_short)

        return ProductDescription(
            sku=sku,
            template_name=template_name,
            short_description=short,
            full_description=full,
            bullet_points=bullets,
        )

    def batch_generate(self, products: List[Dict[str, Any]],
                       template_name: str = "standard") -> List[ProductDescription]:
        """Generate descriptions for multiple products."""
        results: List[ProductDescription] = []
        for prod in products:
            sku = prod.get("sku", "unknown")
            desc = self.generate(sku, prod, template_name)
            results.append(desc)
        return results
