"""
BITVORA EXCHANGE — Weekly Cleanup Worker
Deletes transactions older than 7 days in terminal states.
Runs once per day at startup then every 24h.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from database import get_supabase

logger = logging.getLogger("bitvora.cleanup")

TERMINAL_STATUSES = ["payout_sent", "failed", "expired"]
RETENTION_DAYS = 7


async def cleanup_worker():
    """Run cleanup at startup then every 24 hours."""
    logger.info("Cleanup worker started.")
    while True:
        try:
            await _run_cleanup()
        except asyncio.CancelledError:
            logger.info("Cleanup worker cancelled.")
            raise
        except Exception as e:
            logger.error(f"Cleanup worker error: {e}")
        
        # Sleep 24 hours
        await asyncio.sleep(86400)


async def _run_cleanup():
    db = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    
    try:
        result = (
            db.table("transactions")
            .delete()
            .in_("status", TERMINAL_STATUSES)
            .lt("created_at", cutoff)
            .execute()
        )
        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"Cleanup: deleted {count} transactions older than {RETENTION_DAYS} days.")
        else:
            logger.info("Cleanup: No old transactions to delete.")
    except Exception as e:
        logger.error(f"Cleanup DB error: {e}")
