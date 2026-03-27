"""
BITVORA EXCHANGE — Health Check Endpoint
Comprehensive service status with Redis, Supabase, queue depth, and worker info.
Exempt from all middleware — must respond even during maintenance.
"""

import time
import logging
from datetime import datetime, timezone
from fastapi import APIRouter
from starlette.responses import JSONResponse

logger = logging.getLogger("bitvora.health")

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """
    Comprehensive health endpoint.
    Returns 200 if all critical services are up, 503 if any are down.
    Exempt from Cloudflare middleware and rate limiting.
    """
    status = {
        "status": "ok",
        "service": "bitvora-exchange-backend",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    all_healthy = True

    # ─── Redis Check ───
    try:
        from services.redis_client import redis_ping

        redis_ok, redis_latency = await redis_ping()
        status["checks"]["redis"] = {
            "status": "connected" if redis_ok else "disconnected",
            "latency_ms": redis_latency,
        }
        if not redis_ok:
            # Redis being down is degraded, not critical
            status["checks"]["redis"]["note"] = "Running in degraded mode (in-memory queues)"
    except Exception as e:
        status["checks"]["redis"] = {"status": "error", "error": str(e)}

    # ─── Supabase Check ───
    try:
        from database import get_supabase

        start = time.monotonic()
        db = get_supabase()
        # Simple query to test connection
        db.table("exchange_rates").select("asset").limit(1).execute()
        latency = round((time.monotonic() - start) * 1000, 2)

        status["checks"]["supabase"] = {
            "status": "connected",
            "latency_ms": latency,
        }
    except Exception as e:
        status["checks"]["supabase"] = {"status": "error", "error": str(e)}
        all_healthy = False

    # ─── Queue Depth ───
    try:
        from services.tx_verifier.verification_queue import get_queue_depth

        depth = await get_queue_depth()
        status["checks"]["queue"] = {
            "depth": depth,
            "status": "healthy" if depth < 1000 else "high",
        }
    except Exception as e:
        status["checks"]["queue"] = {"status": "error", "error": str(e)}

    # ─── Price Manager ───
    try:
        from services.price_manager import _cache_updated_at, _rate_cache

        if _cache_updated_at:
            status["checks"]["price_manager"] = {
                "status": "active",
                "last_update": _cache_updated_at.isoformat(),
                "cached_assets": len(_rate_cache),
            }
        else:
            status["checks"]["price_manager"] = {
                "status": "not_initialized",
            }
    except Exception as e:
        status["checks"]["price_manager"] = {"status": "error", "error": str(e)}

    # ─── Overall Status ───
    status["status"] = "ok" if all_healthy else "degraded"
    status_code = 200 if all_healthy else 503

    return JSONResponse(content=status, status_code=status_code)
