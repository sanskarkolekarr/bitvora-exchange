"""
BITVORA EXCHANGE — FastAPI Entry Point (Production)
Slimmed-down API server: lifespan manages only API-relevant workers.
Verification workers run in separate containers via worker_main.py.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse

from config import settings
from utils.middleware import (
    CloudflareMiddleware,
    RateLimitMiddleware,
    MaintenanceMiddleware,
    BodySizeLimitMiddleware,
)
from routes import auth, transaction, status, assets, admin, user, support
from routes.health import router as health_router

# API-relevant workers (stay in the API process)
from services.price_manager import price_manager_worker
from services.price_manager import price_manager_worker

# ═══════════════════════════════════════════════
# Sentry (optional — initialise before app creation)
# ═══════════════════════════════════════════════

try:
    if settings.SENTRY_DSN:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.05,
            profiles_sample_rate=0.01,
            environment=settings.ENVIRONMENT,
            server_name="bitvora-api",
        )
except ImportError:
    pass
except Exception:
    pass

# ═══════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-35s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bitvora.main")


# ═══════════════════════════════════════════════
# Lifespan — API Workers Only
# Verification workers are in worker_main.py (separate container)
# ═══════════════════════════════════════════════

_worker_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start API-relevant workers on startup, cancel on shutdown."""
    logger.info("=" * 60)
    logger.info("  BITVORA EXCHANGE API — Starting Up")
    logger.info("=" * 60)

    # Only API-relevant workers — verification runs in worker-verifier container
    _worker_tasks.extend(
        [
            asyncio.create_task(price_manager_worker(), name="price_manager"),
        ]
    )

    logger.info(f"Started {len(_worker_tasks)} API workers (price_manager, telegram)")
    logger.info("Verification workers run in separate container (worker-verifier)")

    yield

    # Shutdown — cancel all workers
    logger.info("Shutting down API workers...")
    for task in _worker_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Close Redis
    try:
        from services.redis_client import close_redis
        await close_redis()
    except Exception:
        pass

    _worker_tasks.clear()
    logger.info("All API workers stopped. Goodbye.")


# ═══════════════════════════════════════════════
# FastAPI App
# ═══════════════════════════════════════════════

app = FastAPI(
    title="BITVORA Exchange API",
    version="2.0.0",
    # Disable docs in production
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

# ═══════════════════════════════════════════════
# Prometheus Metrics (optional)
# ═══════════════════════════════════════════════

try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
    logger.info("Prometheus metrics enabled at /metrics")
except ImportError:
    logger.info("prometheus-fastapi-instrumentator not installed — metrics disabled")

# ═══════════════════════════════════════════════
# Middleware Stack (order matters — outermost first)
# ═══════════════════════════════════════════════

# GZip compression for responses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS — locked to frontend domain only in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [os.getenv("BITVORA_DOMAIN", "https://bitvoraexchange.com")]
        if settings.is_production
        else ["*"]
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(MaintenanceMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CloudflareMiddleware)
app.add_middleware(BodySizeLimitMiddleware)  # 512KB body guard


# Security Headers Layer (OWASP-compliant)
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME-type sniffing attacks
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Old XSS filter for legacy browsers
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Force HTTPS for 1 year
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    # Content Security Policy
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://unpkg.com https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # Disable camera, microphone, geolocation
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    # Control referrer
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Cloak server identity
    response.headers["Server"] = "BITVORA-SECURE-ENGINE"
    # Remove potentially leaky headers
    if "X-Powered-By" in response.headers:
        del response.headers["X-Powered-By"]
    return response


# ═══════════════════════════════════════════════
# Route Registration
# ═══════════════════════════════════════════════

app.include_router(health_router)  # Health check — exempt from middleware
app.include_router(auth.router)
app.include_router(transaction.router)
app.include_router(status.router)
app.include_router(assets.router)
app.include_router(admin.router)
app.include_router(user.router)
app.include_router(support.router)


# ═══════════════════════════════════════════════
# Global Exception Handler
# ═══════════════════════════════════════════════


from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Catch-all: never expose stack traces in production.
    Log the real error server-side, return generic message.
    """
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)

    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred."},
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )
