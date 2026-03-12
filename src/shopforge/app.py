"""ShopForge FastAPI application."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from shopforge.service import CommerceService

logger = logging.getLogger(__name__)

_service: CommerceService | None = None

ZUULTIMATE_BASE_URL = os.environ.get("ZUULTIMATE_BASE_URL", "http://localhost:8000")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service
    _service = CommerceService()
    logger.info("ShopForge started")
    yield
    logger.info("ShopForge shutting down")


app = FastAPI(title="ShopForge", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Auth dependency ────────────────────────────────────────────────────────────

async def get_tenant(request: Request) -> dict:
    """Validate bearer token against Zuultimate and return tenant context."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{ZUULTIMATE_BASE_URL}/v1/identity/auth/validate",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as e:
        logger.error("Zuultimate unreachable: %s", e)
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or expired credentials")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Auth service error")

    return resp.json()


def require_entitlement(entitlement: str):
    """Dependency factory: blocks if tenant lacks the required entitlement."""
    async def _check(tenant: dict = Depends(get_tenant)) -> dict:
        if entitlement not in tenant.get("entitlements", []):
            raise HTTPException(
                status_code=403,
                detail=f"Your plan does not include '{entitlement}'. Upgrade to access this feature.",
            )
        return tenant
    return _check


def _svc() -> CommerceService:
    if _service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _service


# ── Models ─────────────────────────────────────────────────────────────────────

class ConnectShopifyRequest(BaseModel):
    key: str
    store_url: str
    access_token: str
    name: Optional[str] = None
    api_version: str = "2024-01"


class ConnectMedusaRequest(BaseModel):
    base_url: str
    api_key: Optional[str] = None


class PriceUpdateRequest(BaseModel):
    product_id: str
    variant_id: str
    new_price: float
    compare_at_price: Optional[float] = None


class CreateBundleRequest(BaseModel):
    storefront_key: str
    bundle_name: str
    product_ids: list[str]
    discount: float = 0.85


class MedusaOrderRequest(BaseModel):
    source_storefront: str = "medusa"
    email: str
    shipping_address: Optional[dict] = None
    items: list[dict]


# ── Basic endpoints (shopforge:basic) ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "shopforge", "version": app.version}


@app.get("/health/detailed")
async def health_detailed():
    checks = {}
    status = "ok"

    # Service layer check
    try:
        svc = _svc()
        stats = svc.get_stats()
        checks["service"] = {
            "status": "ok",
            "storefronts": stats.get("storefronts", 0),
            "has_shopify": stats.get("has_shopify", False),
            "has_medusa": stats.get("has_medusa", False),
        }
    except Exception as e:
        checks["service"] = {"status": "error", "error": str(e)}
        status = "degraded"

    # Telemetry check
    try:
        svc = _svc()
        telemetry = svc.get_telemetry()
        checks["telemetry"] = {"status": "ok" if telemetry else "unavailable"}
    except Exception:
        checks["telemetry"] = {"status": "unavailable"}

    return {"status": status, "service": "shopforge", "version": app.version, "checks": checks}


@app.get("/v1/storefronts")
async def list_storefronts(tenant: dict = Depends(require_entitlement("shopforge:basic"))):
    return _svc().list_storefronts()


@app.get("/v1/storefronts/{key}")
async def get_storefront(key: str, tenant: dict = Depends(require_entitlement("shopforge:basic"))):
    result = _svc().get_storefront(key)
    if result is None:
        raise HTTPException(status_code=404, detail="Storefront not found")
    return result


@app.post("/v1/storefronts/shopify")
async def connect_shopify(
    body: ConnectShopifyRequest,
    tenant: dict = Depends(require_entitlement("shopforge:basic")),
):
    success = _svc().connect_shopify(
        key=body.key,
        store_url=body.store_url,
        access_token=body.access_token,
        name=body.name,
        api_version=body.api_version,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to connect Shopify storefront")
    return {"success": True, "key": body.key}


@app.post("/v1/storefronts/medusa")
async def connect_medusa(
    body: ConnectMedusaRequest,
    tenant: dict = Depends(require_entitlement("shopforge:basic")),
):
    success = _svc().connect_medusa(base_url=body.base_url, api_key=body.api_key)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to connect Medusa backend")
    return {"success": True}


@app.get("/v1/products/{storefront_key}")
async def get_products(
    storefront_key: str,
    limit: int = Query(100, le=500),
    tenant: dict = Depends(require_entitlement("shopforge:basic")),
):
    try:
        return await _svc().get_products(storefront_key, limit=limit)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/v1/inventory/alerts")
async def get_inventory_alerts(
    threshold: int = Query(10, ge=1),
    tenant: dict = Depends(require_entitlement("shopforge:basic")),
):
    return await _svc().get_inventory_alerts(low_stock_threshold=threshold)


@app.get("/v1/stats")
async def get_stats(tenant: dict = Depends(require_entitlement("shopforge:basic"))):
    return _svc().get_stats()


# ── Pro endpoints (shopforge:full) ─────────────────────────────────────────────

@app.get("/v1/analytics")
async def get_all_analytics(tenant: dict = Depends(require_entitlement("shopforge:full"))):
    return await _svc().get_all_analytics()


@app.get("/v1/analytics/{storefront_key}")
async def get_storefront_analytics(
    storefront_key: str,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().get_storefront_analytics(storefront_key)


@app.post("/v1/pricing/optimize")
async def optimize_pricing(
    storefront_key: str = Query(...),
    target_margin: float = Query(40.0),
    strategy: str = Query("cost_plus"),
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().optimize_pricing(storefront_key, target_margin, strategy)


@app.get("/v1/margins")
async def get_margin_analysis(
    storefront_key: Optional[str] = Query(None),
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().get_margin_analysis(storefront_key)


@app.put("/v1/pricing/update/{storefront_key}")
async def apply_price_update(
    storefront_key: str,
    body: PriceUpdateRequest,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().apply_price_update(
        storefront_key, body.product_id, body.variant_id, body.new_price, body.compare_at_price
    )


@app.post("/v1/sync/medusa")
async def sync_to_medusa(
    source_storefront: str = Query(...),
    target_niche: str = Query(...),
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().sync_to_medusa(source_storefront, target_niche)


# ── Enterprise endpoints (shopforge:full + enterprise gate) ────────────────────

@app.get("/v1/executive/{executive_code}")
async def get_executive_report(
    executive_code: str,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    if executive_code not in ("CRO", "CFO", "CMO", "COO"):
        raise HTTPException(status_code=400, detail="Invalid executive code. Use CRO, CFO, CMO, or COO.")
    return await _svc().get_executive_report(executive_code)


@app.post("/v1/autonomous/analyze")
async def run_autonomous_analysis(tenant: dict = Depends(require_entitlement("shopforge:full"))):
    return await _svc().run_autonomous_analysis()


@app.get("/v1/niche/summary")
async def get_niche_summary(tenant: dict = Depends(require_entitlement("shopforge:full"))):
    return await _svc().get_niche_storefront_summary()


# ── Order routing endpoints ──────────────────────────────────────────────────

@app.post("/v1/orders/from-medusa")
async def create_order_from_medusa(
    body: MedusaOrderRequest,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    result = _svc().create_draft_order_from_medusa(body.model_dump())
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/v1/webhooks/medusa/order-placed")
async def medusa_order_webhook(request: Request):
    payload = await request.json()
    result = _svc().handle_medusa_order_webhook(payload)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Trend endpoints ──────────────────────────────────────────────────────────

@app.get("/v1/trends/enrich/{storefront_key}")
async def enrich_with_trends(
    storefront_key: str,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().enrich_products_with_trends(storefront_key)


@app.get("/v1/trends/analysis")
async def get_trend_analysis(
    storefront_key: Optional[str] = Query(None),
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().get_trend_analysis(storefront_key)


# ── Bundle endpoints ─────────────────────────────────────────────────────────

@app.post("/v1/bundles/create")
async def create_bundle(
    body: CreateBundleRequest,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    return await _svc().create_bundle(
        body.storefront_key, body.bundle_name, body.product_ids, body.discount
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("shopforge.app:app", host="0.0.0.0", port=8003, reload=True)
