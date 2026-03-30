# Shopforge

Multi-storefront commerce toolkit with Shopify and Medusa integration, dynamic pricing, and margin analysis.

## Overview

Shopforge provides a unified interface for managing multiple e-commerce storefronts across platforms. It connects a central Shopify fulfillment hub with niche Medusa-powered storefronts, offering dynamic pricing optimization and portfolio-level margin analysis -- all with zero external dependencies.

## Features

- **Multi-storefront management** -- Register, connect, and manage storefronts across Shopify and Medusa from a single service layer
- **Shopify Admin API client** -- Full product, collection, order, and inventory management
- **Medusa backend integration** -- Niche storefronts connected to a central Shopify fulfillment hub with automatic product filtering
- **Niche storefront architecture** -- Eight pre-configured segments (tech, wellness, fashion, pets, outdoor, eco, creative, productivity)
- **Dynamic pricing engine** -- Eight strategies: cost-plus, competitive, value-based, dynamic, loss-leader, premium, bundle, penetration
- **Margin analysis** -- Analyze margins at the product, storefront, or portfolio level with health categorization
- **Pricing recommendations** -- Actionable suggestions sorted by revenue impact with configurable thresholds
- **Inventory alerts** -- Low-stock and out-of-stock detection across all connected storefronts
- **Executive reports** -- Role-specific reports for CRO, CFO, CMO, and COO

## Installation

```
pip install shopforge
```

For development:

```
pip install -e ".[dev]"
```

## Quick Start

```python
import asyncio
from shopforge import CommerceService

service = CommerceService()

# Connect a Shopify storefront
service.connect_shopify(
    key="main_store",
    store_url="mystore.myshopify.com",
    access_token="shpat_xxxxx",
    name="Main Store",
)

# Get pricing recommendations
recommendations = asyncio.run(service.optimize_pricing(
    storefront_key="main_store",
    target_margin=40.0,
    strategy="cost_plus",
))

# Analyze margins
margin_report = asyncio.run(service.get_margin_analysis())
```

## Architecture

```
src/shopforge/
    core.py      Data models (Product, Variant, Order, Storefront, Registry)
    shopify.py   Shopify Admin API client and storefront manager
    medusa.py    Medusa client, niche storefront definitions and filtering
    pricing.py   Pricing engine, margin analyzer, recommendation generator
    service.py   CommerceService -- unified interface for all operations
```

## Running Tests

```
pytest tests/ -v
```

## Requirements

- Python >= 3.10
- No external dependencies (stdlib only)

## License

MIT License. See [LICENSE](LICENSE) for details.

## Author

Chris Arseno
