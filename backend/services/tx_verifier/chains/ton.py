"""
BITVORA EXCHANGE — TON Chain Verifier
Handles: TON and Jetton tokens
"""

import logging
from typing import Optional
import httpx
from config import settings

logger = logging.getLogger("bitvora.verifier.ton")


from ..models import VerificationResult

async def verify_transaction(
    txid: str,
    chain: str,
    expected_address: str,
    expected_amount: float,
    asset: str,
) -> VerificationResult:
    """Verify a TON transaction via TON Center API."""
    api_base = settings.rpc_urls.get("ton", "https://toncenter.com/api/v2")
    required_confs = settings.confirmation_thresholds.get("ton", 1)
    explorer_base = settings.explorer_base_urls.get("ton", "")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get recent transactions for the deposit address
            resp = await client.get(
                f"{api_base}/getTransactions",
                params={
                    "address": expected_address,
                    "limit": 50,
                    "archival": "true",
                },
            )

            if resp.status_code != 200:
                return VerificationResult(
                    valid=False, error="TON API request failed"
                )

            data = resp.json()

            if not data.get("ok"):
                return VerificationResult(
                    valid=False, error="TON API returned error"
                )

            transactions = data.get("result", [])

            # Find the transaction by hash
            matched_tx = None
            for tx in transactions:
                tx_hash = tx.get("transaction_id", {}).get("hash", "")
                # TON hashes can be base64 encoded — normalize
                if tx_hash == txid or tx_hash.replace("+", "-").replace("/", "_") == txid:
                    matched_tx = tx
                    break

            if not matched_tx:
                return VerificationResult(
                    valid=False,
                    error="Transaction not found in recent history for deposit address",
                )

            # Check transaction age (older than 30 mins)
            import time
            tx_time = matched_tx.get("utime", 0)
            if tx_time:
                if time.time() - tx_time > 1800:
                    return VerificationResult(
                        valid=False, error="Transaction is older than 30 minutes! Please submit your latest transaction hash."
                    )

            # Parse amount
            in_msg = matched_tx.get("in_msg", {})

            if asset.upper() == "TON":
                # Native TON transfer
                value_nanoton = int(in_msg.get("value", 0))
                amount_detected = value_nanoton / 1e9  # nanoton to TON
                source = in_msg.get("source", "")
            else:
                # Jetton transfer — parse message body
                # For Jettons, the value is in the message body
                amount_detected = 0.0
                source = in_msg.get("source", "")

                # Try parsing the body for jetton amount
                msg_body = in_msg.get("msg_data", {}).get("body", "")
                if msg_body:
                    try:
                        # Jetton transfer notification contains amount
                        raw = int(in_msg.get("value", 0))
                        amount_detected = raw / 1e6  # USDT on TON uses 6 decimals
                    except (ValueError, TypeError):
                        pass

                if amount_detected == 0:
                    return VerificationResult(
                        valid=False,
                        error="Could not parse Jetton transfer amount",
                    )

            confirmations = 1  # If found, it's finalized on TON

            # Validate amount (0.1% tolerance)
            tolerance = expected_amount * 0.001
            if abs(amount_detected - expected_amount) > tolerance:
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=amount_detected,
                    recipient_address=expected_address,
                    error=f"Amount mismatch: expected {expected_amount}, got {amount_detected}",
                )

            return VerificationResult(
                valid=True,
                confirmations=confirmations,
                required_confirmations=required_confs,
                amount_detected=amount_detected,
                recipient_address=expected_address,
                explorer_url=f"{explorer_base}{txid}",
            )

    except Exception as e:
        logger.error(f"TON verification error: {e}")
        return VerificationResult(valid=False, error=f"Verification failed: {str(e)}")
