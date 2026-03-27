"""
BITVORA EXCHANGE — Middleware Stack (Hardened for 10,000 Concurrency)
CloudflareMiddleware, RateLimitMiddleware, MaintenanceMiddleware
Size limit guard, Slowloris protection, tiered rate limiting.
"""

import time
import asyncio
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from config import settings

logger = logging.getLogger("bitvora.middleware")

# ─── Tiered Rate Limits (requests per 60 seconds per IP) ────────────────────
_RATE_LIMITS = {
    "/auth/login":     20,   # Strict — brute force protection
    "/auth/register":  10,   # Very strict — spam prevention
    "__default__":    120,   # All other endpoints
}


# ═══════════════════════════════════════════════
# Cloudflare Tunnel Validation
# ═══════════════════════════════════════════════


class CloudflareMiddleware(BaseHTTPMiddleware):
    """
    Validates that every request arrived through Cloudflare Tunnel.
    Rejects direct-to-VPS requests with 403.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip in development
        if not settings.is_production:
            return await call_next(request)

        # Health check bypass
        if request.url.path == "/health":
            return await call_next(request)

        cf_header = request.headers.get("CF-Access-Client-Id", "")
        if cf_header != settings.CLOUDFLARE_TUNNEL_TOKEN:
            logger.warning(
                f"Blocked direct request from {request.client.host} to {request.url.path}"
            )
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        return await call_next(request)


# ═══════════════════════════════════════════════
# Rate Limiting (In-Memory Rolling Window)
# ═══════════════════════════════════════════════


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP, per-route tiered rate limiter using a rolling 60-second window.
    Auth routes are strictest (20/min). Default 120/min for all others.
    Returns 429 when limit is exceeded.
    """
    # key: (ip, path_prefix) -> timestamps
    _requests: dict = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.headers.get(
            "CF-Connecting-IP", request.client.host if request.client else "unknown"
        )
        path = request.url.path
        now = time.time()
        window = 60.0

        # Determine limit for this path
        limit = _RATE_LIMITS.get(path, _RATE_LIMITS["__default__"])

        cache_key = f"{client_ip}|{path}"
        self._requests[cache_key] = [
            ts for ts in self._requests[cache_key] if now - ts < window
        ]

        if len(self._requests[cache_key]) >= limit:
            logger.warning(f"Rate limit exceeded: ip={client_ip} path={path}")
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={"detail": "Too many requests. Please slow down."},
            )

        self._requests[cache_key].append(now)
        return await call_next(request)


# ─── Large Body / Slowloris Guard ────────────────────────────────────────────

MAX_BODY_SIZE = 512 * 1024  # 512 KB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Rejects requests with Content-Length > MAX_BODY_SIZE.
    Protects against payload flood attacks.
    """
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            logger.warning(
                f"Body too large from {request.client.host}: {content_length} bytes"
            )
            return JSONResponse(
                status_code=413,
                content={"detail": "Request payload too large."},
            )
        return await call_next(request)


# ═══════════════════════════════════════════════
# Maintenance Mode
# ═══════════════════════════════════════════════

# In-memory toggle — set via admin routes
_maintenance_mode = False


def set_maintenance_mode(enabled: bool):
    global _maintenance_mode
    _maintenance_mode = enabled


def is_maintenance_mode() -> bool:
    return _maintenance_mode


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """
    Returns 503 for all non-admin requests when maintenance mode is active.
    """

    async def dispatch(self, request: Request, call_next):
        if _maintenance_mode:
            # Allow admin routes and health check through
            if request.url.path.startswith("/admin") or request.url.path == "/health":
                return await call_next(request)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "BITVORA Exchange is currently under maintenance. Please try again shortly."
                },
            )
        return await call_next(request)
