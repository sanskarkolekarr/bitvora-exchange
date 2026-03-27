"""
BITVORA EXCHANGE — Late Payment Sweeper
Mirrors the Telegram bot's late_sweeper.py exactly.

Runs every 300 seconds (5 minutes).
Scans all 'monitoring_expired' transactions that have a TXID.
If funds are found on-chain → marks as 'late_recovery' and alerts admin.

This is the safety net that catches:
  - Users who sent funds seconds after order expiry
  - RPC lag that caused the order to expire before verification succeeded
  - AA/bundled transactions that took longer to index
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from database import get_supabase
from config import settings
from services.txlock import lock_txid, is_txid_used
from services.telegram_bot import bot

logger = logging.getLogger("bitvora.worker.sweeper")


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


async def late_sweeper_worker():
    """
    Background task: every 5 minutes, scan monitoring_expired orders.
    Mirrors the bot's services/late_sweeper.py loop.
    """
    logger.info("Late Sweeper worker started (300s interval)")

    while True:
        try:
            await asyncio.sleep(300)
            await _sweep_late_transactions()
        except asyncio.CancelledError:
            logger.info("Late Sweeper cancelled")
            break
        except Exception as e:
            logger.error("Late Sweeper error: %s", e)


async def _sweep_late_transactions():
    """
    Check all monitoring_expired orders with a TXID for late payments.
    Window: up to 48 hours after creation.
    """
    db = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    result = (
        db.table("transactions")
        .select("*")
        .eq("status", "monitoring_expired")
        .neq("txid", "")
        .gte("created_at", cutoff)
        .execute()
    )

    if not result.data:
        return

    # Pre-filter already-used TXIDs (already paid out via another order)
    candidates = [tx for tx in result.data if not is_txid_used(tx.get("txid", ""))]
    if not candidates:
        return

    logger.info("Late Sweeper: checking %d monitoring_expired orders...", len(candidates))

    for tx in candidates:
        tx_id = tx["id"]
        txid = tx.get("txid", "")
        chain = tx.get("chain", "")
        reference = tx.get("reference", tx_id[:8])

        if not txid or not chain:
            continue

        try:
            verifier = await _get_verifier(chain)
            if not verifier:
                continue

            # For the sweeper, we deliberately pass NO order_created_at
            # because we WANT to find funds even if they arrived after order expiry.
            # The timing check is bypassed here — that's the whole point of late recovery.
            import inspect
            verifier_sig = inspect.signature(verifier)
            call_kwargs = dict(
                txid=txid,
                chain=chain,
                expected_address=tx.get("deposit_address", ""),
                expected_amount=float(tx.get("amount_crypto", 0)),
                asset=tx.get("asset", ""),
            )
            # Pass order_created_at=None explicitly (skip timing gate for recovery)
            if "order_created_at" in verifier_sig.parameters:
                call_kwargs["order_created_at"] = None

            result_v = await verifier(**call_kwargs)

            if not result_v.valid:
                # Still not found — skip this cycle, will retry in 5 min
                continue

            required_confs = settings.confirmation_thresholds.get(chain, 1)
            if result_v.confirmations < required_confs:
                # Found but not confirmed enough yet
                continue

            # ── Late funds confirmed! ──
            logger.warning(
                "🚨 LATE FUNDS DETECTED: order=%s chain=%s amount=%.6f txid=%s",
                reference, chain, result_v.amount_detected, txid[:20],
            )

            now = datetime.now(timezone.utc).isoformat()
            lock_txid(txid)  # Prevent reuse

            db.table("transactions").update({
                "status": "late_recovery",
                "error_message": "LATE FUNDS ARRIVED — requires admin review",
                "confirmations": result_v.confirmations,
                "amount_crypto_received": result_v.amount_detected,
                "verified_at": now,
            }).eq("id", tx_id).execute()

            # Auto-open support ticket
            try:
                db.table("support_tickets").insert({
                    "id": str(uuid.uuid4()),
                    "user_id": tx.get("user_id"),
                    "subject": f"LATE FUNDS — {reference}",
                    "message": (
                        f"SYSTEM ALERT: Late funds detected for expired order.\n"
                        f"Amount received: {result_v.amount_detected:.8f} {tx.get('asset', '')}\n"
                        f"Required: {tx.get('amount_crypto', '?')} {tx.get('asset', '')}\n"
                        f"TXID: {txid}\n"
                        f"Explorer: {result_v.explorer_url or 'N/A'}"
                    ),
                    "status": "open",
                }).execute()
            except Exception as e:
                logger.error("Failed to create support ticket for tx=%s: %s", tx_id[:8], e)

            # Admin Telegram notification
            if bot and settings.TG_CHAT_ID:
                msg = (
                    f"🚨 <b>LATE FUNDS DETECTED</b> 🚨\n\n"
                    f"Order <code>{reference}</code> expired but funds arrived!\n"
                    f"<b>Chain:</b> {chain.upper()}\n"
                    f"<b>Amount:</b> {result_v.amount_detected:.8f} {tx.get('asset', '')}\n"
                    f"<b>TXID:</b> <code>{txid[:30]}</code>\n"
                    f"<b>Explorer:</b> {result_v.explorer_url or 'N/A'}\n\n"
                    f"Support ticket opened. Manual review required."
                )
                try:
                    await bot.send_message(
                        chat_id=settings.TG_CHAT_ID,
                        text=msg,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error("Failed to notify admin of late funds: %s", e)

        except Exception as e:
            logger.error("Sweeper exception on tx=%s: %s", tx_id[:8], e, exc_info=True)
