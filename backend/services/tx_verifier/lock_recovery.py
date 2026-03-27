"""
BITVORA EXCHANGE — Lock Recovery Worker (Redis-aware)
With Redis distributed locks, TTL handles expiry automatically.
This worker now only syncs Supabase is_locked column for admin panel display
and handles edge cases where lock state is inconsistent.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from database import get_supabase

logger = logging.getLogger("bitvora.worker.lock_recovery")


async def lock_recovery_worker():
    """
    Runs every 60 seconds.

    With Redis: Redis TTL auto-expires locks after 5 minutes.
    This worker syncs the Supabase is_locked column to match Redis state
    so the admin panel shows accurate lock status.

    Without Redis: Falls back to the old behavior — resets Supabase locks
    older than 5 minutes.
    """
    logger.info("Lock recovery worker started")

    while True:
        try:
            await _run_recovery()
        except asyncio.CancelledError:
            logger.info("Lock recovery worker cancelled")
            break
        except Exception as e:
            logger.error(f"Lock recovery error: {e}")

        await asyncio.sleep(60)


async def _run_recovery():
    """Check for stale locks and clean up."""
    from services.redis_client import get_redis
    from services.tx_verifier.distributed_lock import is_locked as redis_is_locked

    db = get_supabase()
    redis = await get_redis()

    if redis:
        # ─── Redis mode: sync Supabase column with Redis truth ───
        # Find transactions marked locked in Supabase
        result = (
            db.table("transactions")
            .select("id")
            .eq("is_locked", True)
            .execute()
        )

        synced = 0
        for tx in result.data:
            tx_id = tx["id"]
            still_locked = await redis_is_locked(tx_id)

            if not still_locked:
                # Redis lock expired (TTL) but Supabase still shows locked
                db.table("transactions").update(
                    {"is_locked": False, "lock_acquired_at": None}
                ).eq("id", tx_id).execute()
                synced += 1

        if synced > 0:
            logger.info(f"Synced {synced} stale Supabase locks (Redis TTL expired)")

    else:
        # ─── Fallback mode: time-based cleanup like the old system ───
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        result = (
            db.table("transactions")
            .select("id, lock_acquired_at")
            .eq("is_locked", True)
            .lt("lock_acquired_at", cutoff)
            .execute()
        )

        if result.data:
            for tx in result.data:
                db.table("transactions").update(
                    {"is_locked": False, "lock_acquired_at": None}
                ).eq("id", tx["id"]).execute()

                logger.warning(f"Recovered stale lock on transaction {tx['id']}")

            logger.info(f"Recovered {len(result.data)} stale locks (fallback mode)")
