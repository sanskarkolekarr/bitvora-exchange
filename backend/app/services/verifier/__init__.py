"""
TXID Verification Module.
Production-grade, fully async, multi-chain transaction verifier.
No database. No Redis. No API routes. Pure verification logic.
"""

from app.services.verifier.main import verify_tx


async def quick_verify(txid: str, chain: str) -> dict | None:
    """
    Quick single-shot verification for use in the API endpoint.
    Returns the raw result dict or None on any failure.
    """
    try:
        result = await verify_tx(txid, chain)
        if isinstance(result, dict) and result.get("success"):
            return result.get("data")
        return None
    except Exception:
        return None


__all__ = ["verify_tx", "quick_verify"]
