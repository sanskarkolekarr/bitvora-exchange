"""
BITVORA EXCHANGE — Redis Distributed Lock (Redlock pattern)
Replaces Supabase column-based locking for transaction processing.
Falls back to Supabase locking when Redis is unavailable.
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("bitvora.distributed_lock")

# Lua script: only delete the key if the value matches (prevents releasing someone else's lock)
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Default lock TTL: 5 minutes (300,000 ms)
DEFAULT_LOCK_TTL_MS = 300_000

# Key prefix
LOCK_PREFIX = "bitvora:lock:txn:"


def _lock_key(transaction_id: str) -> str:
    return f"{LOCK_PREFIX}{transaction_id}"


async def acquire_lock(
    transaction_id: str,
    worker_id: str = None,
    ttl_ms: int = DEFAULT_LOCK_TTL_MS,
) -> str | None:
    """
    Acquire a distributed lock on a transaction.

    Returns the lock_value (worker_id) on success, None on failure.
    If Redis unavailable, falls back to Supabase column lock.
    """
    from services.redis_client import get_redis

    if worker_id is None:
        worker_id = str(uuid.uuid4())

    redis = await get_redis()

    if redis:
        try:
            key = _lock_key(transaction_id)
            acquired = await redis.set(key, worker_id, nx=True, px=ttl_ms)
            if acquired:
                logger.debug(f"Lock acquired: {transaction_id} by {worker_id[:8]}")
                return worker_id
            else:
                logger.debug(f"Lock busy: {transaction_id}")
                return None
        except Exception as e:
            logger.error(f"Redis lock error for {transaction_id}: {e}")
            # Fall through to Supabase fallback
            return await _supabase_acquire(transaction_id)
    else:
        return await _supabase_acquire(transaction_id)


async def release_lock(transaction_id: str, worker_id: str) -> bool:
    """
    Release a distributed lock. Uses Lua script to verify ownership.
    """
    from services.redis_client import get_redis

    redis = await get_redis()

    if redis:
        try:
            key = _lock_key(transaction_id)
            result = await redis.eval(_RELEASE_SCRIPT, 1, key, worker_id)
            released = result == 1
            if released:
                logger.debug(f"Lock released: {transaction_id} by {worker_id[:8]}")
            else:
                logger.warning(
                    f"Lock release failed (not owner): {transaction_id} by {worker_id[:8]}"
                )
            return released
        except Exception as e:
            logger.error(f"Redis unlock error for {transaction_id}: {e}")
            await _supabase_release(transaction_id)
            return False
    else:
        await _supabase_release(transaction_id)
        return True


async def is_locked(transaction_id: str) -> bool:
    """Check if a transaction is currently locked."""
    from services.redis_client import get_redis

    redis = await get_redis()

    if redis:
        try:
            return await redis.exists(_lock_key(transaction_id)) > 0
        except Exception:
            return False
    else:
        return False


async def sync_lock_to_supabase(transaction_id: str, locked: bool):
    """
    Mirror lock state to Supabase is_locked column for admin panel display.
    This is fire-and-forget — failures are logged but don't block processing.
    """
    try:
        from database import get_supabase

        db = get_supabase()
        update = {"is_locked": locked}
        if not locked:
            update["lock_acquired_at"] = None
        else:
            update["lock_acquired_at"] = datetime.now(timezone.utc).isoformat()

        db.table("transactions").update(update).eq("id", transaction_id).execute()
    except Exception as e:
        logger.error(f"Failed to sync lock state to Supabase for {transaction_id}: {e}")


# ═══════════════════════════════════════════════
# Supabase Fallback (used when Redis is unavailable)
# ═══════════════════════════════════════════════


async def _supabase_acquire(transaction_id: str) -> str | None:
    """Fallback: acquire lock via Supabase is_locked column."""
    try:
        from database import get_supabase

        db = get_supabase()
        worker_id = str(uuid.uuid4())

        db.table("transactions").update(
            {
                "is_locked": True,
                "lock_acquired_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", transaction_id).eq("is_locked", False).execute()

        return worker_id
    except Exception as e:
        logger.error(f"Supabase lock acquire failed for {transaction_id}: {e}")
        return None


async def _supabase_release(transaction_id: str):
    """Fallback: release lock via Supabase column."""
    try:
        from database import get_supabase

        db = get_supabase()
        db.table("transactions").update(
            {"is_locked": False, "lock_acquired_at": None}
        ).eq("id", transaction_id).execute()
    except Exception as e:
        logger.error(f"Supabase lock release failed for {transaction_id}: {e}")
