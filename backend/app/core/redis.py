"""
Async Redis client — connection pool and backward-compatible queue/lock API.

Provides:
- Connection lifecycle (get_redis / close_redis)
- enqueue_tx / dequeue_tx  → delegates to app.services.worker.queue
- acquire_lock / release_lock / is_locked  (kept for simple callers)

The worker system (services/worker/) owns the production queue and locking.
Functions here are thin wrappers so existing callers (API routes) keep working.
"""

from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("core.redis")

# ── Connection pool ────────────────────────────────────────────

_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Return the global Redis connection (lazy-initialised)."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis connection pool created")
    return _pool


async def close_redis() -> None:
    """Gracefully shut down the Redis pool."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Redis connection pool closed")


# ── Queue operations (delegates to worker queue) ──────────────


async def enqueue_tx(txid: str) -> bool:
    """
    Push a TXID onto the worker processing queue.

    This is a thin wrapper around the worker queue module so that
    API routes can keep importing from ``app.core.redis``.
    """
    from app.services.worker.queue import enqueue_tx as _worker_enqueue
    return await _worker_enqueue(txid)


async def dequeue_tx(timeout: int = 5) -> Optional[str]:
    """Pop from the worker queue (used mainly in tests)."""
    from app.services.worker.queue import dequeue_tx as _worker_dequeue
    return await _worker_dequeue(timeout)


async def mark_processed(txid: str) -> None:
    """Mark a TXID as completed in the worker queue."""
    from app.services.worker.queue import mark_completed
    await mark_completed(txid)


# ── Simple lock operations (non-owner-guarded) ────────────────
# Kept for callers that don't need owner-safe semantics.
# The worker system uses services/worker/locks.py with Lua scripts.

_LOCK_PREFIX = "bitvora:tx:lock:"


async def acquire_lock(txid: str, ttl: Optional[int] = None) -> bool:
    """
    Acquire a simple lock (no owner token).

    For owner-safe locking with Lua-guarded release, use
    ``app.services.worker.locks.acquire_lock`` instead.
    """
    r = await get_redis()
    lock_key = f"{_LOCK_PREFIX}{txid}"
    lock_ttl = ttl or settings.REDIS_LOCK_TIMEOUT

    acquired = await r.set(lock_key, "1", nx=True, ex=lock_ttl)
    if acquired:
        logger.info("Lock acquired for TX %s (TTL=%ds)", txid, lock_ttl)
        return True

    logger.warning("Lock NOT acquired for TX %s — already held", txid)
    return False


async def release_lock(txid: str) -> bool:
    """Release a simple (non-owner-guarded) lock."""
    r = await get_redis()
    lock_key = f"{_LOCK_PREFIX}{txid}"
    deleted = await r.delete(lock_key)
    if deleted:
        logger.info("Lock released for TX %s", txid)
        return True

    logger.warning("Lock release failed for TX %s — key not found", txid)
    return False


async def is_locked(txid: str) -> bool:
    """Check whether a TXID lock is currently held."""
    r = await get_redis()
    return bool(await r.exists(f"{_LOCK_PREFIX}{txid}"))

