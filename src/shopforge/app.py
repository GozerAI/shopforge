"""ShopForge FastAPI application."""

import hashlib
import hmac
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from pydantic import BaseModel

from shopforge.service import CommerceService
from shopforge.provisioning import StorefrontProvisioner

# Resolve frontend directory relative to this file
_FRONTEND_DIR = Path(__file__).parent.parent.parent.parent / "frontend"

logger = logging.getLogger(__name__)
def _setup_logging():
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    env = os.environ.get("ENV", os.environ.get("SHOPFORGE_ENV", "development"))
    if env.lower() == "production":
        fmt = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format=fmt, force=True)


_service: CommerceService | None = None
_provisioner: StorefrontProvisioner | None = None

ZUULTIMATE_BASE_URL = os.environ.get("ZUULTIMATE_BASE_URL", "http://localhost:8000")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")]
SHOPFORGE_SERVICE_TOKEN = os.environ.get("SHOPFORGE_SERVICE_TOKEN", "")


def _validate_env():
    """Warn about development defaults in production."""
    env = os.environ.get("ENV", os.environ.get("SHOPFORGE_ENV", "development"))
    if env.lower() != "production":
        return
    vinzy_server = os.environ.get("VINZY_SERVER", "http://localhost:8080")
    checks = {
        "ZUULTIMATE_BASE_URL": ZUULTIMATE_BASE_URL,
        "VINZY_SERVER": vinzy_server,
        "CORS_ORIGINS": ",".join(CORS_ORIGINS),
    }
    for name, value in checks.items():
        if "localhost" in value or "127.0.0.1" in value:
            logger.warning("PRODUCTION WARNING: %s contains localhost: %s", name, value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    _validate_env()
    global _service, _provisioner
    _service = CommerceService()
    _provisioner = StorefrontProvisioner(
        medusa_storefront=_service._medusa_storefront if hasattr(_service, "_medusa_storefront") else None,
    )
    logger.info("ShopForge started")
    yield
    logger.info("ShopForge shutting down")


app = FastAPI(title="ShopForge", version="0.1.0", lifespan=lifespan)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization", "X-Service-Token"],
)

# Mount static assets and dashboard if the frontend directory exists
_static_dir = _FRONTEND_DIR / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Auth dependency ────────────────────────────────────────────────────────────

async def get_tenant(request: Request) -> dict:
    """Validate bearer token against Zuultimate and return tenant context.

    Also accepts X-Service-Token header for internal service-to-service
    calls (e.g. from Nexus/C-Suite). When a valid service token is
    provided the request bypasses tenant auth and receives full
    entitlements.
    """
    # Service token bypass for internal callers
    service_token = request.headers.get("X-Service-Token", "")
    if SHOPFORGE_SERVICE_TOKEN and service_token and service_token == SHOPFORGE_SERVICE_TOKEN:
        return {
            "tenant_id": "service-internal",
            "plan": "enterprise",
            "entitlements": ["shopforge:basic", "shopforge:full"],
            "status": "active",
            "service_caller": True,
        }

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




SERVICE_TOKEN = os.environ.get("SHOPFORGE_SERVICE_TOKEN", "")


async def get_tenant_or_service(request: Request) -> dict:
    """Allow either bearer token auth or X-Service-Token for internal calls."""
    service_token = request.headers.get("X-Service-Token", "")
    if service_token and SERVICE_TOKEN and service_token == SERVICE_TOKEN:
        return {
            "tenant_id": "service",
            "plan": "enterprise",
            "entitlements": ["shopforge:basic", "shopforge:full"],
            "status": "active",
        }
    return await get_tenant(request)

def _svc() -> CommerceService:
    if _service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _service


# ── Models ─────────────────────────────────────────────────────────────────────

class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthRegisterRequest(BaseModel):
    name: str
    email: str
    password: str


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


class DynamicProvisionRequest(BaseModel):
    name: str
    description: str = ""
    segments: list[str]
    product_types: list[str] = []
    tags: list[str] = []
    theme: str = "default"
    target_audience: str = ""
    markup_percentage: float = 0.0
    deploy_container: bool = True


# ── Frontend pages ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing():
    """Serve the marketing landing page."""
    page = _FRONTEND_DIR / "landing.html"
    if page.exists():
        return FileResponse(str(page), media_type="text/html")
    return HTMLResponse("<h1>Shopforge</h1><p>Landing page not found.</p>", status_code=404)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    """Serve the single-page dashboard."""
    index = _FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return HTMLResponse("<h1>Dashboard not found</h1><p>Run the frontend build step.</p>", status_code=404)


# ── Simple local auth (JWT-free convenience layer for the dashboard) ───────────
# These endpoints issue opaque tokens backed by Zuultimate when available,
# or return a minimal self-signed token for local development.

_local_sessions: dict[str, dict] = {}  # token -> tenant dict (in-memory, dev only)


@app.post("/api/auth/login")
@limiter.limit("20/minute")
async def auth_login(request: Request, body: AuthLoginRequest):
    """
    Login endpoint for the dashboard.

    Attempts to authenticate via Zuultimate. Falls back to a local dev token
    when Zuultimate is unreachable (useful for testing without the auth service).
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{ZUULTIMATE_BASE_URL}/v1/identity/auth/login",
                json={"email": body.email, "password": body.password},
            )
        if resp.status_code == 200:
            data = resp.json()
            access_token = data.get("access_token", "")
            # Validate the token to get tenant context
            validate_resp = await httpx.AsyncClient(timeout=5.0).__aenter__()
            try:
                val = await validate_resp.get(
                    f"{ZUULTIMATE_BASE_URL}/v1/identity/auth/validate",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                tenant = val.json() if val.status_code == 200 else data
            finally:
                await validate_resp.aclose()
            return {"access_token": access_token, "tenant": tenant}
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        raise HTTPException(status_code=502, detail="Auth service error")
    except httpx.RequestError:
        # Zuultimate unreachable — in production this is a hard failure.
        env = os.environ.get("ENV", os.environ.get("SHOPFORGE_ENV", "development"))
        if env.lower() == "production":
            raise HTTPException(status_code=503, detail="Auth service unavailable")
        # Dev/test fallback: issue a local dev token so the dashboard
        # remains usable without the full auth stack running.
        logger.warning("Zuultimate unreachable; issuing local dev session for %s", body.email)
        token = secrets.token_urlsafe(32)
        tenant = {
            "email": body.email,
            "tenant_id": "local-dev",
            "plan": "starter",
            "entitlements": ["shopforge:basic"],
            "status": "active",
        }
        _local_sessions[token] = tenant
        return {"access_token": token, "tenant": tenant}


@app.post("/api/auth/register")
@limiter.limit("10/minute")
async def auth_register(request: Request, body: AuthRegisterRequest):
    """
    Register endpoint for the dashboard.

    Proxies to Zuultimate when available; returns a helpful error when not.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{ZUULTIMATE_BASE_URL}/v1/identity/auth/register",
                json={"name": body.name, "email": body.email, "password": body.password},
            )
        if resp.status_code in (200, 201):
            return resp.json()
        detail = resp.json().get("detail", "Registration failed") if resp.content else "Registration failed"
        raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Auth service unavailable. Please try again later.",
        )


# ── Basic endpoints (shopforge:basic) ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "shopforge", "version": app.version}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe -- checks service layer and Zuultimate dependency."""
    from fastapi.responses import JSONResponse

    checks: dict[str, bool] = {}

    # Check service layer initialized
    checks["service"] = _service is not None

    # Check Zuultimate reachable
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{ZUULTIMATE_BASE_URL}/health")
            checks["zuultimate"] = resp.status_code == 200
    except Exception:
        checks["zuultimate"] = False

    all_ready = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ready else 503,
        content={"ready": all_ready, "checks": checks},
    )


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


@app.get("/v1/storefronts/dynamic")
async def list_dynamic_storefronts(
    tenant: dict = Depends(require_entitlement("shopforge:basic")),
):
    """List dynamically provisioned storefronts."""
    svc = _svc()
    if not hasattr(svc, "_medusa_storefront") or svc._medusa_storefront is None:
        return {"storefronts": []}
    dynamic = svc._medusa_storefront.list_dynamic_storefronts()
    return {"storefronts": [sf.to_dict() for sf in dynamic]}


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
@limiter.limit("30/minute")
async def run_autonomous_analysis(request: Request, tenant: dict = Depends(require_entitlement("shopforge:full"))):
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
    body = await request.body()
    secret = os.environ.get("MEDUSA_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook verification not configured")
    sig = request.headers.get("X-Webhook-Signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    import json as _json
    payload = _json.loads(body)
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




# ── Service-to-service endpoints (Nexus/C-Suite) ──────────────────────────────

class ProvisionStorefrontRequest(BaseModel):
    key: str
    name: Optional[str] = None
    platform: str = "shopify"
    store_url: Optional[str] = None
    access_token: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None


@app.post("/v1/storefronts/provision")
async def provision_storefront(
    body: ProvisionStorefrontRequest,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    """Provision a new storefront (used by C-Suite via Nexus)."""
    svc = _svc()
    if body.platform == "shopify":
        if not body.store_url or not body.access_token:
            raise HTTPException(status_code=400, detail="store_url and access_token required for Shopify")
        success = svc.connect_shopify(
            key=body.key,
            store_url=body.store_url,
            access_token=body.access_token,
            name=body.name,
        )
    elif body.platform == "medusa":
        if not body.base_url:
            raise HTTPException(status_code=400, detail="base_url required for Medusa")
        success = svc.connect_medusa(base_url=body.base_url, api_key=body.api_key)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {body.platform}")

    if not success:
        raise HTTPException(status_code=500, detail="Provisioning failed")
    return {"success": True, "key": body.key, "platform": body.platform}


@app.get("/v1/revenue/summary")
async def get_revenue_summary(
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    """Revenue summary across all storefronts."""
    svc = _svc()
    analytics = await svc.get_all_analytics()
    margin = await svc.get_margin_analysis()
    return {
        "total_inventory_value": analytics["totals"]["total_inventory_value"],
        "total_products": analytics["totals"]["total_products"],
        "gross_margin": margin.get("gross_margin", 0),
        "gross_profit": margin.get("gross_profit", 0),
        "storefronts": len(analytics.get("storefronts", {})),
    }

# -- Provisioning endpoints (Phase 2) -----------------------------------------

@app.post("/v1/storefronts/provision/dynamic")
@limiter.limit("10/minute")
async def provision_dynamic_storefront(
    request: Request,
    body: DynamicProvisionRequest,
    tenant: dict = Depends(require_entitlement("shopforge:full")),
):
    """Provision a new dynamic storefront."""
    if _provisioner is None:
        raise HTTPException(status_code=503, detail="Provisioner not initialized")
    result = await _provisioner.provision(body.model_dump())
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error", "Provisioning failed"))
    return result



# -- Security headers middleware ------------------------------------------------

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("shopforge.app:app", host="0.0.0.0", port=8003)
