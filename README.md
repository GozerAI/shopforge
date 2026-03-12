# Shopforge

**Multi-storefront commerce toolkit with dynamic pricing and margin analysis.**

Part of the [GozerAI](https://gozerai.com) ecosystem.

## Overview

Shopforge provides a unified interface for managing multiple e-commerce storefronts. It includes a product registry, storefront management, inventory alerts, and statistics -- all with zero external dependencies at the library layer. Pro and Enterprise tiers add Shopify/Medusa integration, dynamic pricing, trend enrichment, and audit logging.

## Installation

```bash
pip install shopforge
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

```python
from shopforge import CommerceService

service = CommerceService()

# Register a storefront
service.register_storefront(
    key="main_store",
    name="Main Store",
    platform="generic",
)

# Add a product
service.add_product(
    storefront_key="main_store",
    name="Widget Pro",
    sku="WGT-001",
    price=29.99,
    cost=12.00,
)

# Check inventory alerts (low stock / out of stock)
alerts = service.get_inventory_alerts()

# Get storefront statistics
stats = service.get_stats()
```

## Feature Tiers

| Feature | Community | Pro | Enterprise |
|---|:---:|:---:|:---:|
| Storefront registry | x | x | x |
| Product management | x | x | x |
| Inventory alerts | x | x | x |
| Basic statistics | x | x | x |
| Shopify Admin API integration | | x | x |
| Medusa backend integration | | x | x |
| Dynamic pricing engine (8 strategies) | | x | x |
| Margin analysis and recommendations | | x | x |
| Trend enrichment | | x | x |
| Bundle creation | | x | x |
| Niche storefront architecture | | x | x |
| Executive reports (CRO, CFO, CMO, COO) | | x | x |
| Autonomous analysis | | x | x |
| Audit logging | | | x |

### Gated Features

Pro and Enterprise features require a license key. Set the `VINZY_LICENSE_KEY` environment variable or visit [gozerai.com/pricing](https://gozerai.com/pricing) to upgrade.

## API Endpoints

Start the API server:

```bash
uvicorn shopforge.app:app --host 0.0.0.0 --port 8002
```

### Community (shopforge:basic)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/v1/storefronts` | List storefronts |
| GET | `/v1/storefronts/{key}` | Storefront detail |
| POST | `/v1/storefronts/shopify` | Register Shopify storefront |
| POST | `/v1/storefronts/medusa` | Register Medusa storefront |
| GET | `/v1/products/{storefront_key}` | List products |
| GET | `/v1/inventory/alerts` | Inventory alerts |
| GET | `/v1/stats` | Service statistics |

### Pro (shopforge:full)

| Method | Path | Description |
|---|---|---|
| GET | `/v1/analytics` | Portfolio analytics |
| GET | `/v1/analytics/{storefront_key}` | Storefront analytics |
| POST | `/v1/pricing/optimize` | Run pricing optimization |
| GET | `/v1/margins` | Margin analysis |
| PUT | `/v1/pricing/update/{storefront_key}` | Apply pricing changes |
| POST | `/v1/sync/medusa` | Sync Medusa catalog |
| GET | `/v1/executive/{code}` | Executive report |
| POST | `/v1/autonomous/analyze` | Autonomous analysis cycle |
| GET | `/v1/niche/summary` | Niche segment summary |
| POST | `/v1/orders/from-medusa` | Import Medusa orders |
| POST | `/v1/webhooks/medusa/order-placed` | Medusa order webhook |
| GET | `/v1/trends/enrich/{storefront_key}` | Trend enrichment |
| GET | `/v1/trends/analysis` | Trend analysis |
| POST | `/v1/bundles/create` | Create product bundle |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ZUULTIMATE_BASE_URL` | `http://localhost:8000` | Auth service URL |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `VINZY_LICENSE_KEY` | (empty) | License key for Pro/Enterprise features |
| `VINZY_SERVER` | `http://localhost:8080` | License validation server |

## Requirements

- Python >= 3.10
- No external dependencies for the library (stdlib only)
- FastAPI + httpx + slowapi for the API server

## License

MIT License. See [LICENSE](LICENSE) for details.
