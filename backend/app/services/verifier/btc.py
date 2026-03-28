"""
Bitcoin transaction verifier.
Uses Blockstream / Mempool REST API. Fully async with multi-endpoint fallback.

CONFIG-DRIVEN: RPC endpoints and deposit addresses from settings (env vars).
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

logger = get_logger("verifier.btc")

CHAIN = "bitcoin"
MAX_RETRIES = 5
TIMEOUT_S = 15
SAT = 100_000_000  # 1 BTC = 100 000 000 satoshis


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-RPC ENDPOINT RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════


def _get_btc_endpoints() -> list[str]:
    """
    Get BTC API endpoints from config with hardcoded fallbacks.
    Config supports comma-separated multi-RPC.
    """
    config_rpcs = settings.rpc_endpoint_lists.get(CHAIN, [])

    fallbacks = [
        "https://blockstream.info/api",
        "https://mempool.space/api",
    ]

    combined = config_rpcs + [fb for fb in fallbacks if fb not in config_rpcs]
    return list(dict.fromkeys(combined))


# ═══════════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ═══════════════════════════════════════════════════════════════════════════


async def _get(
    session: aiohttp.ClientSession,
    base: str,
    path: str,
) -> Any:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    async with session.get(
        url, timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
    ) as r:
        if r.status == 404:
            raise LookupError("tx_not_found")
        if r.status != 200:
            raise ConnectionError(f"HTTP {r.status}")
        ct = r.content_type or ""
        if "json" in ct:
            return await r.json()
        text = await r.text()
        try:
            return int(text.strip())
        except ValueError:
            return text.strip()


async def _call(path: str) -> Any:
    """GET with multi-endpoint fallback + retry (config-driven). Re-raises LookupError immediately."""
    endpoints = _get_btc_endpoints()
    last: Optional[Exception] = None
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            base = endpoints[attempt % len(endpoints)]
            try:
                return await _get(session, base, path)
            except LookupError:
                raise  # 404 = tx genuinely missing, no retry
            except Exception as exc:
                last = exc
                logger.warning("BTC API fail: %s attempt=%d err=%s", path, attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))
    raise ConnectionError(f"All BTC API attempts exhausted: {last}")


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


async def verify_btc_tx(txid: str) -> dict:
    """
    Full Bitcoin verification pipeline.
    1. Fetch TX from Blockstream/Mempool API
    2. Confirm it's mined
    3. Fetch latest block height for confirmation count
    4. Find matching vout to deposit address
    5. Validate receiver, amount, timestamp, confirmations
    6. Return standardized result with chain field
    """
    try:
        tx = await _call(f"tx/{txid}")
        if not isinstance(tx, dict):
            return _err("tx_not_found")

        status = tx.get("status", {})
        if not status.get("confirmed", False):
            return _err("tx_pending")

        block_height = status.get("block_height", 0)
        timestamp = status.get("block_time", 0)
        if not timestamp:
            return _err("tx_pending")

        # ── Latest block height ────────────────────────────────
        tip = await _call("blocks/tip/height")
        latest = int(tip) if not isinstance(tip, int) else tip
        confirmations = max(0, latest - block_height + 1)

        # ── Find matching output ───────────────────────────────
        deposit = settings.wallet_addresses.get(CHAIN, "")
        vouts = tx.get("vout", [])
        match = None
        for out in vouts:
            if out.get("scriptpubkey_address", "") == deposit:
                match = out
                break

        if match is None:
            return _err("wallet_mismatch")

        amount = match["value"] / SAT
        receiver = match["scriptpubkey_address"]

        # Sender = first input's previous output address
        vin = tx.get("vin", [])
        sender = (
            vin[0].get("prevout", {}).get("scriptpubkey_address", "unknown")
            if vin else "unknown"
        )

        # ── Validations ────────────────────────────────────────
        for fn, args in [
            (validate_receiver, (receiver, CHAIN)),
            (validate_amount, (amount, "BTC")),
            (validate_timestamp, (timestamp,)),
            (validate_confirmations, (CHAIN, confirmations)),
        ]:
            ok, code = fn(*args)
            if not ok:
                return _err(code)

        logger.info(
            "BTC verified: tx=%s amt=%.8f confs=%d",
            txid[:16], amount, confirmations,
        )
        return {
            "success": True,
            "error": None,
            "data": {
                "token": "BTC",
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
        logger.exception("Unexpected BTC verification error: %s", exc)
        return _err("internal_error")


def _err(code: str) -> dict:
    return {"success": False, "error": code, "data": None}
