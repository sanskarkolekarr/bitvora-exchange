"""
TXID Verification — Entry Point.

Single async function that validates input, routes to the correct chain module,
and returns a unified result. No database. No Redis. No API routes.

Supports: ethereum, bsc, tron, bitcoin.
Extensible for: solana, litecoin, etc.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logger import get_logger
from app.services.verifier.validators import CHAIN_TYPES, validate_chain, validate_txid

logger = get_logger("verifier.main")


async def verify_tx(txid: str, chain: str) -> dict:
    """
    Verify a blockchain transaction by its TXID.

    Args:
        txid:  Transaction hash / ID (format depends on chain).
        chain: Blockchain network name — ethereum | bsc | tron | bitcoin.

    Returns:
        {
            "success": bool,
            "error":   str | None,
            "data": {
                "token":         str,
                "amount":        float,
                "sender":        str,
                "receiver":      str,
                "timestamp":     int,
                "confirmations": int,
                "chain":         str,
            } | None
        }
    """
    # ── 1. Sanitise ─────────────────────────────────────────────
    if not isinstance(txid, str) or not isinstance(chain, str):
        return _err("invalid_txid")

    txid = txid.strip()
    chain = chain.strip().lower()

    # ── 2. Validate chain is supported ──────────────────────────
    ok, code = validate_chain(chain)
    if not ok:
        return _err(code)

    # ── 3. Verify deposit address is configured ─────────────────
    deposit = settings.wallet_addresses.get(chain, "")
    if not deposit:
        logger.error("No deposit address configured for chain=%s", chain)
        return _err("chain_not_configured")

    # ── 4. Validate TXID format ─────────────────────────────────
    ok, code = validate_txid(txid, chain)
    if not ok:
        return _err(code)

    # ── 5. Route to chain-specific verifier ─────────────────────
    chain_type = CHAIN_TYPES[chain]

    try:
        if chain_type == "evm":
            from app.services.verifier.evm import verify_evm_tx
            result = await verify_evm_tx(txid, chain)

        elif chain_type == "tron":
            from app.services.verifier.tron import verify_tron_tx
            result = await verify_tron_tx(txid)

        elif chain_type == "btc":
            from app.services.verifier.btc import verify_btc_tx
            result = await verify_btc_tx(txid)

        elif chain_type == "solana":
            from app.services.verifier.solana import verify_solana_tx
            result = await verify_solana_tx(txid)

        elif chain_type == "ltc":
            from app.services.verifier.ltc import verify_ltc_tx
            result = await verify_ltc_tx(txid)

        else:
            return _err("unsupported_chain")

        # ── Ensure chain field is present in result data ────────
        if result.get("success") and result.get("data"):
            result["data"].setdefault("chain", chain)

        return result

    except Exception as exc:
        logger.exception("Unhandled error in verify_tx: %s", exc)
        return _err("internal_error")


def _err(code: str) -> dict:
    return {"success": False, "error": code, "data": None}
