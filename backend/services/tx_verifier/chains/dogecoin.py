"""
BITVORA EXCHANGE — Dogecoin Chain Verifier
Uses BlockCypher API (same as Litecoin) + Dogechain fallback
"""

import logging
import httpx
from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.dogecoin")


async def verify_transaction(
    txid: str,
    chain: str,
    expected_address: str,
    expected_amount: float,
    asset: str,
) -> VerificationResult:
    """Verify a Dogecoin transaction via BlockCypher API."""
    api_base = settings.rpc_urls.get("dogecoin", "https://api.blockcypher.com/v1/doge/main")
    required_confs = settings.confirmation_thresholds.get("dogecoin", 6)
    explorer_base = settings.explorer_base_urls.get("dogecoin", "https://blockchair.com/dogecoin/transaction/")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{api_base}/txs/{txid}?limit=50&includeHex=false")
            if resp.status_code != 200:
                # Fallback: Blockchair
                resp2 = await client.get(f"https://api.blockchair.com/dogecoin/dashboards/transaction/{txid}")
                if resp2.status_code != 200:
                    return VerificationResult(valid=False, error="Transaction not found on Dogecoin network")
                return await _parse_blockchair(resp2.json(), expected_address, expected_amount, required_confs, explorer_base, txid)

            tx = resp.json()
            confirmations = tx.get("confirmations", 0)

            if confirmations == 0:
                return VerificationResult(
                    valid=False,
                    confirmations=0,
                    required_confirmations=required_confs,
                    error="Transaction not yet confirmed",
                )

            recipient = ""
            amount_detected = 0.0

            for output in tx.get("outputs", []):
                addrs = output.get("addresses", [])
                value_satoshis = output.get("value", 0)
                value_doge = value_satoshis / 1e8

                if expected_address.lower() in [a.lower() for a in addrs]:
                    recipient = expected_address
                    amount_detected = value_doge
                    break

            if not recipient:
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    error="No output matching deposit address found",
                )

            tolerance = expected_amount * 0.001
            if abs(amount_detected - expected_amount) > tolerance:
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=amount_detected,
                    recipient_address=recipient,
                    error=f"Amount mismatch: expected {expected_amount} DOGE, got {amount_detected} DOGE",
                )

            return VerificationResult(
                valid=True,
                confirmations=confirmations,
                required_confirmations=required_confs,
                amount_detected=amount_detected,
                recipient_address=recipient,
                explorer_url=f"{explorer_base}{txid}",
            )

    except Exception as e:
        logger.error(f"Dogecoin verification error: {e}")
        return VerificationResult(valid=False, error=f"Verification failed: {str(e)}")


async def _parse_blockchair(data: dict, expected_address: str, expected_amount: float, required_confs: int, explorer_base: str, txid: str) -> VerificationResult:
    try:
        tx_data = data.get("data", {}).get(txid, {})
        tx = tx_data.get("transaction", {})
        outputs = tx_data.get("outputs", [])
        confirmations = tx.get("block_id", 0)
        if not confirmations:
            return VerificationResult(valid=False, confirmations=0, required_confirmations=required_confs, error="Not confirmed yet")
        for out in outputs:
            if out.get("recipient", "").lower() == expected_address.lower():
                value_doge = out.get("value", 0) / 1e8
                tolerance = expected_amount * 0.001
                if abs(value_doge - expected_amount) <= tolerance:
                    return VerificationResult(valid=True, confirmations=confirmations, required_confirmations=required_confs, amount_detected=value_doge, recipient_address=expected_address, explorer_url=f"{explorer_base}{txid}")
                return VerificationResult(valid=False, confirmations=confirmations, required_confirmations=required_confs, amount_detected=value_doge, error=f"Amount mismatch: expected {expected_amount} DOGE, got {value_doge} DOGE")
        return VerificationResult(valid=False, confirmations=confirmations, required_confirmations=required_confs, error="No output matching deposit address")
    except Exception as e:
        return VerificationResult(valid=False, error=f"Blockchair parse error: {e}")
