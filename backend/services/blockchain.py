"""
BITVORA EXCHANGE — Unified Blockchain Verification Service
Mirrors the Telegram bot's services/blockchain.py interface.

Single entry point for all chain verification:
  verify_transaction(network, txid, ...) → TxResult

Dispatches to the correct chain verifier based on network.
"""

import logging
from dataclasses import dataclass

from config import settings
from services.tx_verifier.models import VerificationResult

logger = logging.getLogger("bitvora.blockchain")


# Re-export the TxResult-compatible result class
TxResult = VerificationResult


# ─────────────────────────────────────────────────────────────
# Network → Chain family mapping (matches config.settings.chain_families)
# ─────────────────────────────────────────────────────────────

NETWORK_TO_CHAIN = {
    # EVM
    "ERC20": "ethereum",
    "BEP20": "bsc",
    "ETHEREUM": "ethereum",
    "BSC": "bsc",
    # Non-EVM
    "TRC20": "tron",
    "TRON": "tron",
    "SOL": "solana",
    "SOLANA": "solana",
    "BTC": "bitcoin",
    "BITCOIN": "bitcoin",
    "LTC": "litecoin",
    "LITECOIN": "litecoin",
    "TON": "ton",
}


async def verify_transaction(
    network: str,
    txid: str,
    expected_address: str,
    expected_amount: float,
    asset: str,
) -> VerificationResult:
    """
    Unified verification entry point.
    Matches the Telegram bot's interface:
      result = await verify_transaction(network="BEP20", txid="0x...", ...)

    Dispatches to the correct chain-specific verifier.
    """
    network_upper = network.upper()
    chain = NETWORK_TO_CHAIN.get(network_upper, network_upper.lower())

    family = settings.chain_families.get(chain)

    try:
        if family == "evm":
            from services.tx_verifier.chains.evm import verify_transaction as _verify
        elif family == "tron":
            from services.tx_verifier.chains.tron import verify_transaction as _verify
        elif family == "solana":
            from services.tx_verifier.chains.solana import verify_transaction as _verify
        elif family == "bitcoin":
            from services.tx_verifier.chains.bitcoin import verify_transaction as _verify
        elif family == "litecoin":
            from services.tx_verifier.chains.litecoin import verify_transaction as _verify
        elif family == "ton":
            from services.tx_verifier.chains.ton import verify_transaction as _verify
        else:
            return VerificationResult(valid=False, error=f"Unsupported network: {network}")

        return await _verify(
            txid=txid,
            chain=chain,
            expected_address=expected_address,
            expected_amount=expected_amount,
            asset=asset,
        )

    except Exception as e:
        logger.exception("Verification error for network=%s txid=%s", network, txid[:16])
        return VerificationResult(valid=False, error=f"Verification error: {str(e)}")
