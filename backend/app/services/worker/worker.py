"""
Async worker engine for TXID verification.

Spawns a configurable pool of coroutine workers (default 30) that:

    1. Dequeue a TXID from Redis
    2. Acquire a distributed lock (prevents double-processing)
    3. Fetch chain info from DB
    4. Call the verifier service
    5. Convert to USD/INR via price engine
    6. Update the database
    7. Send Telegram notification
    8. Release the lock

Life-cycle:
    start_workers()  — called from FastAPI lifespan (startup)
    stop_workers()   — called from FastAPI lifespan (shutdown)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import get_session
from app.core.logger import get_logger
from app.services.worker.locks import LockHandle, acquire_lock, release_lock
from app.services.worker.queue import dequeue_tx, mark_completed, mark_failed_permanent
from app.services.worker.scheduler import (
    handle_retry,
    start_scheduler,
    stop_scheduler,
    update_tx_status_processing,
)

logger = get_logger("worker.engine")

# ── Configuration ──────────────────────────────────────────────

WORKER_COUNT: int = 30
_shutdown_event: asyncio.Event = asyncio.Event()
_worker_tasks: list[asyncio.Task] = []
_scheduler_task: Optional[asyncio.Task] = None


# ── Fetch chain from DB ──────────────────────────────────────


async def _get_tx_info(txid: str) -> tuple[Optional[str], Optional[str], bool]:
    """Fetch the chain, user_id, and telegram_sent for a TXID from the database."""
    from app.models.transaction import Transaction

    async with get_session() as session:
        stmt = select(Transaction.chain, Transaction.user_id, Transaction.telegram_sent).where(Transaction.txid == txid).limit(1)
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row:
            return row[0], row[1], row[2]
        return None, None, False


# ── Verifier bridge ───────────────────────────────────────────


async def _call_verifier(txid: str, chain: str) -> dict:
    """
    Call the verifier service for a TXID on the given chain.

    Returns a normalised dict with:
        success:   bool
        error:     str | None
        data:      { token, amount, sender, receiver, timestamp, confirmations }
    """
    try:
        from app.services.verifier import verify_tx
        result = await verify_tx(txid, chain)

        if isinstance(result, dict):
            return result

        return {"success": False, "error": "unexpected_result", "data": None}

    except ImportError:
        logger.error(
            "Verifier module not available — cannot process TX %s", txid[:16],
        )
        return {"success": False, "error": "verifier_unavailable", "data": None}
    except Exception as exc:
        logger.error(
            "Verifier raised for TX %s: %s", txid[:16], exc, exc_info=True,
        )
        return {"success": False, "error": "verifier_error", "data": None}


# ── Price conversion ─────────────────────────────────────────


async def _convert_to_fiat(token: str, amount: float) -> dict:
    """Convert crypto amount to USD and INR."""
    try:
        from app.services.price.converter import convert
        result = await convert(token, amount)
        return {
            "usd_value": result.get("total_usd", 0),
            "inr_value": result.get("total_inr", 0),
        }
    except Exception as exc:
        logger.warning("Price conversion failed for %s: %s", token, exc)
        return {"usd_value": None, "inr_value": None}


# ── DB update helpers ─────────────────────────────────────────


async def _update_tx_confirmed(txid: str, data: dict) -> None:
    """Write verification results to the database."""
    from app.models.transaction import Transaction, TransactionStatus

    async with get_session() as session:
        stmt = (
            select(Transaction)
            .where(Transaction.txid == txid)
            .with_for_update()
        )
        result = await session.execute(stmt)
        tx = result.scalar_one_or_none()

        if tx is None:
            logger.error("_update_tx_confirmed: TX %s not in DB", txid[:16])
            return

        tx.status = TransactionStatus.CONFIRMED
        tx.amount = data.get("amount")
        tx.usd_value = data.get("usd_value")
        tx.inr_value = data.get("inr_value")
        tx.sender_address = data.get("sender")
        tx.receiver_address = data.get("receiver")
        tx.verified_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(tx)

    logger.info(
        "TX %s CONFIRMED — amount=%.8f usd=%.2f inr=%.2f, DB update success, status changed to %s",
        txid[:16],
        data.get("amount", 0),
        data.get("usd_value", 0),
        data.get("inr_value", 0),
        tx.status.value
    )


async def _mark_tx_invalid(txid: str) -> None:
    """Mark a transaction as permanently failed."""
    from app.models.transaction import Transaction, TransactionStatus

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

    logger.warning("TX %s marked INVALID/FAILED in DB", txid[:16])


async def _set_telegram_sent(txid: str) -> None:
    """Mark a transaction as having sent its Telegram notification."""
    from app.models.transaction import Transaction

    async with get_session() as session:
        stmt = (
            update(Transaction)
            .where(Transaction.txid == txid)
            .values(telegram_sent=True)
        )
        await session.execute(stmt)

    logger.debug("TX %s marked telegram_sent=True in DB", txid[:16])


# ── Telegram notification ────────────────────────────────────


async def _notify_telegram(txid: str, chain: str, data: dict, user_id: str | None = None) -> None:
    """Send transaction notification to Telegram group, including UPI payout info."""
    try:
        upi_id = ""
        username = ""

        # Fetch user's UPI for payout info
        if user_id:
            try:
                from app.models.user import User
                async with get_session() as session:
                    stmt = select(User.default_upi, User.username).where(User.id == user_id).limit(1)
                    result = await session.execute(stmt)
                    row = result.one_or_none()
                    if row:
                        upi_id = row[0] or ""
                        username = row[1] or ""
            except Exception as exc:
                logger.warning("Failed to fetch UPI for user %s: %s", user_id, exc)

        from app.services.telegram.notifier import send_tx_notification
        await send_tx_notification({
            "txid": txid,
            "chain": chain,
            "token": data.get("token", ""),
            "amount": data.get("amount", 0),
            "usd": data.get("usd_value", 0),
            "inr": data.get("inr_value", 0),
            "sender": data.get("sender", ""),
            "receiver": data.get("receiver", ""),
            "timestamp": data.get("timestamp", 0),
            "upi_id": upi_id,
            "username": username,
        })
    except Exception as exc:
        logger.warning("Telegram notification failed for TX %s: %s", txid[:16], exc)


# ── Single job processor ──────────────────────────────────────


async def _process_single_tx(txid: str) -> None:
    """
    Full lifecycle for a single TXID.

    Lock → Fetch chain → Verify → Convert → Update DB → Notify → Release lock.
    Guarantees lock release even on exception.
    """
    lock: Optional[LockHandle] = None

    try:
        # ── 1. Acquire lock ────────────────────────────────────
        lock = await acquire_lock(txid)
        if not lock.acquired:
            logger.info("TX %s lock contention — skipping", txid[:16])
            return

        # ── 2. Mark processing in DB ───────────────────────────
        await update_tx_status_processing(txid)

        # ── 3. Get chain + user_id from DB ──────────────────────
        chain, user_id, telegram_sent = await _get_tx_info(txid)
        if not chain:
            logger.error("TX %s has no chain in DB — marking failed", txid[:16])
            await _mark_tx_invalid(txid)
            await mark_failed_permanent(txid)
            return

        # ── 4. Call verifier ───────────────────────────────────
        logger.info("TX %s → calling verifier (chain=%s)", txid[:16], chain)
        result = await _call_verifier(txid, chain)

        success = result.get("success", False)
        error = result.get("error")
        data = result.get("data") or {}

        # ── 5. Process result ──────────────────────────────────

        if success and data:
            # ✅ SUCCESS — convert prices, update DB, notify
            token = data.get("token", "")
            amount = data.get("amount", 0)

            if amount and token:
                fiat = await _convert_to_fiat(token, amount)
                data["usd_value"] = fiat["usd_value"]
                data["inr_value"] = fiat["inr_value"]

            await _update_tx_confirmed(txid, data)
            await mark_completed(txid)
            
            if not telegram_sent:
                await _notify_telegram(txid, chain, data, user_id=user_id)
                await _set_telegram_sent(txid)
            else:
                logger.info("TX %s telegram already sent — skipping", txid[:16])

            logger.info("TX %s ✓ verification complete, job removed from Redis", txid[:16])
            return

        elif error in ("tx_not_found", "tx_pending", "rpc_failure"):
            # 🔁 RETRYABLE — schedule retry
            logger.info("TX %s %s — scheduling retry", txid[:16], error)
            retried = await handle_retry(txid)
            if not retried:
                logger.warning("TX %s exhausted retries after %s", txid[:16], error)

        elif error in ("wallet_mismatch", "zero_amount", "invalid_txid",
                        "tx_failed", "unsupported_chain", "dust_transaction"):
            # ❌ PERMANENT FAILURE — no retry
            logger.warning("TX %s permanent failure: %s", txid[:16], error)
            await _mark_tx_invalid(txid)
            await mark_failed_permanent(txid)

        else:
            # ⚠️ Unknown error — treat as retryable
            logger.warning("TX %s unexpected error '%s' — retrying", txid[:16], error)
            await handle_retry(txid)

    except Exception:
        logger.exception("Unhandled error processing TX %s", txid[:16])
        try:
            await handle_retry(txid)
        except Exception:
            logger.exception("Failed to schedule retry for TX %s after crash", txid[:16])

    finally:
        if lock and lock.acquired:
            try:
                await release_lock(lock)
            except Exception:
                logger.exception("Failed to release lock for TX %s", txid[:16])


# ── Worker coroutine ──────────────────────────────────────────


async def _worker_loop(worker_id: int) -> None:
    """Continuous loop: dequeue → process → repeat."""
    logger.info("Worker-%03d started", worker_id)

    while not _shutdown_event.is_set():
        try:
            txid = await dequeue_tx(timeout=2)

            if txid is None:
                continue

            logger.info("Worker-%03d picked TX %s", worker_id, txid[:16])
            await _process_single_tx(txid)

        except asyncio.CancelledError:
            logger.info("Worker-%03d cancelled", worker_id)
            break
        except Exception:
            logger.exception("Worker-%03d unexpected error — restarting loop", worker_id)
            await asyncio.sleep(1)

    logger.info("Worker-%03d stopped", worker_id)


# ── Pool lifecycle ────────────────────────────────────────────


async def start_workers(count: Optional[int] = None) -> None:
    """Launch the worker pool and the retry scheduler."""
    global _worker_tasks, _scheduler_task

    n = count or WORKER_COUNT
    _shutdown_event.clear()

    _scheduler_task = await start_scheduler()
    logger.info("Retry scheduler launched")

    for i in range(n):
        task = asyncio.create_task(_worker_loop(i), name=f"tx-worker-{i:03d}")
        _worker_tasks.append(task)

    logger.info("Worker pool started: %d workers, scheduler active", n)


async def stop_workers(timeout: float = 10.0) -> None:
    """Gracefully stop all workers and the scheduler."""
    global _worker_tasks, _scheduler_task

    logger.info("Initiating worker pool shutdown…")
    _shutdown_event.set()

    if _worker_tasks:
        done, pending = await asyncio.wait(_worker_tasks, timeout=timeout)

        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=2.0)
            logger.warning("Force-cancelled %d worker tasks", len(pending))

        logger.info(
            "Worker pool drained: %d completed, %d cancelled",
            len(done), len(pending),
        )

    _worker_tasks.clear()
    await stop_scheduler()
    logger.info("Worker system fully stopped")
