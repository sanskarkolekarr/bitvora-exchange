"""
BITVORA EXCHANGE — Pending Transaction Watcher
Mirrors Telegram bot watcher behavior exactly.

Loop (every 120s):
  1. Fetch all "pending" transactions that have a TXID but are unverified
  2. Also re-check "verifying" transactions (have confs but not enough)
  3. Call verify_transaction WITH order_created_at for timing validation
  4. On success → lock TXID, queue payout, notify admin
  5. On soft failure → leave as pending (retry next cycle)
  6. On hard failure → mark as failed immediately

Hard failures (don't retry):
  - reverted on-chain
  - recipient mismatch
  - tx predates order
  - TXID already used

Soft failures (retry next cycle):
  - TX not found yet (propagating)
  - pending (mempool)
  - insufficient confirmations
  - RPC/explorer errors
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from database import get_supabase
from config import settings
from services.txlock import lock_txid, is_txid_used
from services.telegram_bot import send_order_notification

logger = logging.getLogger("bitvora.worker.watcher")


async def _get_verifier(chain: str):
    """Route chain to the correct verifier module."""
    family = settings.chain_families.get(chain)
    if family == "evm":
        from services.tx_verifier.chains.evm import verify_transaction
    elif family == "tron":
        from services.tx_verifier.chains.tron import verify_transaction
    elif family == "solana":
        from services.tx_verifier.chains.solana import verify_transaction
    elif family == "bitcoin":
        from services.tx_verifier.chains.bitcoin import verify_transaction
    elif family == "litecoin":
        from services.tx_verifier.chains.litecoin import verify_transaction
    elif family == "ton":
        from services.tx_verifier.chains.ton import verify_transaction
    else:
        return None
    return verify_transaction


async def pending_tx_watcher():
    """
    Main watcher loop. Runs every 120 seconds.
    Mirrors the Telegram bot's pending_tx_watcher exactly.
    """
    logger.info("Pending TX watcher started (interval=120s)")
    while True:
        try:
            await asyncio.sleep(120)
            await _run_watcher_cycle()
        except asyncio.CancelledError:
            logger.info("Pending TX watcher cancelled")
            break
        except Exception as e:
            logger.error("Watcher cycle error: %s", e, exc_info=True)


async def _run_watcher_cycle():
    """
    Single watcher cycle. Fetches all pending + verifying orders with TXIDs
    and attempts verification with full order context (including created_at).
    """
    from services.tx_verifier.distributed_lock import acquire_lock, release_lock

    db = get_supabase()
    worker_id = f"watcher-{uuid.uuid4().hex[:8]}"

    # Fetch pending AND verifying orders that have a submitted TXID
    # "verifying" = valid TX, but not enough confirmations yet
    result = (
        db.table("transactions")
        .select("*")
        .in_("status", ["pending", "verifying", "pending_retry"])
        .neq("txid", "")
        .execute()
    )

    if not result.data:
        return

    logger.info("Watcher cycle: %d orders to check", len(result.data))

    for tx in result.data:
        tx_id = tx["id"]
        txid = tx.get("txid", "")
        chain = tx.get("chain", "")
        order_created_at = tx.get("created_at")  # ISO8601 from Supabase

        if not txid or not chain:
            continue

        # ── TXID Duplicate Prevention ──
        if is_txid_used(txid):
            db.table("transactions").update({
                "status": "failed",
                "error_message": "This transaction ID has already been used for another order",
            }).eq("id", tx_id).execute()
            logger.warning("Watcher: TXID %s already used — marked as failed", txid[:16])
            continue

        # ── Distributed lock (prevent duplicate processing) ──
        lock_value = await acquire_lock(tx_id, worker_id, ttl_ms=120_000)
        if not lock_value:
            continue  # Another worker has this one

        try:
            verifier = await _get_verifier(chain)
            if not verifier:
                logger.warning("No verifier for chain=%s tx=%s", chain, tx_id[:8])
                continue

            logger.info(
                "Watcher checking: tx=%s chain=%s txid=%s status=%s",
                tx_id[:8], chain, txid[:16] + "...", tx.get("status"),
            )

            # Call verifier WITH order_created_at for bot-identical timing validation
            import inspect
            verifier_sig = inspect.signature(verifier)
            supports_created_at = "order_created_at" in verifier_sig.parameters

            if supports_created_at:
                result_v = await verifier(
                    txid=txid,
                    chain=chain,
                    expected_address=tx.get("deposit_address", ""),
                    expected_amount=float(tx.get("amount_crypto", 0)),
                    asset=tx.get("asset", ""),
                    order_created_at=order_created_at,
                )
            else:
                # Older verifiers (BTC, LTC, Tron, Solana) — no timing param yet
                result_v = await verifier(
                    txid=txid,
                    chain=chain,
                    expected_address=tx.get("deposit_address", ""),
                    expected_amount=float(tx.get("amount_crypto", 0)),
                    asset=tx.get("asset", ""),
                )

            # ── Handle result ──
            await _handle_result(db, tx, result_v, worker_id)

        except Exception as e:
            logger.error("Watcher exception for tx=%s: %s", tx_id[:8], e, exc_info=True)
        finally:
            await release_lock(tx_id, lock_value)


async def _handle_result(db, tx, result_v, worker_id: str):
    """
    Apply the verification result to the database.
    Exactly mirrors bot's if success / if failure logic.
    """
    tx_id = tx["id"]
    txid = tx.get("txid", "")
    chain = tx.get("chain", "")

    if not result_v.valid:
        # ── Use model's is_hard_failure (clean categorisation) ──
        if result_v.is_hard_failure:
            db.table("transactions").update({
                "status": "failed",
                "error_message": result_v.error,
            }).eq("id", tx_id).execute()
            logger.info("Watcher: tx=%s HARD FAIL: %s", tx_id[:8], result_v.error)
        else:
            # Soft fail — leave as pending/verifying, retry on next cycle
            logger.info(
                "Watcher: tx=%s SOFT FAIL (retry next cycle): %s",
                tx_id[:8], result_v.error,
            )
        return

    # ── TX is VALID ──
    lock_txid(txid)  # Permanently lock TXID to prevent reuse

    required_confs = settings.confirmation_thresholds.get(chain, 1)
    now = datetime.now(timezone.utc).isoformat()

    if result_v.confirmations >= required_confs:
        # Fully confirmed → queue for payout
        db.table("transactions").update({
            "status": "payout_queued",
            "confirmations": result_v.confirmations,
            "verified_at": now,
            "payout_queued_at": now,
            "amount_crypto_received": result_v.amount_detected,  # Record actual received amount
        }).eq("id", tx_id).execute()

        # Insert into payout queue
        try:
            db.table("payout_queue").insert({
                "id": str(uuid.uuid4()),
                "transaction_id": tx_id,
                "payout_destination": tx.get("payout_destination", ""),
                "amount_inr": tx.get("amount_inr", 0),
                "status": "pending",
                "queued_at": now,
            }).execute()
        except Exception as e:
            logger.error("Failed to insert payout queue for tx=%s: %s", tx_id[:8], e)

        # Admin Telegram notification
        try:
            user_res = db.table("users").select("username").eq("id", tx["user_id"]).execute()
            tx["username"] = user_res.data[0]["username"] if user_res.data else "Unknown"
            await send_order_notification(tx)
        except Exception as e:
            logger.error("Notification failed for tx=%s: %s", tx_id[:8], e)

        logger.info(
            "✅ Watcher: tx=%s CONFIRMED — %.8f received, %d/%d confs → payout_queued",
            tx_id[:8], result_v.amount_detected, result_v.confirmations, required_confs,
        )

    else:
        # Valid TX, waiting for more confirmations
        db.table("transactions").update({
            "status": "verifying",
            "confirmations": result_v.confirmations,
            "required_confirmations": required_confs,
        }).eq("id", tx_id).execute()

        logger.info(
            "⏳ Watcher: tx=%s VALID — %d/%d confs, waiting...",
            tx_id[:8], result_v.confirmations, required_confs,
        )
