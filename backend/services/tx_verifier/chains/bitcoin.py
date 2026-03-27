"""
BITVORA EXCHANGE — Bitcoin Chain Verifier (Production)
Handles: BTC only

Ported from battle-tested Telegram bot blockchain.py.
Uses dual API strategy:
  1. Primary: Blockstream API (free, no key required)
  2. Fallback: BlockCypher API (double-spend detection)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.bitcoin")

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

TIMEOUT = httpx.Timeout(12.0)

# Multi-endpoint pool
BTC_API_ENDPOINTS = [
    {"type": "blockstream", "base": "https://blockstream.info/api"},
    {"type": "blockcypher", "base": "https://api.blockcypher.com/v1/btc/main"},
]


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
    Verify a Bitcoin transaction.
    Tries Blockstream first, then BlockCypher as fallback.
    """
    required_confs = settings.confirmation_thresholds.get("bitcoin", 2)
    explorer_base = settings.explorer_base_urls.get("bitcoin", "")
    wallet = expected_address.lower().strip()

    last_result = None
    for endpoint in BTC_API_ENDPOINTS:
        try:
            if endpoint["type"] == "blockstream":
                result = await _verify_blockstream(
                    txid, wallet, required_confs, endpoint["base"], explorer_base, expected_amount,
                )
            else:
                result = await _verify_blockcypher(
                    txid, wallet, required_confs, endpoint["base"], explorer_base, expected_amount,
                )

            if result.valid:
                return result

            # Stop on definitive business logic failures
            if result.error:
                err = result.error.lower()
                if any(kw in err for kw in ["mismatch", "double-spend", "zero", "older"]):
                    return result

            last_result = result

        except Exception as e:
            logger.error("Bitcoin verification error via %s: %s", endpoint["type"], e)
            last_result = VerificationResult(valid=False, error=f"Verification failed: {str(e)}")

    return last_result or VerificationResult(valid=False, error="Bitcoin verification failed on all endpoints")


# ─────────────────────────────────────────────────────────────
# Blockstream API (Primary)
# ─────────────────────────────────────────────────────────────

async def _verify_blockstream(
    txid: str,
    wallet: str,
    required: int,
    api_base: str,
    explorer_base: str,
    expected_amount: float,
) -> VerificationResult:
    """Verify via Blockstream's free REST API."""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{api_base}/tx/{txid}")
        if resp.status_code != 200:
            return VerificationResult(valid=False, error="Transaction not found on Bitcoin")

        tx = resp.json()

        # ── Timestamp — 30-minute age check ──
        status = tx.get("status", {})
        tx_time = status.get("block_time", 0)
        if tx_time and (time.time() - tx_time > 1800):
            return VerificationResult(
                valid=False,
                error="Transaction is older than 30 minutes! Please submit your latest transaction hash.",
            )

        # ── Confirmation status ──
        if not status.get("confirmed", False):
            return VerificationResult(
                valid=False, confirmations=0,
                required_confirmations=required,
                error="Transaction not yet confirmed",
            )

        tx_block_height = status.get("block_height", 0)

        # Get current block height
        height_resp = await client.get(f"{api_base}/blocks/tip/height")
        current_height = 0
        if height_resp.status_code == 200:
            try:
                current_height = int(height_resp.text.strip())
            except ValueError:
                pass

        confirmations = max(0, current_height - tx_block_height + 1) if current_height else 0

        # ── Check outputs ──
        recipient = ""
        amount_detected = 0.0

        for vout in tx.get("vout", []):
            addr = vout.get("scriptpubkey_address", "")
            value_sats = vout.get("value", 0)
            if addr.lower() == wallet:
                recipient = addr
                amount_detected += value_sats / 1e8  # Aggregate all outputs to our wallet

        if not recipient:
            return VerificationResult(
                valid=False, confirmations=confirmations,
                required_confirmations=required,
                error="No output matching deposit address found — funds sent to wrong address",
            )

        if amount_detected <= 0:
            return VerificationResult(valid=False, error="Transaction value is zero")

        # ── Amount validation (0.1% tolerance) ──
        tolerance = expected_amount * 0.001
        if abs(amount_detected - expected_amount) > tolerance:
            return VerificationResult(
                valid=False,
                confirmations=confirmations,
                required_confirmations=required,
                amount_detected=amount_detected,
                recipient_address=recipient,
                error=f"Amount mismatch: expected {expected_amount} BTC, got {amount_detected} BTC",
            )

        return VerificationResult(
            valid=True,
            confirmations=confirmations,
            required_confirmations=required,
            amount_detected=amount_detected,
            recipient_address=recipient,
            explorer_url=f"{explorer_base}{txid}",
        )


# ─────────────────────────────────────────────────────────────
# BlockCypher API (Fallback — has double-spend detection)
# ─────────────────────────────────────────────────────────────

async def _verify_blockcypher(
    txid: str,
    wallet: str,
    required: int,
    api_base: str,
    explorer_base: str,
    expected_amount: float,
) -> VerificationResult:
    """Verify via BlockCypher API. Includes double-spend detection."""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{api_base}/txs/{txid}", params={"limit": 50})

        if resp.status_code == 404:
            return VerificationResult(valid=False, error="Transaction not found")
        if resp.status_code == 429:
            return VerificationResult(valid=False, error="BlockCypher API rate limited")
        if resp.status_code != 200:
            return VerificationResult(valid=False, error=f"BlockCypher API error: HTTP {resp.status_code}")

        data = resp.json()

        # ── Double-spend check (BlockCypher exclusive feature) ──
        if data.get("double_spend", False):
            logger.warning("Double-spend detected for BTC txid=%s", txid)
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
                pass  # Continue without timestamp check

        # ── Amount to our wallet ──
        outputs = data.get("outputs", [])
        received_satoshis = 0
        for out in outputs:
            addresses = [a.lower() for a in out.get("addresses", [])]
            if wallet in addresses:
                received_satoshis += int(out.get("value", 0))

        if received_satoshis <= 0:
            return VerificationResult(
                valid=False,
                error="No output matching deposit address — funds sent to wrong address",
            )

        amount = received_satoshis / 1e8
        confirmations = int(data.get("confirmations", 0))

        # ── Amount validation ──
        tolerance = expected_amount * 0.001
        if abs(amount - expected_amount) > tolerance:
            return VerificationResult(
                valid=False,
                confirmations=confirmations,
                required_confirmations=required,
                amount_detected=amount,
                recipient_address=wallet,
                error=f"Amount mismatch: expected {expected_amount} BTC, got {amount} BTC",
            )

        return VerificationResult(
            valid=True,
            confirmations=confirmations,
            required_confirmations=required,
            amount_detected=amount,
            recipient_address=wallet,
            explorer_url=f"{explorer_base}{txid}",
        )
