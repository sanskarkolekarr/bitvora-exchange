"""
BITVORA EXCHANGE — Solana Chain Verifier (Production)
Handles: SOL native and SPL tokens (USDT, USDC)

Ported from battle-tested Telegram bot blockchain.py.
Uses Solana JSON-RPC with balance delta detection and
parsed instruction fallback for maximum compatibility.
"""

import logging
import time
from typing import Optional

import httpx

from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.solana")

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

TIMEOUT = httpx.Timeout(12.0)

# Multi-endpoint pool for Solana
SOLANA_RPC_ENDPOINTS: list[str] = [
    "https://api.mainnet-beta.solana.com",
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
    Verify a Solana transaction via JSON-RPC.
    Uses dual detection strategy:
      1. Native SOL: balance delta of pre/post balances
      2. SPL Token: pre/post token balance comparison
    Falls back to parsed instruction check for SOL transfers.
    """
    required_confs = settings.confirmation_thresholds.get("solana", 1)
    explorer_base = settings.explorer_base_urls.get("solana", "")
    wallet = expected_address.strip()
    wallet_lower = wallet.lower()

    # Build RPC list — settings first, then fallbacks
    rpc_from_settings = settings.rpc_urls.get("solana")
    rpc_list = []
    if rpc_from_settings:
        rpc_list.append(rpc_from_settings)
    for ep in SOLANA_RPC_ENDPOINTS:
        if ep not in rpc_list:
            rpc_list.append(ep)

    last_result = None
    for rpc_url in rpc_list:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTransaction",
                        "params": [
                            txid,
                            {
                                "encoding": "jsonParsed",
                                "maxSupportedTransactionVersion": 0,
                                "commitment": "finalized",
                            },
                        ],
                    },
                )

            if resp.status_code == 429:
                last_result = VerificationResult(valid=False, error="Solana RPC rate limited — retry shortly")
                continue
            if resp.status_code != 200:
                last_result = VerificationResult(valid=False, error=f"Solana RPC error: HTTP {resp.status_code}")
                continue

            try:
                data = resp.json()
            except Exception:
                last_result = VerificationResult(valid=False, error="Invalid response from Solana RPC")
                continue

            if not isinstance(data, dict):
                last_result = VerificationResult(valid=False, error="Unexpected Solana response format")
                continue

            if "error" in data:
                err = data["error"]
                rpc_err = err.get("message", "Unknown RPC error") if isinstance(err, dict) else str(err)
                last_result = VerificationResult(valid=False, error=f"Solana RPC error: {rpc_err}")
                continue

            result = data.get("result")
            if not result:
                last_result = VerificationResult(valid=False, error="Transaction not found on Solana — may still be processing")
                continue

            # ── Transaction error check ──
            meta = result.get("meta", {})
            if not isinstance(meta, dict):
                return VerificationResult(valid=False, error="Invalid transaction metadata")

            if meta.get("err") is not None:
                err_detail = meta["err"]
                logger.warning("Solana tx failed err=%s txid=%s", err_detail, txid)
                return VerificationResult(valid=False, error=f"Transaction failed on Solana: {err_detail}")

            # ── Timestamp — 30-minute age check ──
            tx_time = result.get("blockTime", 0) or 0
            if tx_time and (time.time() - tx_time > 1800):
                return VerificationResult(
                    valid=False,
                    error="Transaction is older than 30 minutes! Please submit your latest transaction hash.",
                )

            # ── Confirmations — "finalized" = irreversible ──
            confirmations = required_confs  # Finalized commitment level = fully confirmed

            # ── Extract transfer amount ──
            tx_body = result.get("transaction", {})
            message = tx_body.get("message", {}) if isinstance(tx_body, dict) else {}
            pre_balances = meta.get("preBalances", [])
            post_balances = meta.get("postBalances", [])
            account_keys = message.get("accountKeys", [])

            amount_detected = 0.0
            recipient = ""
            found = False

            if asset.upper() == "SOL":
                # ── Strategy 1: SOL balance delta ──
                key_index: dict[str, int] = {}
                for i, key_entry in enumerate(account_keys):
                    if isinstance(key_entry, dict):
                        pubkey = key_entry.get("pubkey", "")
                    else:
                        pubkey = str(key_entry)
                    key_index[pubkey.lower()] = i

                wallet_idx = key_index.get(wallet_lower)
                if wallet_idx is not None and wallet_idx < len(pre_balances):
                    pre = pre_balances[wallet_idx]
                    post = post_balances[wallet_idx] if wallet_idx < len(post_balances) else pre
                    delta_lamports = post - pre
                    if delta_lamports > 0:
                        amount_detected = delta_lamports / 1e9
                        recipient = wallet
                        found = True

                # ── Strategy 2: Parsed instructions fallback ──
                if not found:
                    instructions = message.get("instructions", [])
                    if isinstance(instructions, list):
                        for ix in instructions:
                            if not isinstance(ix, dict):
                                continue
                            parsed = ix.get("parsed")
                            if not isinstance(parsed, dict):
                                continue
                            ix_type = parsed.get("type", "")
                            info = parsed.get("info", {})
                            if ix_type == "transfer" and isinstance(info, dict):
                                dest = (info.get("destination") or "").lower()
                                if dest == wallet_lower:
                                    try:
                                        lamports = int(info.get("lamports", 0))
                                    except (ValueError, TypeError):
                                        continue
                                    amount_detected = lamports / 1e9
                                    if amount_detected > 0:
                                        recipient = wallet
                                        found = True
                                        break

            else:
                # ── SPL Token: pre/post token balances ──
                pre_tokens = meta.get("preTokenBalances", [])
                post_tokens = meta.get("postTokenBalances", [])

                for post_bal in post_tokens:
                    owner = post_bal.get("owner", "")
                    if owner.lower() == wallet_lower:
                        post_amount = float(
                            post_bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0
                        )
                        # Find matching pre-balance
                        pre_amount = 0.0
                        for pre_bal in pre_tokens:
                            if pre_bal.get("owner", "").lower() == owner.lower():
                                pre_amount = float(
                                    pre_bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0
                                )
                                break
                        diff = post_amount - pre_amount
                        if diff > 0:
                            amount_detected = diff
                            recipient = owner
                            found = True
                            break

            if not found or amount_detected <= 0:
                logger.info("Solana: no transfer to wallet found — wallet=%s txid=%s", wallet, txid[:16])
                return VerificationResult(
                    valid=False,
                    error="Recipient wallet does not match or zero amount transferred",
                )

            # ── Amount validation (0.1% tolerance) ──
            tolerance = expected_amount * 0.001
            if abs(amount_detected - expected_amount) > tolerance:
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=amount_detected,
                    recipient_address=recipient,
                    error=f"Amount mismatch: expected {expected_amount}, detected {amount_detected}",
                )

            logger.info(
                "Solana verified txid=%s amount=%.9f confirmations=%d",
                txid[:16], amount_detected, confirmations,
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
            logger.error("Solana verification error on %s: %s", rpc_url, e)
            last_result = VerificationResult(valid=False, error=f"Solana RPC error: {str(e)}")
            continue

    return last_result or VerificationResult(valid=False, error="Solana RPC verification failed on all endpoints")
