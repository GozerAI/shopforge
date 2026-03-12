#!/usr/bin/env bash
# export_public.sh — Creates a clean public export of Shopforge for GozerAI/shopforge.
# Usage: bash scripts/export_public.sh [target_dir]
#
# Strips proprietary Pro/Enterprise modules and internal infrastructure,
# leaving only community-tier code + the license gate (so users see the upgrade path).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-${REPO_ROOT}/../shopforge-public-export}"

echo "=== Shopforge Public Export ==="
echo "Source: ${REPO_ROOT}"
echo "Target: ${TARGET}"

# Clean target
rm -rf "${TARGET}"
mkdir -p "${TARGET}"

# Use git archive to get a clean copy (respects .gitignore, excludes .git)
cd "${REPO_ROOT}"
git archive HEAD | tar -x -C "${TARGET}"

# ===== STRIP PROPRIETARY MODULES =====

# Pro tier — advanced commerce features
rm -f "${TARGET}/src/shopforge/trends.py"
rm -f "${TARGET}/src/shopforge/pricing.py"
rm -f "${TARGET}/src/shopforge/medusa.py"
rm -f "${TARGET}/src/shopforge/shopify.py"

# Enterprise tier — enterprise reporting
rm -f "${TARGET}/src/shopforge/audit.py"

# ===== STRIP TESTS FOR PROPRIETARY MODULES =====
rm -f "${TARGET}/tests/unit/test_trends.py"
rm -f "${TARGET}/tests/unit/test_dynamic_pricing.py"
rm -f "${TARGET}/tests/unit/test_audit.py"
rm -f "${TARGET}/tests/unit/test_order_router.py"
rm -f "${TARGET}/tests/unit/test_rate_limiter.py"
rm -f "${TARGET}/tests/unit/test_service.py"

# ===== CREATE STUB FILES FOR STRIPPED MODULES =====

for mod in trends pricing medusa shopify audit; do
    cat > "${TARGET}/src/shopforge/${mod}.py" << 'PYEOF'
"""This module requires a commercial license.

Visit https://gozerai.com/pricing for Pro and Enterprise tier details.
Set VINZY_LICENSE_KEY to unlock licensed features.
"""

raise ImportError(
    f"{__name__} requires a commercial Shopforge license. "
    "Visit https://gozerai.com/pricing for details."
)
PYEOF
done

# ===== SANITIZE README =====
cat > "${TARGET}/README.md" << 'MDEOF'
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
MDEOF

echo ""
echo "=== Export complete: ${TARGET} ==="
echo ""
echo "Community-tier modules included:"
echo "  __init__, app, core, licensing, service"
echo ""
echo "Stripped (Pro/Enterprise):"
echo "  trends, pricing, medusa, shopify, audit"
