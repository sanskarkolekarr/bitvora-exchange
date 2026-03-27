"""
BITVORA EXCHANGE — XRP (Ripple) Chain Verifier
Uses XRPL public API (xrplcluster.com)
"""

import logging
import httpx
from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.xrp")


async def verify_transaction(
    txid: str,
    chain: str,
    expected_address: str,
    expected_amount: float,
    asset: str,
) -> VerificationResult:
    """Verify an XRP transaction via XRPL public API."""
    api_base = settings.rpc_urls.get("xrp", "https://s1.ripple.com:51234")
    required_confs = settings.confirmation_thresholds.get("xrp", 1)
    explorer_base = settings.explorer_base_urls.get("xrp", "https://xrpscan.com/tx/")

    payload = {
        "method": "tx",
        "params": [{"transaction": txid, "binary": False}]
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(api_base, json=payload)
            if resp.status_code != 200:
                return VerificationResult(valid=False, error="XRP node unreachable")

            data = resp.json()
            result = data.get("result", {})

            if result.get("status") == "error":
                return VerificationResult(valid=False, error=f"TX not found: {result.get('error_message', 'unknown')}")

            tx = result

            # Check validation
            validated = tx.get("validated", False)
            if not validated:
                return VerificationResult(
                    valid=False,
                    confirmations=0,
                    required_confirmations=required_confs,
                    error="Transaction not yet validated on ledger",
                )

            # XRP doesn't use confirmations in the same way — validated = final
            confirmations = 1  # validated means confirmed

            # Check meta result
            meta = tx.get("meta", {})
            if meta.get("TransactionResult") != "tesSUCCESS":
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    error=f"TX failed on-chain: {meta.get('TransactionResult')}",
                )

            # Check destination
            dest = tx.get("Destination", "")
            if dest.lower() != expected_address.lower():
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    error="Destination address does not match deposit address",
                )

            # XRP amount (in drops, 1 XRP = 1,000,000 drops)
            amount_raw = tx.get("Amount", 0)
            if isinstance(amount_raw, str):
                amount_detected = int(amount_raw) / 1e6
            else:
                return VerificationResult(valid=False, error="Non-native XRP token — only XRP supported")

            # Validate amount (0.1% tolerance)
            tolerance = expected_amount * 0.001
            if abs(amount_detected - expected_amount) > tolerance:
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=amount_detected,
                    recipient_address=dest,
                    error=f"Amount mismatch: expected {expected_amount} XRP, got {amount_detected} XRP",
                )

            return VerificationResult(
                valid=True,
                confirmations=confirmations,
                required_confirmations=required_confs,
                amount_detected=amount_detected,
                recipient_address=dest,
                explorer_url=f"{explorer_base}{txid}",
            )

    except Exception as e:
        logger.error(f"XRP verification error: {e}")
        return VerificationResult(valid=False, error=f"Verification failed: {str(e)}")
