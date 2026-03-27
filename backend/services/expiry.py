"""
BITVORA EXCHANGE — Expiry Worker
Mirrors the Telegram bot's expiry behavior exactly.

State transitions (bot-identical):
  pending/verifying + expires_at < now
    → status = "monitoring_expired"   (NOT "expired" immediately)

"monitoring_expired" means:
  - The order window has closed
  - BUT the late sweeper still watches for funds for another 48 hours
  - Only if the sweeper finds nothing do we truly abandon it

This matches the bot's graceful expiry → late_recovery flow.
"""

import asyncio
import logging
from datetime import datetime, timezone

from database import get_supabase

logger = logging.getLogger("bitvora.worker.expiry")


async def expiry_worker():
    """
    Runs every 60 seconds.
    Moves expired pending/verifying transactions to 'monitoring_expired'.
    The late sweeper handles recovery from that state.
    """
    logger.info("Expiry worker started (60s interval)")

    while True:
        try:
            await _run_expiry_cycle()
        except asyncio.CancelledError:
            logger.info("Expiry worker cancelled")
            break
        except Exception as e:
            logger.error("Expiry worker error: %s", e)

        await asyncio.sleep(60)


async def _run_expiry_cycle():
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    # Expire pending / verifying orders past their window
    result = (
        db.table("transactions")
        .select("id, txid, reference")
        .in_("status", ["pending", "verifying", "pending_retry"])
        .lt("expires_at", now)
        .execute()
    )

    if not result.data:
        return

    for tx in result.data:
        db.table("transactions").update({
            "status": "monitoring_expired",
            "is_locked": False,
            "lock_acquired_at": None,
        }).eq("id", tx["id"]).execute()

        logger.info(
            "Order %s expired → monitoring_expired (txid=%s)",
            tx.get("reference", tx["id"][:8]),
            (tx.get("txid") or "none")[:16],
        )

    logger.info("Expiry cycle: moved %d orders to monitoring_expired", len(result.data))
