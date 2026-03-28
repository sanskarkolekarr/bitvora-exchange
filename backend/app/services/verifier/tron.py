"""
TRON blockchain transaction verifier.
Uses TronGrid REST API. Supports TRC20 tokens and native TRX transfers.
Multi-endpoint fallback · retry · fully async.

CONFIG-DRIVEN: Token contracts, deposit addresses, and RPC endpoints
are all sourced from settings (env vars). Nothing is hardcoded.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Optional

import aiohttp

from app.core.config import settings
from app.core.logger import get_logger
from app.services.verifier.validators import (
    validate_confirmations,
    validate_amount,
    validate_receiver,
    validate_timestamp,
    validate_token_contract,
)

logger = get_logger("verifier.tron")

CHAIN = "tron"
MAX_RETRIES = 5
TIMEOUT_S = 15


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-RPC ENDPOINT RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════


def _get_tron_endpoints() -> list[str]:
    """
    Get TRON API endpoints from config with hardcoded fallback.
    Config supports comma-separated multi-RPC.
    """
    config_rpcs = settings.rpc_endpoint_lists.get(CHAIN, [])

    fallbacks = [
        "https://api.trongrid.io",
    ]

    combined = config_rpcs + [fb for fb in fallbacks if fb not in config_rpcs]
    return list(dict.fromkeys(combined))


def _get_trc20_registry() -> dict[str, dict]:
    """
    Get TRC20 token registry from config.
    Returns {contract_address: {symbol, decimals}}.
    """
    return settings.token_contracts.get(CHAIN, {})


_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# ═══════════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ═══════════════════════════════════════════════════════════════════════════


async def _api(
    session: aiohttp.ClientSession,
    base: str,
    path: str,
    payload: Optional[dict] = None,
    method: str = "POST",
) -> dict:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    kw: dict[str, Any] = {
        "timeout": aiohttp.ClientTimeout(total=TIMEOUT_S),
        "headers": {"Content-Type": "application/json"},
    }
    if method == "POST":
        async with session.post(url, json=payload or {}, **kw) as r:
            if r.status != 200:
                raise ConnectionError(f"HTTP {r.status}")
            return await r.json()
    else:
        async with session.get(url, **kw) as r:
            if r.status != 200:
                raise ConnectionError(f"HTTP {r.status}")
            return await r.json()


async def _call(path: str, payload: Optional[dict] = None, method: str = "POST") -> dict:
    """TronGrid call with multi-endpoint fallback + retry (config-driven)."""
    endpoints = _get_tron_endpoints()
    last: Optional[Exception] = None
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            base = endpoints[attempt % len(endpoints)]
            try:
                return await _api(session, base, path, payload, method)
            except Exception as exc:
                last = exc
                logger.warning("TronGrid fail: %s attempt=%d err=%s", path, attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))
    raise ConnectionError(f"All TronGrid attempts exhausted: {last}")


# ═══════════════════════════════════════════════════════════════════════════
# ADDRESS HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _hex_to_base58(hex_addr: str) -> str:
    """Convert TRON hex address (41…) to base58check."""
    try:
        if hex_addr.startswith("0x"):
            hex_addr = hex_addr[2:]
        raw = bytes.fromhex(hex_addr)
        cs = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
        data = raw + cs

        leading = sum(1 for b in data if b == 0)
        n = int.from_bytes(data, "big")
        chars: list[str] = []
        while n:
            n, r = divmod(n, 58)
            chars.append(_B58_ALPHABET[r])
        return _B58_ALPHABET[0] * leading + "".join(reversed(chars))
    except Exception:
        return hex_addr


# ═══════════════════════════════════════════════════════════════════════════
# PARSERS
# ═══════════════════════════════════════════════════════════════════════════


def _parse_trc20_events(events: list[dict], deposit: str) -> Optional[dict]:
    """
    Find the TRC20 Transfer event that pays our deposit address.
    Uses CONFIG-DRIVEN token registry from settings.token_contracts.
    """
    trc20_tokens = _get_trc20_registry()

    for ev in events:
        if ev.get("event_name") != "Transfer":
            continue

        contract = ev.get("contract_address", "")
        info = trc20_tokens.get(contract)
        if info is None:
            logger.debug("Skipping unknown TRC20 contract: %s", contract)
            continue

        res = ev.get("result", {})
        to_addr = res.get("to", "")
        from_addr = res.get("from", "")
        raw_val = res.get("value", "0")

        if to_addr == deposit or to_addr.lower() == deposit.lower():
            return {
                "token": info["symbol"],
                "amount": int(raw_val) / (10 ** info["decimals"]),
                "sender": from_addr,
                "receiver": to_addr,
                "contract": contract,
            }
    return None


def _parse_trx_transfer(contracts: list[dict], deposit: str) -> Optional[dict]:
    """Parse native TRX transfer from raw_data.contract."""
    for c in contracts:
        if c.get("type") != "TransferContract":
            continue
        val = c.get("parameter", {}).get("value", {})
        to_b58 = _hex_to_base58(val.get("to_address", ""))
        from_b58 = _hex_to_base58(val.get("owner_address", ""))
        raw_amount = val.get("amount", 0)
        if to_b58 == deposit:
            return {
                "amount": raw_amount / 1_000_000,
                "sender": from_b58,
                "receiver": to_b58,
            }
    return None


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


async def verify_tron_tx(txid: str) -> dict:
    """
    Full TRON verification pipeline.
    1. Fetch tx info + tx data
    2. Verify contractRet == SUCCESS
    3. Fetch latest block for confirmations
    4. Parse TRC20 events → fallback to native TRX
    5. Validate token contract (config-driven), receiver, amount, timestamp
    6. Return standardized result with chain field
    """
    try:
        # ── Concurrent: tx_info + tx_data ──────────────────────
        tx_info, tx_data = await asyncio.gather(
            _call("wallet/gettransactioninfobyid", {"value": txid}),
            _call("wallet/gettransactionbyid", {"value": txid}),
        )

        if not tx_info or "id" not in tx_info:
            return _err("tx_not_found")
        if not tx_data or "txID" not in tx_data:
            return _err("tx_not_found")

        # ── Must be SUCCESS ────────────────────────────────────
        ret = tx_data.get("ret", [{}])
        if not ret or ret[0].get("contractRet") != "SUCCESS":
            return _err("tx_failed")

        # ── Block info ─────────────────────────────────────────
        block_num = tx_info.get("blockNumber", 0)
        timestamp = tx_info.get("blockTimeStamp", 0) // 1000  # ms→s
        if timestamp == 0:
            return _err("tx_pending")

        # ── Latest block for confirmations ─────────────────────
        now_block = await _call("wallet/getnowblock", {})
        latest_num = (
            now_block.get("block_header", {})
            .get("raw_data", {})
            .get("number", 0)
        )
        confirmations = max(0, latest_num - block_num)

        # ── Parse transfer ─────────────────────────────────────
        deposit = settings.wallet_addresses.get(CHAIN, "")

        events_resp = await _call(f"v1/transactions/{txid}/events", method="GET")
        transfer = _parse_trc20_events(events_resp.get("data", []), deposit)

        if transfer:
            token, amount = transfer["token"], transfer["amount"]
            sender, receiver = transfer["sender"], transfer["receiver"]
            contract = transfer.get("contract", "")

            # ── Validate token contract against config ──────────
            ok, err_code = validate_token_contract(contract, CHAIN)
            if not ok:
                return _err(err_code)
        else:
            contracts = tx_data.get("raw_data", {}).get("contract", [])
            native = _parse_trx_transfer(contracts, deposit)
            if native is None:
                return _err("wallet_mismatch")
            token, amount = "TRX", native["amount"]
            sender, receiver = native["sender"], native["receiver"]

        # ── Validations ────────────────────────────────────────
        for fn, args in [
            (validate_receiver, (receiver, CHAIN)),
            (validate_min_amount, (amount, token)),
            (validate_timestamp, (timestamp,)),
            (validate_confirmations, (CHAIN, confirmations)),
        ]:
            ok, code = fn(*args)
            if not ok:
                return _err(code)

        logger.info(
            "TRON verified: tx=%s token=%s amt=%.6f confs=%d",
            txid[:16], token, amount, confirmations,
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
                "chain": CHAIN,
            },
        }

    except LookupError as exc:
        return _err(str(exc))
    except ConnectionError:
        return _err("rpc_failure")
    except Exception as exc:
        logger.exception("Unexpected TRON verification error: %s", exc)
        return _err("internal_error")


def _err(code: str) -> dict:
    return {"success": False, "error": code, "data": None}
