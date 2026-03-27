"""
BITVORA EXCHANGE — Redis Client
Async singleton with graceful fallback to None when Redis is unavailable.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("bitvora.redis")

_redis_client = None
_initialized = False


async def get_redis():
    """
    Returns the async Redis client, or None if Redis is unavailable.
    Lazy-initialises on first call.
    """
    global _redis_client, _initialized

    if _initialized:
        return _redis_client

    _initialized = True
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

    try:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        # Test the connection
        await _redis_client.ping()
        logger.info(f"Redis connected: {redis_url}")
        return _redis_client

    except ImportError:
        logger.warning("redis package not installed — running without Redis")
        _redis_client = None
        return None
    except Exception as e:
        logger.warning(f"Redis connection failed ({redis_url}): {e} — running in degraded mode")
        _redis_client = None
        return None


async def close_redis():
    """Gracefully close the Redis connection."""
    global _redis_client, _initialized
    if _redis_client:
        try:
            await _redis_client.close()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis: {e}")
    _redis_client = None
    _initialized = False


async def redis_ping() -> tuple[bool, Optional[float]]:
    """
    Health check — returns (is_connected, latency_ms).
    """
    import time

    client = await get_redis()
    if not client:
        return False, None

    try:
        start = time.monotonic()
        await client.ping()
        latency = round((time.monotonic() - start) * 1000, 2)
        return True, latency
    except Exception:
        return False, None
