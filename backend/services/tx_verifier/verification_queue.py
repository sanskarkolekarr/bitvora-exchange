"""
BITVORA EXCHANGE — Verification Queue (Production)
Redis-backed persistent job queue with concurrent worker pool.
Falls back to in-memory asyncio.Queue when Redis is unavailable.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from database import get_supabase
from config import settings
from services.telegram_bot import send_order_notification

logger = logging.getLogger("bitvora.worker.verification_queue")

# ═══════════════════════════════════════════════
# In-memory fallback queue (used when Redis unavailable)
# ═══════════════════════════════════════════════

_fallback_queue: Optional[asyncio.Queue] = None

REDIS_QUEUE_KEY = "bitvora:verify:queue"

# Module-level RPC round-robin counters
_rpc_counters: dict[str, int] = {}


def _get_fallback_queue() -> asyncio.Queue:
    global _fallback_queue
    if _fallback_queue is None:
        _fallback_queue = asyncio.Queue(maxsize=10000)
    return _fallback_queue


# ═══════════════════════════════════════════════
# RPC Round-Robin
# ═══════════════════════════════════════════════


def get_rpc_url(chain: str) -> str:
    """
    Get the next RPC URL for a chain using round-robin rotation.
    Falls back to primary RPC if pools not available.
    """
    pools = settings.rpc_pools
    urls = pools.get(chain, [settings.rpc_urls.get(chain, "")])
    if not urls:
        return settings.rpc_urls.get(chain, "")

    if chain not in _rpc_counters:
        _rpc_counters[chain] = 0

    idx = _rpc_counters[chain] % len(urls)
    _rpc_counters[chain] += 1
    return urls[idx]


# ═══════════════════════════════════════════════
# Queue Operations
# ═══════════════════════════════════════════════


async def push_to_queue(
    transaction_id: str,
    chain: str,
    priority: int = 0,
) -> bool:
    """
    Push a verification job to the queue.
    Uses Redis LPUSH if available, falls back to asyncio.Queue.
    """
    from services.redis_client import get_redis

    job = {
        "transaction_id": transaction_id,
        "chain": chain,
        "priority": priority,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "retry_count": 0,
    }

    redis = await get_redis()
    if redis:
        try:
            await redis.lpush(REDIS_QUEUE_KEY, json.dumps(job))
            logger.debug(f"Job pushed to Redis queue: {transaction_id}")
            return True
        except Exception as e:
            logger.error(f"Redis LPUSH failed: {e} — falling back to memory queue")

    # Fallback: in-memory queue
    try:
        _get_fallback_queue().put_nowait(job)
        logger.debug(f"Job pushed to fallback queue: {transaction_id}")
        return True
    except asyncio.QueueFull:
        logger.error(f"Fallback queue full — dropping job {transaction_id}")
        return False


async def get_queue_depth() -> int:
    """Get the current queue depth for health checks."""
    from services.redis_client import get_redis

    redis = await get_redis()
    if redis:
        try:
            return await redis.llen(REDIS_QUEUE_KEY)
        except Exception:
            pass

    return _get_fallback_queue().qsize()


# ═══════════════════════════════════════════════
# Chain Verifier Dispatch
# ═══════════════════════════════════════════════


async def _get_verifier(chain: str):
    """Dynamically import the correct chain verifier."""
    family = settings.chain_families.get(chain)
    if family == "evm":
        from services.tx_verifier.chains.evm import verify_transaction
    elif family == "tron":
        from services.tx_verifier.chains.tron import verify_transaction
    elif family == "solana":
        from services.tx_verifier.chains.solana import verify_transaction
    elif family == "bitcoin":
        from services.tx_verifier.chains.bitcoin import verify_transaction
    elif family == "ton":
        from services.tx_verifier.chains.ton import verify_transaction
    elif family == "litecoin":
        from services.tx_verifier.chains.litecoin import verify_transaction
    else:
        return None
    return verify_transaction



# ═══════════════════════════════════════════════
# Payout Queue Helper
# ═══════════════════════════════════════════════


async def _queue_payout(db, tx):
    """Insert transaction into payout queue."""
    try:
        db.table("payout_queue").insert(
            {
                "id": str(uuid.uuid4()),
                "transaction_id": tx["id"],
                "payout_destination": tx.get("payout_destination", ""),
                "amount_inr": tx.get("amount_inr", 0),
                "status": "pending",
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as e:
        logger.error(f"Failed to queue payout for {tx['id']}: {e}")


# ═══════════════════════════════════════════════
# Job Processor (shared by all workers)
# ═══════════════════════════════════════════════


async def _process_job(job: dict, worker_id: str):
    """
    Process a single verification job.
    Acquires distributed lock, runs verifier, updates database.
    """
    from services.tx_verifier.distributed_lock import (
        acquire_lock,
        release_lock,
        sync_lock_to_supabase,
    )

    tx_id = job["transaction_id"]
    chain = job.get("chain", "")
    retry_count = job.get("retry_count", 0)

    db = get_supabase()

    # Fetch the transaction from Supabase
    result = db.table("transactions").select("*").eq("id", tx_id).execute()
    if not result.data:
        logger.warning(f"[{worker_id}] Transaction {tx_id} not found — skipping")
        return

    tx = result.data[0]

    # Skip if no longer pending
    if tx["status"] not in ("pending",):
        logger.debug(f"[{worker_id}] Transaction {tx_id} status is {tx['status']} — skipping")
        return

    # Acquire distributed lock
    lock_value = await acquire_lock(tx_id, worker_id)
    if not lock_value:
        logger.debug(f"[{worker_id}] Could not acquire lock on {tx_id} — another worker has it")
        return

    await sync_lock_to_supabase(tx_id, True)

    try:
        verifier = await _get_verifier(chain or tx["chain"])
        if not verifier:
            db.table("transactions").update(
                {"status": "failed", "error_message": f"Unsupported chain: {chain}"}
            ).eq("id", tx_id).execute()
            return

        txid = tx["txid"]
        logger.info(f"[{worker_id}] Processing {txid[:16]}... on {chain or tx['chain']}")

        try:
            import inspect
            verifier_sig = inspect.signature(verifier)
            supports_created_at = "order_created_at" in verifier_sig.parameters

            call_kwargs = dict(
                txid=txid,
                chain=tx["chain"],
                expected_address=tx["deposit_address"],
                expected_amount=float(tx.get("amount_crypto", 0)),
                asset=tx["asset"],
            )
            if supports_created_at:
                call_kwargs["order_created_at"] = tx.get("created_at")

            vresult = await verifier(**call_kwargs)

        except Exception as e:
            logger.error(f"[{worker_id}] Verifier exception for {tx_id}: {e}")
            # Re-queue with incremented retry
            if retry_count < 5:
                job["retry_count"] = retry_count + 1
                await push_to_queue(tx_id, chain, job.get("priority", 0))
                logger.info(f"[{worker_id}] Re-queued {tx_id} (retry {retry_count + 1}/5)")
            else:
                db.table("transactions").update(
                    {"status": "pending_retry", "error_message": f"Worker retries exhausted, deferring to watcher: {e}"}
                ).eq("id", tx_id).execute()
                logger.warning(f"[{worker_id}] Worker retries exhausted for {tx_id} — marked pending_retry")
            return

        # ── Process verification result (bot-identical state machine) ──
        if not vresult.valid:
            if vresult.is_hard_failure:
                # Definitive on-chain failure — reverted, wrong address, too old, etc.
                db.table("transactions").update(
                    {"status": "failed", "error_message": vresult.error}
                ).eq("id", tx_id).execute()
                logger.info(f"[{worker_id}] TX {tx_id[:8]} HARD FAIL: {vresult.error}")

            elif vresult.confirmations > 0:
                # Valid TX but insufficient confs yet — put in verifying
                db.table("transactions").update(
                    {"status": "verifying", "confirmations": vresult.confirmations}
                ).eq("id", tx_id).execute()
                logger.info(
                    f"[{worker_id}] TX {tx_id[:8]} partial: {vresult.confirmations}/{vresult.required_confirmations} confs"
                )

            else:
                # Soft failure (not found, propagating, RPC lag)
                # Mark as pending_retry so the watcher loop will pick it up
                db.table("transactions").update(
                    {"status": "pending_retry", "error_message": vresult.error}
                ).eq("id", tx_id).execute()
                logger.info(
                    f"[{worker_id}] TX {tx_id[:8]} SOFT FAIL (deferred to watcher): {vresult.error}"
                )

        elif vresult.valid:
            if vresult.confirmations >= vresult.required_confirmations:
                # ── FULLY CONFIRMED ──
                now = datetime.now(timezone.utc).isoformat()
                db.table("transactions").update(
                    {
                        "status": "payout_queued",
                        "confirmations": vresult.confirmations,
                        "verified_at": now,
                        "payout_queued_at": now,
                        "amount_crypto_received": vresult.amount_detected,
                    }
                ).eq("id", tx_id).execute()

                user_res = (
                    db.table("users")
                    .select("username")
                    .eq("id", tx["user_id"])
                    .execute()
                )
                tx["username"] = user_res.data[0]["username"] if user_res.data else "Unknown"

                await _queue_payout(db, tx)
                await send_order_notification(tx)
                logger.info(
                    f"[{worker_id}] ✅ TX {tx_id[:8]} verified → payout_queued "
                    f"({vresult.amount_detected:.6f} received, {vresult.confirmations} confs)"
                )
            else:
                # Valid but waiting for more confirmations
                db.table("transactions").update(
                    {
                        "status": "verifying",
                        "confirmations": vresult.confirmations,
                        "required_confirmations": vresult.required_confirmations,
                    }
                ).eq("id", tx_id).execute()
                logger.info(
                    f"[{worker_id}] TX {tx_id[:8]} valid, {vresult.confirmations}/{vresult.required_confirmations} confs"
                )

    finally:
        await release_lock(tx_id, lock_value)
        await sync_lock_to_supabase(tx_id, False)


# ═══════════════════════════════════════════════
# Pending Tracker
# ═══════════════════════════════════════════════

async def pending_tracker_worker():
    """
    Runs every 60 seconds.
    Fetches all unexpired 'pending' transactions from the database
    and pushes them to the verification queue.
    """
    logger.info("Pending tracker worker started")
    while True:
        try:
            db = get_supabase()
            now = datetime.now(timezone.utc).isoformat()
            
            result = (
                db.table("transactions")
                .select("id, chain")
                .eq("status", "pending")
                .eq("is_locked", False)
                .gt("expires_at", now)
                .execute()
            )
            
            # For each pending tx, enqueue it.
            # Distributed locks prevent multi-processing if queue gets backed up.
            for tx in result.data:
                await push_to_queue(tx["id"], tx["chain"])
                
        except asyncio.CancelledError:
            logger.info("Pending tracker cancelled")
            break
        except Exception as e:
            logger.error(f"Pending tracker error: {e}")
            
        await asyncio.sleep(60)


# ═══════════════════════════════════════════════
# Worker — Redis Consumer
# ═══════════════════════════════════════════════


async def verification_queue_worker(
    worker_id: int = 0,
    chain_filter: str = None,
):
    """
    Single worker that pulls jobs from the queue.
    If chain_filter is set, only processes matching jobs (re-queues others).
    """
    from services.redis_client import get_redis

    wid = f"vw-{chain_filter or 'any'}-{worker_id}"
    logger.info(f"[{wid}] Verification worker started (filter={chain_filter})")

    while True:
        try:
            redis = await get_redis()

            if redis:
                # ─── Redis mode: BRPOP with 1s timeout ───
                result = await redis.brpop(REDIS_QUEUE_KEY, timeout=1)
                if result is None:
                    continue  # Timeout — no jobs, loop back

                _, raw = result
                job = json.loads(raw)
            else:
                # ─── Fallback mode: asyncio.Queue ───
                try:
                    job = await asyncio.wait_for(_get_fallback_queue().get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

            # Chain filtering — if this job doesn't match our filter, re-queue it
            job_chain = job.get("chain", "")
            job_family = settings.chain_families.get(job_chain, "")

            if chain_filter and job_family != chain_filter:
                # Not our job — push it back
                if redis:
                    await redis.lpush(REDIS_QUEUE_KEY, json.dumps(job))
                else:
                    await _get_fallback_queue().put(job)
                    _get_fallback_queue().task_done()
                await asyncio.sleep(0.1)
                continue

            await _process_job(job, wid)

            if not redis:
                _get_fallback_queue().task_done()

        except asyncio.CancelledError:
            logger.info(f"[{wid}] Worker cancelled")
            break
        except Exception as e:
            logger.error(f"[{wid}] Worker error: {e}")
            await asyncio.sleep(2)


# ═══════════════════════════════════════════════
# Worker Pool — Starts all concurrent workers
# ═══════════════════════════════════════════════


async def start_worker_pool():
    """
    Start the full pool of concurrent verification workers.
    Total: 26 workers across all chain families.

    EVM: 10 workers, Tron: 5, Solana: 5, Bitcoin: 3, TON: 3
    """
    logger.info("=" * 60)
    logger.info("  Starting Verification Worker Pool")
    logger.info("=" * 60)

    pool_config = settings.worker_pool_config
    tasks = []

    for family, count in pool_config.items():
        for i in range(count):
            task = asyncio.create_task(
                verification_queue_worker(worker_id=i, chain_filter=family),
                name=f"verify-{family}-{i}",
            )
            tasks.append(task)

    total = sum(pool_config.values())
    logger.info(
        f"Worker pool started: {total} workers "
        f"({', '.join(f'{f}={c}' for f, c in pool_config.items())})"
    )

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Worker pool shutting down...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Worker pool stopped")
