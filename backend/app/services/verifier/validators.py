"""
Transaction validation utilities.
Validates TXID format, timestamps, confirmations, wallet addresses, and amounts.
No database — pure validation logic. Trusts ONLY blockchain data.

All thresholds and addresses are config-driven via settings.
"""

from __future__ import annotations

import re
import time
from typing import Optional, Tuple

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("verifier.validators")

# ── TXID format patterns ────────────────────────────────────────────────────
_EVM_TXID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# ── Chain → type mapping ────────────────────────────────────────────────────
CHAIN_TYPES: dict[str, str] = {
    "ethereum": "evm",
    "bsc":      "evm",
    "tron":     "tron",
    "bitcoin":  "btc",
    "solana":   "solana",
    "litecoin": "ltc",
}

# ── Confirmation thresholds (min required) ──────────────────────────────────
CONFIRMATION_RANGE: dict[str, Tuple[int, int]] = {
    "ethereum": (3, 12),
    "bsc":      (3, 12),
    "tron":     (1, 20),
    "bitcoin":  (2, 6),
    "litecoin": (2, 6),
    "solana":   (1, 1),
}

# ── Maximum transaction age (seconds) ──────────────────────────────────────
MAX_TX_AGE_SECONDS = 3600  # 1 hour

# ── Minimum amounts per token symbol (anti-dust / anti-spam) ────────────────
# Used as fallback; MIN_DEPOSIT_AMOUNT from config is the primary threshold.
MIN_AMOUNTS: dict[str, float] = {
    "ETH":  0.0005,
    "BNB":  0.002,
    "BTC":  0.00005,
    "TRX":  10.0,
    "USDT": 1.0,
    "USDC": 1.0,
    "DAI":  1.0,
    "BUSD": 1.0,
}


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════


def validate_chain(chain: str) -> Tuple[bool, Optional[str]]:
    """Check if chain is supported."""
    if chain not in CHAIN_TYPES:
        return False, "unsupported_chain"
    return True, None


def validate_txid(txid: str, chain: str) -> Tuple[bool, Optional[str]]:
    """
    Validate TXID format for the given chain.
    - EVM:  0x + 64 hex chars
    - BTC:  64 hex chars (no prefix)
    - TRON: 64 hex chars (no prefix)
    """
    if not txid or not isinstance(txid, str):
        return False, "invalid_txid"

    txid = txid.strip()
    chain_type = CHAIN_TYPES.get(chain)

    if chain_type == "evm":
        if not _EVM_TXID_RE.match(txid):
            return False, "invalid_txid"
    elif chain_type in ("btc", "tron", "ltc"):
        # Allow basic checks or any reasonable length hash for newer chains
        if len(txid) < 30:
             return False, "invalid_txid"
    elif chain_type == "solana":
        if len(txid) < 80:
             return False, "invalid_txid"
    else:
        return False, "unsupported_chain"

    return True, None


def validate_timestamp(
    tx_timestamp: int,
    max_age_seconds: int = MAX_TX_AGE_SECONDS,
) -> Tuple[bool, Optional[str]]:
    """Reject transactions older than max_age_seconds or with future timestamps."""
    now = int(time.time())
    age = now - tx_timestamp

    if age > max_age_seconds:
        logger.warning("TX too old: age=%ds, max=%ds", age, max_age_seconds)
        return False, "too_old"

    # Tolerate up to 5 min clock skew
    if age < -300:
        logger.warning("TX timestamp in future: age=%ds", age)
        return False, "invalid_timestamp"

    return True, None


def validate_confirmations(chain: str, confirmations: int) -> Tuple[bool, Optional[str]]:
    """Check if transaction has sufficient confirmations for its chain."""
    min_conf, _ = CONFIRMATION_RANGE.get(chain, (3, 12))

    if confirmations < min_conf:
        logger.warning(
            "Insufficient confirmations: chain=%s, got=%d, required=%d",
            chain, confirmations, min_conf,
        )
        return False, "insufficient_confirmations"

    return True, None


def validate_receiver(receiver: str, chain: str) -> Tuple[bool, Optional[str]]:
    """Verify receiver matches the configured deposit address for this chain."""
    if not receiver:
        return False, "wallet_mismatch"

    expected = settings.wallet_addresses.get(chain, "")
    if not expected:
        logger.error("No deposit address configured for chain=%s", chain)
        return False, "wallet_mismatch"

    # EVM addresses are case-insensitive (checksummed vs lowercase)
    chain_type = CHAIN_TYPES.get(chain)
    if chain_type == "evm":
        match = receiver.lower() == expected.lower()
    else:
        match = receiver == expected

    if not match:
        logger.warning(
            "Wallet mismatch: chain=%s, got=%s, expected=%s",
            chain, receiver, expected,
        )
        return False, "wallet_mismatch"

    return True, None


def validate_amount(amount: float, token: str) -> Tuple[bool, Optional[str]]:
    """Reject dust / spam and over-the-limit transactions."""
    if amount <= 0:
        return False, "invalid_amount"

    # ── Check Minimum ──
    # Use config-driven minimum first, then token-specific fallback
    min_amount = MIN_AMOUNTS.get(token.upper(), settings.MIN_DEPOSIT_AMOUNT)

    if min_amount and amount < min_amount:
        logger.warning(
            "Dust transaction: token=%s, amount=%f, min=%f",
            token, amount, min_amount,
        )
        return False, "dust_transaction"

    # ── Check Maximum ──
    max_amount = settings.MAX_DEPOSIT_AMOUNT
    if max_amount and amount > max_amount:
        logger.warning(
            "Over-limit transaction: token=%s, amount=%f, max=%f",
            token, amount, max_amount,
        )
        return False, "over_limit"

    return True, None


def validate_token_contract(
    contract: str,
    chain: str,
    expected_token: str | None = None,
) -> Tuple[bool, Optional[str]]:
    """
    Validate that a token contract address is recognized for the given chain.
    Uses settings.token_contracts which is built from env vars.

    Args:
        contract: The contract address from the blockchain.
        chain: The blockchain (ethereum, bsc, tron).
        expected_token: If provided, also checks the contract matches this token symbol.

    Returns:
        (True, None) if valid, (False, error_code) if not.
    """
    contracts = settings.token_contracts.get(chain, {})
    if not contracts:
        logger.warning("No token contracts configured for chain=%s", chain)
        return False, "token_mismatch"

    # Normalize: lowercase for EVM chains
    if chain in ("ethereum", "bsc"):
        contract = contract.lower()

    token_info = contracts.get(contract)
    if token_info is None:
        logger.warning(
            "Unknown token contract: chain=%s contract=%s",
            chain, contract,
        )
        return False, "token_mismatch"

    if expected_token and token_info["symbol"].upper() != expected_token.upper():
        logger.warning(
            "Token symbol mismatch: expected=%s got=%s",
            expected_token, token_info["symbol"],
        )
        return False, "token_mismatch"

    return True, None
