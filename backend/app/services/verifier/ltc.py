"""
Litecoin transaction verifier.
Uses litecoinspace REST API (mempool.space clone for LTC). Fully async.

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

logger = get_logger("verifier.ltc")

CHAIN = "litecoin"
MAX_RETRIES = 5
TIMEOUT_S = 15
LITOSHI = 100_000_000  # 1 LTC = 100 000 000 litoshis

# ═══════════════════════════════════════════════════════════════════════════
# MULTI-RPC ENDPOINT RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════

def _get_ltc_endpoints() -> list[str]:
    """Get LTC API endpoints."""
    config_rpcs = settings.rpc_endpoint_lists.get(CHAIN, [])
    fallbacks = [
        "https://litecoinspace.org/api",
    ]
    combined = config_rpcs + [fb for fb in fallbacks if fb not in config_rpcs]
    return list(dict.fromkeys(combined))

# ═══════════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ═══════════════════════════════════════════════════════════════════════════

async def _get(session: aiohttp.ClientSession, base: str, path: str) -> Any:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)) as r:
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
    """GET with multi-endpoint fallback + retry."""
    endpoints = _get_ltc_endpoints()
    last: Optional[Exception] = None
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            base = endpoints[attempt % len(endpoints)]
            try:
                return await _get(session, base, path)
            except LookupError:
                raise
            except Exception as exc:
                last = exc
                logger.warning("LTC API fail: %s attempt=%d err=%s", path, attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))
    raise ConnectionError(f"All LTC API attempts exhausted: {last}")

# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

async def verify_ltc_tx(txid: str) -> dict:
    """Verify Litecoin transaction via litecoinspace API."""
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

        amount = match["value"] / LITOSHI
        receiver = match["scriptpubkey_address"]

        # Sender
        vin = tx.get("vin", [])
        sender = (
            vin[0].get("prevout", {}).get("scriptpubkey_address", "unknown")
            if vin else "unknown"
        )

        for fn, args in [
            (validate_receiver, (receiver, CHAIN)),
            (validate_amount, (amount, "LTC")),
            (validate_timestamp, (timestamp,)),
            (validate_confirmations, (CHAIN, confirmations)),
        ]:
            ok, code = fn(*args)
            if not ok:
                return _err(code)

        logger.info(
            "LTC verified: tx=%s amt=%.8f confs=%d",
            txid[:16], amount, confirmations,
        )
        return {
            "success": True,
            "error": None,
            "data": {
                "token": "LTC",
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
        logger.exception("Unexpected LTC verification error: %s", exc)
        return _err("internal_error")

def _err(code: str) -> dict:
    return {"success": False, "error": code, "data": None}
