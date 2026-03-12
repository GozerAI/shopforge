# Shopforge

AI-powered e-commerce toolkit — Part of the GozerAI ecosystem.

## Overview

Shopforge provides a unified interface for managing multi-storefront commerce operations. Community tier includes core data models, the service layer, and licensing integration.

## Features (Community Tier)

- **Core data models** — Product, Variant, Order, Storefront, Registry
- **Service layer** — CommerceService unified interface
- **License integration** — Vinzy license gate for feature tiers

Pro and Enterprise tiers unlock advanced commerce features including Shopify/Medusa integration, dynamic pricing, trend analysis, and audit reporting.

Visit [gozerai.com/pricing](https://gozerai.com/pricing) for tier details.

## Installation

```
pip install shopforge
```

For development:

```
pip install -e ".[dev]"
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

## Links

- **Pricing & Licensing**: https://gozerai.com/pricing
- **Documentation**: https://gozerai.com/docs/shopforge
