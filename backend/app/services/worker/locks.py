"""
Redis-based distributed lock system for TXID processing.

Uses SET NX EX for atomic acquire and Lua-script-guarded release
to ensure only the lock owner can delete the key.

Safety guarantees:
    • Mutual exclusion — only one worker holds a given TXID lock.
    • Deadlock prevention — every lock has a TTL; if a worker crashes
      the lock auto-expires.
    • Owner-safe release — a Lua script checks the owner token before
      DELeting, so a slow worker cannot accidentally release a lock
      that was already re-acquired by another worker after expiry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import get_logger
from app.core.redis import get_redis

logger = get_logger("worker.locks")

# ── Key namespace ──────────────────────────────────────────────

_LOCK_PREFIX = "bitvora:worker:lock:"

# ── Lua scripts (executed atomically on Redis) ────────────────

# Release only if the caller owns the lock (value == owner token)
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Extend TTL only if the caller still owns the lock
_EXTEND_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


# ── Lock handle ────────────────────────────────────────────────


@dataclass(frozen=False, slots=True)
class LockHandle:
    """
    Represents an acquired lock.

    Workers hold this object and pass it to `release_lock` / `extend_lock`.
    The `owner` token guarantees safe release even under clock drift or
    slow-worker scenarios.
    """

    txid: str
    owner: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired: bool = False

    @property
    def key(self) -> str:
        return f"{_LOCK_PREFIX}{self.txid}"


# ── Acquire ────────────────────────────────────────────────────


async def acquire_lock(
    txid: str,
    ttl: Optional[int] = None,
) -> LockHandle:
    """
    Attempt to acquire an exclusive lock for a TXID.

    Args:
        txid: Transaction ID to lock.
        ttl:  Lock lifetime in seconds (defaults to REDIS_LOCK_TIMEOUT).

    Returns:
        A LockHandle with `acquired=True` on success, `acquired=False` if
        the lock is already held by another worker.
    """
    r: aioredis.Redis = await get_redis()
    lock_ttl = ttl or settings.REDIS_LOCK_TIMEOUT
    handle = LockHandle(txid=txid)

    acquired = await r.set(
        handle.key,
        handle.owner,
        nx=True,
        ex=lock_ttl,
    )

    if acquired:
        handle.acquired = True
        logger.info(
            "Lock ACQUIRED for TX %s (owner=%s, TTL=%ds)",
            txid[:16], handle.owner[:8], lock_ttl,
        )
    else:
        logger.debug(
            "Lock DENIED for TX %s — already held", txid[:16],
        )

    return handle


# ── Release ────────────────────────────────────────────────────


async def release_lock(handle: LockHandle) -> bool:
    """
    Release a previously acquired lock.

    Uses a Lua script to ensure only the owner (identified by token) can
    release the lock.  This prevents a slow worker from accidentally
    releasing a lock that was re-acquired by another worker after TTL expiry.

    Returns:
        True if the lock was successfully released, False if it was either
        already expired or owned by a different worker.
    """
    if not handle.acquired:
        logger.debug("release_lock called on non-acquired handle for TX %s", handle.txid[:16])
        return False

    r: aioredis.Redis = await get_redis()
    result = await r.eval(_RELEASE_SCRIPT, 1, handle.key, handle.owner)

    if result:
        handle.acquired = False
        logger.info(
            "Lock RELEASED for TX %s (owner=%s)",
            handle.txid[:16], handle.owner[:8],
        )
        return True

    logger.warning(
        "Lock release FAILED for TX %s — expired or stolen (owner=%s)",
        handle.txid[:16], handle.owner[:8],
    )
    return False


# ── Extend ─────────────────────────────────────────────────────


async def extend_lock(handle: LockHandle, extra_ms: int = 30_000) -> bool:
    """
    Extend the TTL of a held lock.

    Useful for long-running verifications that might outlast the default TTL.
    Only the current owner can extend.

    Args:
        handle:   The LockHandle returned by acquire_lock.
        extra_ms: Additional milliseconds to add to the lock TTL.

    Returns:
        True if extended, False if the lock is no longer owned.
    """
    if not handle.acquired:
        return False

    r: aioredis.Redis = await get_redis()
    result = await r.eval(
        _EXTEND_SCRIPT, 1, handle.key, handle.owner, str(extra_ms),
    )

    if result:
        logger.debug(
            "Lock EXTENDED for TX %s by %dms", handle.txid[:16], extra_ms,
        )
        return True

    logger.warning(
        "Lock extend FAILED for TX %s — no longer owned", handle.txid[:16],
    )
    handle.acquired = False
    return False


# ── Query ──────────────────────────────────────────────────────


async def is_locked(txid: str) -> bool:
    """Check whether a TXID lock is currently held (any owner)."""
    r: aioredis.Redis = await get_redis()
    return bool(await r.exists(f"{_LOCK_PREFIX}{txid}"))


async def lock_ttl(txid: str) -> int:
    """Return remaining TTL in seconds for a TXID lock (-2 = not found, -1 = no expiry)."""
    r: aioredis.Redis = await get_redis()
    return await r.ttl(f"{_LOCK_PREFIX}{txid}")
