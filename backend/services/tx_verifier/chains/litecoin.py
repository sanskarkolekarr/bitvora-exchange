"""
BITVORA EXCHANGE — Litecoin Chain Verifier (Production)
Handles: LTC only

Ported from battle-tested Telegram bot blockchain.py.
Uses dual API strategy:
  1. Primary: BlockCypher API (double-spend detection, free tier)
  2. Fallback: Blockchair API
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.litecoin")

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

TIMEOUT = httpx.Timeout(12.0)


# ─────────────────────────────────────────────────────────────
# Public entry point — called by verification_queue.py
# ─────────────────────────────────────────────────────────────

async def verify_transaction(
    txid: str,
    chain: str,
    expected_address: str,
    expected_amount: float,
    asset: str,
) -> VerificationResult:
    """
    Verify a Litecoin transaction.
    Tries BlockCypher first (double-spend detection), then Blockchair fallback.
    """
    api_base = settings.rpc_urls.get("litecoin", "https://api.blockcypher.com/v1/ltc/main")
    required_confs = settings.confirmation_thresholds.get("litecoin", 3)
    explorer_base = settings.explorer_base_urls.get("litecoin", "https://blockchair.com/litecoin/transaction/")
    wallet = expected_address.lower().strip()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:

            # ── Primary: BlockCypher ──
            resp = await client.get(f"{api_base}/txs/{txid}", params={"limit": 50})

            if resp.status_code == 200:
                return _parse_blockcypher(
                    resp.json(), wallet, required_confs, explorer_base,
                    txid, expected_amount,
                )

            # ── Fallback: Blockchair ──
            logger.info("BlockCypher failed for LTC, trying Blockchair fallback")
            resp2 = await client.get(
                f"https://api.blockchair.com/litecoin/dashboards/transaction/{txid}"
            )
            if resp2.status_code == 200:
                return _parse_blockchair(
                    resp2.json(), wallet, required_confs, explorer_base,
                    txid, expected_amount,
                )

            return VerificationResult(valid=False, error="Transaction not found on Litecoin network")

    except Exception as e:
        logger.error("Litecoin verification error: %s", e)
        return VerificationResult(valid=False, error=f"Verification failed: {str(e)}")


# ─────────────────────────────────────────────────────────────
# BlockCypher parser (with double-spend detection)
# ─────────────────────────────────────────────────────────────

def _parse_blockcypher(
    data: dict,
    wallet: str,
    required: int,
    explorer_base: str,
    txid: str,
    expected_amount: float,
) -> VerificationResult:
    """Parse BlockCypher API response."""

    if not isinstance(data, dict):
        return VerificationResult(valid=False, error="Invalid BlockCypher response")

    # ── Double-spend check ──
    if data.get("double_spend", False):
        logger.warning("Double-spend detected for LTC txid=%s", txid)
        return VerificationResult(valid=False, error="Transaction flagged as double-spend — REJECTED")

    # ── Timestamp — 30-minute age check ──
    received_raw = data.get("received") or data.get("confirmed")
    if received_raw:
        try:
            received_raw = received_raw.replace("Z", "+00:00")
            tx_time = int(datetime.fromisoformat(received_raw).timestamp())
            if time.time() - tx_time > 1800:
                return VerificationResult(
                    valid=False,
                    error="Transaction is older than 30 minutes! Please submit your latest transaction hash.",
                )
        except Exception:
            pass

    # ── Confirmations ──
    confirmations = int(data.get("confirmations", 0))
    if confirmations == 0:
        return VerificationResult(
            valid=False, confirmations=0,
            required_confirmations=required,
            error="Transaction not yet confirmed",
        )

    # ── Amount to our wallet ──
    outputs = data.get("outputs", [])
    received_satoshis = 0
    for out in outputs:
        addresses = [a.lower() for a in out.get("addresses", [])]
        if wallet in addresses:
            received_satoshis += int(out.get("value", 0))

    if received_satoshis <= 0:
        return VerificationResult(
            valid=False, confirmations=confirmations,
            required_confirmations=required,
            error="No output matching deposit address found",
        )

    amount = received_satoshis / 1e8

    # ── Amount validation (0.1% tolerance) ──
    tolerance = expected_amount * 0.001
    if abs(amount - expected_amount) > tolerance:
        return VerificationResult(
            valid=False,
            confirmations=confirmations,
            required_confirmations=required,
            amount_detected=amount,
            recipient_address=wallet,
            error=f"Amount mismatch: expected {expected_amount} LTC, got {amount} LTC",
        )

    return VerificationResult(
        valid=True,
        confirmations=confirmations,
        required_confirmations=required,
        amount_detected=amount,
        recipient_address=wallet,
        explorer_url=f"{explorer_base}{txid}",
    )


# ─────────────────────────────────────────────────────────────
# Blockchair parser (fallback)
# ─────────────────────────────────────────────────────────────

def _parse_blockchair(
    data: dict,
    wallet: str,
    required: int,
    explorer_base: str,
    txid: str,
    expected_amount: float,
) -> VerificationResult:
    """Parse Blockchair API response as fallback."""
    try:
        tx_data = data.get("data", {}).get(txid, {})
        tx_info = tx_data.get("transaction", {})
        outputs = tx_data.get("outputs", [])

        block_id = tx_info.get("block_id", 0)
        if not block_id:
            return VerificationResult(
                valid=False, confirmations=0,
                required_confirmations=required,
                error="Not confirmed yet on Litecoin",
            )

        # Blockchair doesn't give easy confirmation count, use block_id as proxy
        confirmations = block_id  # Will be > 0 if mined

        for out in outputs:
            if out.get("recipient", "").lower() == wallet:
                value_ltc = out.get("value", 0) / 1e8

                tolerance = expected_amount * 0.001
                if abs(value_ltc - expected_amount) <= tolerance:
                    return VerificationResult(
                        valid=True,
                        confirmations=confirmations,
                        required_confirmations=required,
                        amount_detected=value_ltc,
                        recipient_address=wallet,
                        explorer_url=f"{explorer_base}{txid}",
                    )

                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required,
                    amount_detected=value_ltc,
                    error=f"Amount mismatch: expected {expected_amount} LTC, got {value_ltc} LTC",
                )

        return VerificationResult(
            valid=False, confirmations=confirmations,
            required_confirmations=required,
            error="No output matching deposit address",
        )

    except Exception as e:
        return VerificationResult(valid=False, error=f"Blockchair parse error: {e}")
