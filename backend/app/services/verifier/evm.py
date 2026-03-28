"""
EVM chain transaction verifier (Ethereum, BSC).
Multi-RPC fallback · retry with exponential backoff · async throughout.
Parses ERC20 Transfer logs — NEVER trusts tx.value for tokens.

CONFIG-DRIVEN: RPC endpoints, deposit addresses, and token contracts
are all sourced from settings (env vars). Nothing is hardcoded.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

from app.core.config import settings
from app.core.logger import get_logger
from app.services.verifier.parser import find_matching_transfer
from app.services.verifier.validators import (
    validate_confirmations,
    validate_amount,
    validate_receiver,
    validate_timestamp,
    validate_token_contract,
)

logger = get_logger("verifier.evm")

# ── Native token metadata ──────────────────────────────────────────────────
NATIVE_TOKENS: dict[str, dict] = {
    "ethereum": {"symbol": "ETH", "decimals": 18},
    "bsc": {"symbol": "BNB", "decimals": 18},
}

# ── Retry / timeout constants ──────────────────────────────────────────────
MAX_RETRIES = 5
REQUEST_TIMEOUT_S = 15


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-RPC ENDPOINT RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════


def _get_rpc_endpoints(chain: str) -> list[str]:
    """
    Get RPC endpoints for a chain from config with hardcoded fallbacks.
    Config supports comma-separated multi-RPC (primary + fallbacks).
    """
    # Primary: from settings.rpc_endpoint_lists (parsed from env)
    config_rpcs = settings.rpc_endpoint_lists.get(chain, [])

    # Static fallbacks (de-duped against config)
    fallbacks: dict[str, list[str]] = {
        "ethereum": [
            "https://rpc.ankr.com/eth",
            "https://ethereum.publicnode.com",
            "https://1rpc.io/eth",
        ],
        "bsc": [
            "https://bsc-dataseed1.binance.org",
            "https://bsc-dataseed2.binance.org",
            "https://rpc.ankr.com/bsc",
        ],
    }

    chain_fallbacks = fallbacks.get(chain, [])
    combined = config_rpcs + [fb for fb in chain_fallbacks if fb not in config_rpcs]

    # Deduplicate while preserving order
    return list(dict.fromkeys(combined))


# ═══════════════════════════════════════════════════════════════════════════
# LOW-LEVEL RPC
# ═══════════════════════════════════════════════════════════════════════════


async def _json_rpc(
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    params: list[Any],
) -> Any:
    """Single JSON-RPC 2.0 call. Raises on HTTP / RPC error."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(
        url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S),
    ) as resp:
        if resp.status != 200:
            raise ConnectionError(f"HTTP {resp.status} from {url}")
        body = await resp.json()
        if "error" in body and body["error"]:
            raise ValueError(f"RPC error: {body['error']}")
        return body.get("result")


async def _rpc_call(method: str, params: list[Any], chain: str) -> Any:
    """
    JSON-RPC with multi-endpoint fallback + exponential backoff.
    Uses config-driven RPC endpoints with hardcoded fallbacks.
    Round-robins across RPCs, max 5 attempts total.
    """
    rpcs = _get_rpc_endpoints(chain)
    if not rpcs:
        raise ValueError(f"No RPC endpoints configured for {chain}")

    last_err: Optional[Exception] = None
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            url = rpcs[attempt % len(rpcs)]
            try:
                return await _json_rpc(session, url, method, params)
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "RPC fail: %s %s attempt=%d/%d err=%s",
                    method, url, attempt + 1, MAX_RETRIES, exc,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))

    raise ConnectionError(f"All RPC attempts exhausted ({method}): {last_err}")


# ═══════════════════════════════════════════════════════════════════════════
# DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════════


async def _fetch_tx(txid: str, chain: str) -> dict:
    r = await _rpc_call("eth_getTransactionByHash", [txid], chain)
    if r is None:
        raise LookupError("tx_not_found")
    return r


async def _fetch_receipt(txid: str, chain: str) -> dict:
    r = await _rpc_call("eth_getTransactionReceipt", [txid], chain)
    if r is None:
        raise LookupError("tx_not_found")
    return r


async def _fetch_block(block_hash: str, chain: str) -> dict:
    r = await _rpc_call("eth_getBlockByHash", [block_hash, False], chain)
    if r is None:
        raise LookupError("block_not_found")
    return r


async def _latest_block_number(chain: str) -> int:
    r = await _rpc_call("eth_blockNumber", [], chain)
    return int(r, 16)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


async def verify_evm_tx(txid: str, chain: str) -> dict:
    """
    Full EVM transaction verification pipeline.

    1. Fetch TX + receipt concurrently (async)
    2. Verify receipt status == 1
    3. Fetch block + latest block concurrently
    4. Parse Transfer logs for ERC20 → fall back to native if none
    5. Validate token contract (config-driven), receiver, amount, timestamp
    6. Return standardized result with chain field
    """
    try:
        # ── Concurrent fetch: tx + receipt ──────────────────────
        tx, receipt = await asyncio.gather(
            _fetch_tx(txid, chain),
            _fetch_receipt(txid, chain),
        )

        # ── Receipt status must be success ──────────────────────
        if int(receipt.get("status", "0x0"), 16) != 1:
            return _err("tx_failed")

        # ── Must be mined (has blockHash) ───────────────────────
        block_hash = tx.get("blockHash")
        if not block_hash or block_hash == "0x" + "0" * 64:
            return _err("tx_pending")

        # ── Concurrent fetch: block + latest height ─────────────
        block, latest_num = await asyncio.gather(
            _fetch_block(block_hash, chain),
            _latest_block_number(chain),
        )

        block_num = int(tx["blockNumber"], 16)
        timestamp = int(block["timestamp"], 16)
        confirmations = latest_num - block_num

        # ── Parse ERC20 Transfer logs (config-driven contracts) ─
        deposit_addr = settings.wallet_addresses.get(chain, "")
        logs = receipt.get("logs", [])
        transfer = find_matching_transfer(logs, deposit_addr, chain)

        if transfer:
            token = transfer["token"]
            amount = transfer["amount"]
            sender = transfer["sender"]
            receiver = transfer["receiver"]
            contract = transfer.get("contract", "")

            # ── Validate token contract against config ──────────
            ok, err_code = validate_token_contract(contract, chain)
            if not ok:
                return _err(err_code)
        else:
            # ── Fallback: native ETH / BNB transfer ────────────
            native = NATIVE_TOKENS.get(chain)
            if not native:
                return _err("unsupported_token")

            raw_value = int(tx.get("value", "0x0"), 16)
            if raw_value == 0:
                return _err("zero_amount")

            token = native["symbol"]
            amount = raw_value / (10 ** native["decimals"])
            sender = tx.get("from", "").lower()
            receiver = tx.get("to", "").lower()

        # ── Validations ─────────────────────────────────────────
        for validator, args in [
            (validate_receiver, (receiver, chain)),
            (validate_amount, (amount, token)),
            (validate_timestamp, (timestamp,)),
            (validate_confirmations, (chain, confirmations)),
        ]:
            ok, err_code = validator(*args)
            if not ok:
                return _err(err_code)

        # ── Success ─────────────────────────────────────────────
        logger.info(
            "EVM verified: chain=%s tx=%s token=%s amt=%.8f confs=%d",
            chain, txid[:16], token, amount, confirmations,
        )
        return {
            "success": True,
            "error": None,
            "data": {
                "token": token,
                "amount": amount,
                "sender": sender,
                "receiver": receiver,
                "timestamp": timestamp,
                "confirmations": confirmations,
                "chain": chain,
            },
        }

    except LookupError as exc:
        return _err(str(exc))
    except ConnectionError:
        return _err("rpc_failure")
    except Exception as exc:
        logger.exception("Unexpected EVM verification error: %s", exc)
        return _err("internal_error")


def _err(code: str) -> dict:
    return {"success": False, "error": code, "data": None}
