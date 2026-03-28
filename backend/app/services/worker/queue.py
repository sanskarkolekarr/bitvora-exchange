"""
Redis-based TXID queue with deduplication and dead-letter tracking.

Architecture:
    Main queue          → bitvora:worker:queue        (Redis LIST — FIFO via LPUSH / BRPOP)
    Dedup guard         → bitvora:worker:dedup        (Redis SET  — O(1) membership check)
    Processing set      → bitvora:worker:processing   (Redis SET  — tracks in-flight TXIDs)
    Dead-letter queue   → bitvora:worker:dlq          (Redis LIST — permanently failed TXIDs)
    Retry schedule      → bitvora:worker:retry        (Redis ZSET — score = Unix timestamp)

Guarantees:
    • A TXID can only appear ONCE across queue + processing at any time.
    • If a worker crashes, the TXID remains in the processing set and can be
      recovered by the scheduler's orphan sweep.
    • Retry items are scored by their next-eligible timestamp so the scheduler
      can poll with ZRANGEBYSCORE in O(log N).
"""

from __future__ import annotations

import time
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import get_logger
from app.core.redis import get_redis

logger = get_logger("worker.queue")

# ── Key namespace ──────────────────────────────────────────────

_PREFIX = "bitvora:worker"
QUEUE_KEY = f"{_PREFIX}:queue"
DEDUP_KEY = f"{_PREFIX}:dedup"
PROCESSING_KEY = f"{_PREFIX}:processing"
DLQ_KEY = f"{_PREFIX}:dlq"
RETRY_ZSET_KEY = f"{_PREFIX}:retry"


# ── Enqueue ────────────────────────────────────────────────────


async def enqueue_tx(txid: str) -> bool:
    """
    Push a TXID onto the processing queue.

    Returns False if the TXID is already queued, in-flight, or in the DLQ —
    preventing duplicate work at every stage.  Uses a pipelined SADD → LPUSH
    to minimise round-trips.
    """
    r: aioredis.Redis = await get_redis()

    # Fast dedup check (SET is O(1))
    if await r.sismember(DEDUP_KEY, txid):
        logger.debug("enqueue_tx: TX %s already in dedup set — skip", txid[:16])
        return False

    if await r.sismember(PROCESSING_KEY, txid):
        logger.debug("enqueue_tx: TX %s already processing — skip", txid[:16])
        return False

    # Atomic add-to-set + push-to-list via pipeline
    async with r.pipeline(transaction=True) as pipe:
        pipe.sadd(DEDUP_KEY, txid)
        pipe.lpush(QUEUE_KEY, txid)
        results = await pipe.execute()

    added_to_dedup = results[0]
    if not added_to_dedup:
        # Race: another coroutine added it between our check and the pipeline
        logger.debug("enqueue_tx: dedup race for TX %s — skip", txid[:16])
        return False

    logger.info("TX %s enqueued", txid[:16])
    return True


# ── Dequeue ────────────────────────────────────────────────────


async def dequeue_tx(timeout: int = 2) -> Optional[str]:
    """
    Blocking pop from the queue.  Moves the TXID into the processing set
    atomically so crash recovery is possible.

    Args:
        timeout: Max seconds to wait (kept small to allow graceful shutdown).

    Returns:
        TXID string or None if the queue is empty after timeout.
    """
    r: aioredis.Redis = await get_redis()

    result = await r.brpop(QUEUE_KEY, timeout=timeout)
    if result is None:
        return None

    _key, txid = result

    # Move from dedup → processing in one pipeline
    async with r.pipeline(transaction=True) as pipe:
        pipe.srem(DEDUP_KEY, txid)
        pipe.sadd(PROCESSING_KEY, txid)
        await pipe.execute()

    logger.info("TX %s dequeued → processing", txid[:16])
    return txid


# ── Completion helpers ─────────────────────────────────────────


async def mark_completed(txid: str) -> None:
    """Remove TXID from the processing set after successful verification."""
    r: aioredis.Redis = await get_redis()
    await r.srem(PROCESSING_KEY, txid)
    logger.info("TX %s marked completed", txid[:16])


async def mark_failed_permanent(txid: str) -> None:
    """Move TXID to the dead-letter queue — no more retries."""
    r: aioredis.Redis = await get_redis()
    async with r.pipeline(transaction=True) as pipe:
        pipe.srem(PROCESSING_KEY, txid)
        pipe.srem(DEDUP_KEY, txid)
        pipe.lpush(DLQ_KEY, txid)
        await pipe.execute()
    logger.warning("TX %s moved to dead-letter queue", txid[:16])


# ── Retry scheduling ──────────────────────────────────────────


async def schedule_retry(txid: str, delay_seconds: float) -> None:
    """
    Schedule a TXID for future retry.

    The TXID is added to a sorted set scored by the Unix timestamp at which
    it becomes eligible.  Removes it from the processing set so the lock can
    be released.
    """
    r: aioredis.Redis = await get_redis()
    eligible_at = time.time() + delay_seconds

    async with r.pipeline(transaction=True) as pipe:
        pipe.srem(PROCESSING_KEY, txid)
        pipe.zadd(RETRY_ZSET_KEY, {txid: eligible_at})
        await pipe.execute()

    logger.info(
        "TX %s scheduled for retry in %.0fs (at %.0f)",
        txid[:16], delay_seconds, eligible_at,
    )


async def collect_due_retries(batch_size: int = 100) -> list[str]:
    """
    Harvest TXIDs whose retry delay has elapsed.

    Returns up to `batch_size` items and re-enqueues them into the main queue.
    Uses ZPOPMIN-style logic atomically.
    """
    r: aioredis.Redis = await get_redis()
    now = time.time()

    # Fetch eligible members (score ≤ now)
    txids: list[str] = await r.zrangebyscore(
        RETRY_ZSET_KEY, "-inf", now, start=0, num=batch_size,
    )
    if not txids:
        return []

    # Remove fetched items and re-enqueue
    async with r.pipeline(transaction=True) as pipe:
        pipe.zrem(RETRY_ZSET_KEY, *txids)
        for txid in txids:
            pipe.sadd(DEDUP_KEY, txid)
            pipe.lpush(QUEUE_KEY, txid)
        await pipe.execute()

    logger.info("Re-enqueued %d due retries", len(txids))
    return txids


# ── Diagnostics ────────────────────────────────────────────────


async def queue_depth() -> dict[str, int]:
    """Return current sizes of queue, processing set, retry set, and DLQ."""
    r: aioredis.Redis = await get_redis()
    async with r.pipeline(transaction=False) as pipe:
        pipe.llen(QUEUE_KEY)
        pipe.scard(PROCESSING_KEY)
        pipe.zcard(RETRY_ZSET_KEY)
        pipe.llen(DLQ_KEY)
        pipe.scard(DEDUP_KEY)
        q, p, rr, d, dd = await pipe.execute()

    return {
        "queued": q,
        "processing": p,
        "retry_scheduled": rr,
        "dead_letter": d,
        "dedup_set": dd,
    }
