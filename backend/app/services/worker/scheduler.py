"""
Retry scheduler and orphan recovery for the worker system.

Responsibilities:
    1. Compute the next retry delay using a fixed backoff table.
    2. Periodically sweep the retry sorted set and re-enqueue eligible TXIDs.
    3. Detect orphaned TXIDs stuck in the processing set (worker crashed
       mid-flight) and re-enqueue them.

Retry table (index = retry_count):
    0 → 10s,  1 → 15s,  2 → 25s,  3 → 40s,  4 → 60s

Max retries: 5  (after 5 attempts the TX is sent to DLQ / marked failed).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import get_session
from app.core.logger import get_logger
from app.models.transaction import Transaction, TransactionStatus
from app.services.worker.queue import (
    collect_due_retries,
    mark_failed_permanent,
    schedule_retry,
    PROCESSING_KEY,
    QUEUE_KEY,
    DEDUP_KEY,
)

logger = get_logger("worker.scheduler")

# ── Retry configuration ───────────────────────────────────────

MAX_RETRIES: int = 5

RETRY_DELAYS: tuple[float, ...] = (
    10.0,   # retry 1
    15.0,   # retry 2
    25.0,   # retry 3
    40.0,   # retry 4
    60.0,   # retry 5
)

# Orphan sweep: if a TXID is in the processing set longer than this
# many seconds it is considered orphaned (worker crashed).
_ORPHAN_THRESHOLD_SECONDS: int = 120

# How often the scheduler loop ticks
_SCHEDULER_TICK_SECONDS: float = 5.0

# How often the orphan sweep runs (every N scheduler ticks)
_ORPHAN_SWEEP_INTERVAL_TICKS: int = 12  # ~60 seconds


# ── Delay calculation ─────────────────────────────────────────


def get_retry_delay(retry_count: int) -> Optional[float]:
    """
    Return the delay in seconds for the given retry attempt.

    Returns None if the maximum retries have been exceeded.
    """
    if retry_count >= MAX_RETRIES:
        return None
    idx = min(retry_count, len(RETRY_DELAYS) - 1)
    return RETRY_DELAYS[idx]


def should_retry(retry_count: int) -> bool:
    """Return True if another retry is allowed."""
    return retry_count < MAX_RETRIES


# ── DB helpers ─────────────────────────────────────────────────


async def increment_retry_count(txid: str) -> int:
    """
    Atomically increment the retry_count for a TXID in the database.

    Returns the new retry_count value.
    """
    async with get_session() as session:
        stmt = (
            select(Transaction)
            .where(Transaction.txid == txid)
            .with_for_update()  # row-level lock
        )
        result = await session.execute(stmt)
        tx = result.scalar_one_or_none()

        if tx is None:
            logger.error("increment_retry_count: TX %s not found in DB", txid[:16])
            return MAX_RETRIES  # force failure

        tx.retry_count += 1
        new_count = tx.retry_count
        logger.info(
            "TX %s retry_count incremented to %d/%d",
            txid[:16], new_count, MAX_RETRIES,
        )
        return new_count


async def mark_tx_failed_in_db(txid: str) -> None:
    """Set the transaction status to FAILED in the database."""
    async with get_session() as session:
        stmt = (
            update(Transaction)
            .where(Transaction.txid == txid)
            .values(
                status=TransactionStatus.FAILED,
                verified_at=datetime.now(timezone.utc),
            )
        )
        await session.execute(stmt)
    logger.warning("TX %s marked FAILED in database", txid[:16])


async def update_tx_status_processing(txid: str) -> None:
    """Set the transaction status to PROCESSING in the database."""
    async with get_session() as session:
        stmt = (
            update(Transaction)
            .where(Transaction.txid == txid)
            .values(status=TransactionStatus.PROCESSING)
        )
        await session.execute(stmt)


# ── Handle retry decision ─────────────────────────────────────


async def handle_retry(txid: str) -> bool:
    """
    Decide whether to retry a TXID and schedule it if allowed.

    Returns True if a retry was scheduled, False if the TX exhausted
    all retries and was moved to the DLQ / marked failed.
    """
    new_count = await increment_retry_count(txid)

    delay = get_retry_delay(new_count)
    if delay is None:
        # Exhausted — permanent failure
        logger.warning(
            "TX %s exhausted all %d retries — marking failed",
            txid[:16], MAX_RETRIES,
        )
        await mark_tx_failed_in_db(txid)
        await mark_failed_permanent(txid)
        return False

    # Schedule for later re-enqueue
    await schedule_retry(txid, delay)
    logger.info(
        "TX %s retry %d/%d scheduled in %.0fs",
        txid[:16], new_count, MAX_RETRIES, delay,
    )
    return True


# ── Orphan recovery ───────────────────────────────────────────


async def sweep_orphans() -> int:
    """
    Detect TXIDs stuck in the processing set without a corresponding lock
    (meaning the worker crashed).  Re-enqueue them.

    Returns the number of orphans recovered.
    """
    from app.services.worker.locks import is_locked
    from app.core.redis import get_redis

    r = await get_redis()
    processing: set[str] = await r.smembers(PROCESSING_KEY)

    if not processing:
        return 0

    orphans: list[str] = []
    for txid in processing:
        # If the lock expired but TXID is still in processing set → orphan
        if not await is_locked(txid):
            orphans.append(txid)

    if not orphans:
        return 0

    # Re-enqueue orphans
    async with r.pipeline(transaction=True) as pipe:
        for txid in orphans:
            pipe.srem(PROCESSING_KEY, txid)
            pipe.sadd(DEDUP_KEY, txid)
            pipe.lpush(QUEUE_KEY, txid)
        await pipe.execute()

    logger.warning("Recovered %d orphaned TXIDs: %s", len(orphans), [t[:16] for t in orphans])
    return len(orphans)


# ── Scheduler loop ────────────────────────────────────────────


_scheduler_running: bool = False
_scheduler_task: Optional[asyncio.Task] = None


async def _scheduler_loop() -> None:
    """
    Background loop that:
        1. Every tick — collects due retries from the sorted set and
           re-enqueues them into the main queue.
        2. Every N ticks — sweeps for orphaned TXIDs.
    """
    global _scheduler_running
    tick = 0

    logger.info(
        "Scheduler started (tick=%.1fs, orphan_sweep_every=%d ticks)",
        _SCHEDULER_TICK_SECONDS, _ORPHAN_SWEEP_INTERVAL_TICKS,
    )

    while _scheduler_running:
        try:
            # 1. Collect due retries
            retried = await collect_due_retries(batch_size=200)
            if retried:
                logger.info("Scheduler re-enqueued %d retries", len(retried))

            # 2. Orphan sweep (less frequently)
            tick += 1
            if tick % _ORPHAN_SWEEP_INTERVAL_TICKS == 0:
                recovered = await sweep_orphans()
                if recovered:
                    logger.info("Scheduler recovered %d orphans", recovered)

        except Exception:
            logger.exception("Scheduler tick error — continuing")

        await asyncio.sleep(_SCHEDULER_TICK_SECONDS)

    logger.info("Scheduler stopped")


async def start_scheduler() -> asyncio.Task:
    """Launch the scheduler as a background asyncio task."""
    global _scheduler_running, _scheduler_task

    if _scheduler_task and not _scheduler_task.done():
        logger.warning("Scheduler already running")
        return _scheduler_task

    _scheduler_running = True
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="tx-scheduler")
    logger.info("Scheduler task created")
    return _scheduler_task


async def stop_scheduler() -> None:
    """Signal the scheduler to stop and wait for it to finish."""
    global _scheduler_running, _scheduler_task

    _scheduler_running = False

    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        logger.info("Scheduler task cancelled")

    _scheduler_task = None
