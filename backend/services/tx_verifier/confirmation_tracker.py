"""
BITVORA EXCHANGE — Confirmation Tracker Worker
Re-checks transactions in 'verifying' state for updated confirmation counts.
Uses Redis distributed locks to prevent duplicate processing.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from database import get_supabase
from config import settings
from services.telegram_bot import send_order_notification

logger = logging.getLogger("bitvora.worker.confirmation_tracker")


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
    else:
        return None
    return verify_transaction


async def confirmation_tracker_worker():
    """
    Runs every 25 seconds. Re-verifies 'verifying' transactions
    to track confirmation count progression.
    Uses Redis distributed lock to prevent duplicate processing.
    """
    logger.info("Confirmation tracker worker started")

    while True:
        try:
            await _track_confirmations()
        except asyncio.CancelledError:
            logger.info("Confirmation tracker worker cancelled")
            break
        except Exception as e:
            logger.error(f"Confirmation tracker error: {e}")

        await asyncio.sleep(25)


async def _track_confirmations():
    """Check all verifying transactions for updated confirmations."""
    from services.tx_verifier.distributed_lock import (
        acquire_lock,
        release_lock,
        sync_lock_to_supabase,
    )

    db = get_supabase()
    worker_id = f"ct-{uuid.uuid4().hex[:8]}"

    result = (
        db.table("transactions")
        .select("*")
        .eq("status", "verifying")
        .execute()
    )

    for tx in result.data:
        tx_id = tx["id"]
        chain = tx["chain"]
        required = tx.get("required_confirmations", 1)

        # Acquire distributed lock (short TTL for confirmation checks)
        lock_value = await acquire_lock(tx_id, worker_id, ttl_ms=60_000)
        if not lock_value:
            continue  # Another worker is handling this transaction

        try:
            verifier = await _get_verifier(chain)
            if not verifier:
                continue

            try:
                result_v = await verifier(
                    txid=tx["txid"],
                    chain=chain,
                    expected_address=tx["deposit_address"],
                    expected_amount=float(tx.get("amount_crypto", 0)),
                    asset=tx["asset"],
                )
            except Exception as e:
                logger.error(f"Confirmation check failed for {tx_id}: {e}")
                continue

            new_confs = result_v.confirmations

            if new_confs >= required:
                # Threshold met — advance to payout_queued
                now = datetime.now(timezone.utc).isoformat()
                db.table("transactions").update(
                    {
                        "status": "payout_queued",
                        "confirmations": new_confs,
                        "verified_at": now,
                        "payout_queued_at": now,
                    }
                ).eq("id", tx_id).execute()

                # Insert payout queue entry
                db.table("payout_queue").insert(
                    {
                        "id": str(uuid.uuid4()),
                        "transaction_id": tx_id,
                        "payout_destination": tx.get("payout_destination", ""),
                        "amount_inr": tx.get("amount_inr", 0),
                        "status": "pending",
                        "queued_at": now,
                    }
                ).execute()

                # Send notification
                user_res = (
                    db.table("users")
                    .select("username")
                    .eq("id", tx["user_id"])
                    .execute()
                )
                tx["username"] = (
                    user_res.data[0]["username"] if user_res.data else "Unknown"
                )
                await send_order_notification(tx)

                logger.info(
                    f"Transaction {tx_id} reached {new_confs}/{required} "
                    f"confirmations — queued for payout"
                )
            elif new_confs != tx.get("confirmations", 0):
                # Update confirmation count
                db.table("transactions").update(
                    {"confirmations": new_confs}
                ).eq("id", tx_id).execute()

                logger.debug(
                    f"Transaction {tx_id}: {new_confs}/{required} confirmations"
                )

        finally:
            await release_lock(tx_id, lock_value)
