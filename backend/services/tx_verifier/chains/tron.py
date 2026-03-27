"""
BITVORA EXCHANGE — Tron Chain Verifier (Production)
Handles: TRX and TRC20 tokens (USDT, USDC)

Ported from battle-tested Telegram bot blockchain.py.
Uses TronGrid v1 REST API with multi-endpoint failover.
"""

import logging
import time
from typing import Optional

import httpx

from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.tron")

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

TIMEOUT = httpx.Timeout(10.0)

# Multi-endpoint pool for Tron
TRON_RPC_ENDPOINTS: list[str] = [
    "https://api.trongrid.io",
    "https://tron.publicnode.com",
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
    Verify a Tron transaction via TronGrid REST API.
    Iterates over multiple TronGrid endpoints for resilience.
    Handles both native TRX transfers and TRC20 token events.
    """
    required_confs = settings.confirmation_thresholds.get("tron", 19)
    explorer_base = settings.explorer_base_urls.get("tron", "")
    wallet = expected_address.lower().strip()

    # Build RPC list — settings first, then fallbacks
    rpc_from_settings = settings.rpc_urls.get("tron")
    rpc_list = []
    if rpc_from_settings:
        rpc_list.append(rpc_from_settings)
    for ep in TRON_RPC_ENDPOINTS:
        if ep not in rpc_list:
            rpc_list.append(ep)

    headers: dict = {"Accept": "application/json"}

    last_result = None
    for rpc_url in rpc_list:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:

                # ── Step 1: Fetch transaction info ──
                info_resp = await client.get(
                    f"{rpc_url}/v1/transactions/{txid}",
                    params={"only_confirmed": "false"},
                )

                if info_resp.status_code == 404:
                    last_result = VerificationResult(valid=False, error="Transaction not found on Tron")
                    continue
                if info_resp.status_code == 429:
                    last_result = VerificationResult(valid=False, error="TronGrid API rate limited — retry shortly")
                    continue
                if info_resp.status_code != 200:
                    last_result = VerificationResult(valid=False, error=f"TronGrid API error: HTTP {info_resp.status_code}")
                    continue

                info_data = info_resp.json()
                if not isinstance(info_data, dict):
                    last_result = VerificationResult(valid=False, error="Unexpected TronGrid response format")
                    continue

                tx_list = info_data.get("data", [])
                if not tx_list:
                    last_result = VerificationResult(valid=False, error="Transaction not found on Tron")
                    continue

                tx_info = tx_list[0] if isinstance(tx_list, list) else {}

                # ── Step 2: Check transaction success status ──
                ret_list = tx_info.get("ret", [{}])
                contract_ret = (ret_list[0] if ret_list else {}).get("contractRet", "")
                if contract_ret and contract_ret != "SUCCESS":
                    logger.warning("Tron tx failed contractRet=%s txid=%s", contract_ret, txid)
                    return VerificationResult(valid=False, error=f"Transaction failed on-chain: {contract_ret}")

                # ── Step 3: Timestamp — 30-minute age check ──
                raw_ts = tx_info.get("block_timestamp")
                tx_time = int(raw_ts) // 1000 if raw_ts else 0

                if tx_time and (time.time() - tx_time > 1800):
                    return VerificationResult(
                        valid=False,
                        error="Transaction is older than 30 minutes! Please submit your latest transaction hash.",
                    )

                # ── Step 4: Detect transfer type ──
                contract = tx_info.get("raw_data", {}).get("contract", [{}])[0]
                contract_type = contract.get("type", "")

                if asset.upper() == "TRX" and contract_type == "TransferContract":
                    # Native TRX transfer
                    params = contract.get("parameter", {}).get("value", {})
                    recipient = params.get("to_address", "")
                    amount_sun = params.get("amount", 0)
                    amount_detected = amount_sun / 1_000_000  # sun to TRX

                    # Tron returns base58 addresses — compare case-insensitively
                    if recipient.lower() != wallet:
                        return VerificationResult(
                            valid=False,
                            recipient_address=recipient,
                            error=f"Recipient mismatch: expected {wallet[:10]}..., got {recipient[:10]}...",
                        )

                elif contract_type == "TriggerSmartContract":
                    # TRC20 token transfer — fetch Transfer events
                    events_resp = await client.get(
                        f"{rpc_url}/v1/transactions/{txid}/events",
                    )
                    if events_resp.status_code != 200:
                        last_result = VerificationResult(valid=False, error=f"Could not fetch Tron events: HTTP {events_resp.status_code}")
                        continue

                    events_data = events_resp.json()
                    if not isinstance(events_data, dict):
                        last_result = VerificationResult(valid=False, error="Unexpected Tron events format")
                        continue

                    events = events_data.get("data", [])

                    # Find Transfer to our wallet
                    amount_detected = 0.0
                    recipient = ""
                    found = False

                    for event in events:
                        if event.get("event_name") != "Transfer":
                            continue
                        result = event.get("result", {})
                        to_addr = (result.get("to") or "").lower().strip()
                        if to_addr != wallet:
                            continue
                        try:
                            raw_val = int(result.get("value", "0"))
                            amount_detected = raw_val / 1e6  # USDT TRC20 = 6 decimals
                        except (ValueError, TypeError):
                            continue
                        if amount_detected > 0:
                            found = True
                            recipient = to_addr
                            break

                    if not found or amount_detected <= 0:
                        return VerificationResult(
                            valid=False,
                            error="Recipient wallet does not match or token transfer amount is zero",
                        )

                else:
                    return VerificationResult(
                        valid=False, error=f"Unsupported Tron contract type: {contract_type}"
                    )

                # ── Step 5: Confirmations ──
                is_confirmed = tx_info.get("confirmed", False)
                confirmations = required_confs if is_confirmed else 0

                # ── Step 6: Amount validation (0.1% tolerance) ──
                tolerance = expected_amount * 0.001
                if abs(amount_detected - expected_amount) > tolerance:
                    return VerificationResult(
                        valid=False,
                        confirmations=confirmations,
                        required_confirmations=required_confs,
                        amount_detected=amount_detected,
                        recipient_address=recipient or wallet,
                        error=f"Amount mismatch: expected {expected_amount}, detected {amount_detected}",
                    )

                logger.info(
                    "Tron verified txid=%s amount=%.6f confirmations=%d",
                    txid[:16], amount_detected, confirmations,
                )

                return VerificationResult(
                    valid=True,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=amount_detected,
                    recipient_address=recipient or wallet,
                    explorer_url=f"{explorer_base}{txid}",
                )

        except Exception as e:
            logger.error("Tron verification error on %s: %s", rpc_url, e)
            last_result = VerificationResult(valid=False, error=f"Tron RPC error: {str(e)}")
            continue

    return last_result or VerificationResult(valid=False, error="Tron RPC verification failed on all endpoints")
