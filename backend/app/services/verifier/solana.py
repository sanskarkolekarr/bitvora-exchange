"""
Solana transaction verifier.
Uses solana-py SDK (if available) or raw HTTP JSON-RPC fallback.

CONFIG-DRIVEN: RPC endpoints and deposit addresses from settings.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

from app.core.config import settings
from app.core.logger import get_logger
from app.services.verifier.validators import (
    validate_confirmations,
    validate_amount,
    validate_receiver,
    validate_timestamp,
)

logger = get_logger("verifier.solana")

CHAIN = "solana"
MAX_RETRIES = 5
TIMEOUT_S = 15
LAMPORTS = 1_000_000_000  # 1 SOL = 1 000 000 000 lamports


def _get_sol_endpoints() -> list[str]:
    config_rpcs = settings.rpc_endpoint_lists.get(CHAIN, [])
    fallbacks = [
        "https://api.mainnet-beta.solana.com",
    ]
    combined = config_rpcs + [fb for fb in fallbacks if fb not in config_rpcs]
    return list(dict.fromkeys(combined))


async def _rpc_call(method: str, params: list[Any]) -> Any:
    """Make JSON-RPC call to Solana nodes."""
    endpoints = _get_sol_endpoints()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    
    last: Optional[Exception] = None
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            base = endpoints[attempt % len(endpoints)]
            try:
                async with session.post(
                    base, json=payload, timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)
                ) as r:
                    if r.status != 200:
                        raise ConnectionError(f"HTTP {r.status}: {await r.text()}")
                    
                    data = await r.json()
                    if "error" in data:
                        raise ValueError(data["error"])
                    return data.get("result")
            except Exception as exc:
                last = exc
                logger.warning("SOL API fail: %s attempt=%d err=%s", method, attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))
    
    raise ConnectionError(f"All SOL API attempts exhausted: {last}")


async def verify_solana_tx(txid: str) -> dict:
    """
    Verify Solana transaction.
    Focuses on native SOL transfers or basic token transfers via balance diffs.
    """
    try:
        # Request parsed JSON encoding for easier reading without solders
        tx = await _rpc_call("getTransaction", [
            txid,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
        ])
        
        if not tx:
            return _err("tx_not_found")
            
        meta = tx.get("meta", {})
        if meta.get("err"):
            return _err("tx_failed")
            
        block_time = tx.get("blockTime", 0)
        if not block_time:
            return _err("tx_pending")
            
        # Optional block height check for confirmations
        latest_block = await _rpc_call("getSlot", [{"commitment": "finalized"}])
        tx_slot = tx.get("slot", 0)
        confirmations = max(0, latest_block - tx_slot) if isinstance(latest_block, int) else 0

        deposit = settings.wallet_addresses.get(CHAIN, "")
        if not deposit:
            return _err("chain_not_configured")

        transaction = tx.get("transaction", {})
        message = transaction.get("message", {})
        account_keys = message.get("accountKeys", [])
        
        # Build pubkey array
        pubkeys = []
        for key in account_keys:
            if isinstance(key, dict):
                pubkeys.append(key.get("pubkey", ""))
            else:
                pubkeys.append(key)
                
        if deposit not in pubkeys:
            return _err("wallet_mismatch")
            
        deposit_idx = pubkeys.index(deposit)
        
        # Check SOL balance change
        pre_bals = meta.get("preBalances", [])
        post_bals = meta.get("postBalances", [])
        
        sol_diff = 0
        if deposit_idx < len(pre_bals) and deposit_idx < len(post_bals):
            sol_diff = post_bals[deposit_idx] - pre_bals[deposit_idx]
            
        token = "SOL"
        amount = 0.0
        
        if sol_diff > 0:
            amount = sol_diff / LAMPORTS
        else:
            # Check SPL Token balances (e.g. USDT)
            pre_token = meta.get("preTokenBalances", [])
            post_token = meta.get("postTokenBalances", [])
            
            def get_token_amt(bals, owner_addr):
                for b in bals:
                    if b.get("owner") == owner_addr:
                        amt_str = b.get("uiTokenAmount", {}).get("uiAmountString", "0")
                        mint = b.get("mint", "")
                        return float(amt_str), mint
                return 0.0, ""
                
            pre_amt, pre_mint = get_token_amt(pre_token, deposit)
            post_amt, post_mint = get_token_amt(post_token, deposit)
            
            if post_amt > pre_amt:
                amount = post_amt - pre_amt
                token = "UNKNOWN"
                # Check USDT mint example (mainnet USDT)
                if post_mint == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":
                    token = "USDT"

        if amount <= 0:
            return _err("wallet_mismatch") # Or no value transferred
            
        # Note: sender logic on Solana is tricky, assume fee payer (index 0)
        sender = pubkeys[0] if pubkeys else "unknown"

        for fn, args in [
            (validate_receiver, (deposit, CHAIN)),
            (validate_amount, (amount, "SOL" if token == "SOL" else token)),
            (validate_timestamp, (block_time,)),
            (validate_confirmations, (CHAIN, confirmations)),
        ]:
            ok, code = fn(*args)
            if not ok:
                return _err(code)

        logger.info(
            "SOL verified: tx=%s amt=%.6f token=%s confs=%d",
            txid[:16], amount, token, confirmations,
        )
        return {
            "success": True,
            "error": None,
            "data": {
                "token": token,
                "amount": amount,
                "sender": sender,
                "receiver": deposit,
                "timestamp": block_time,
                "confirmations": confirmations,
                "chain": CHAIN,
            },
        }

    except LookupError as exc:
        return _err(str(exc))
    except ConnectionError:
        return _err("rpc_failure")
    except ValueError as exc:
        if "not found" in str(exc).lower():
            return _err("tx_not_found")
        return _err("tx_failed")
    except Exception as exc:
        logger.exception("Unexpected SOL verification error: %s", exc)
        return _err("internal_error")


def _err(code: str) -> dict:
    return {"success": False, "error": code, "data": None}
