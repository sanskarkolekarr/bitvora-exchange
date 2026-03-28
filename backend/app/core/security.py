"""
Security primitives: TXID validation, rate limiting, and duplicate detection.

These are infrastructure helpers — no business/blockchain logic lives here.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("core.security")


# ═══════════════════════════════════════════════════════════════
# 1. TXID FORMAT VALIDATION
# ═══════════════════════════════════════════════════════════════

# Chain-specific TXID regex patterns
_TXID_PATTERNS: dict[str, re.Pattern] = {
    # EVM chains (Ethereum, BSC) — 66-char hex with 0x prefix
    "ethereum": re.compile(r"^0x[a-fA-F0-9]{64}$"),
    "bsc":      re.compile(r"^0x[a-fA-F0-9]{64}$"),

    # Tron — 64-char hex (no prefix)
    "tron": re.compile(r"^[a-fA-F0-9]{64}$"),

    # Solana — base58, 87-88 chars
    "solana": re.compile(r"^[1-9A-HJ-NP-Za-km-z]{87,88}$"),

    # Bitcoin — 64-char hex
    "bitcoin": re.compile(r"^[a-fA-F0-9]{64}$"),

    # Litecoin — 64-char hex
    "litecoin": re.compile(r"^[a-fA-F0-9]{64}$"),
}


def validate_txid_format(txid: str, chain: str) -> bool:
    """
    Validates that a TXID matches the expected format for the given chain.

    Args:
        txid:  Transaction hash/ID string.
        chain: Blockchain name (lowercase).

    Returns:
        True if format is valid.

    Raises:
        ValueError: If chain is unsupported or TXID format is invalid.
    """
    chain_lower = chain.lower()

    if chain_lower not in settings.chains_list:
        raise ValueError(f"Unsupported chain: {chain}")

    pattern = _TXID_PATTERNS.get(chain_lower)
    if pattern is None:
        # Allow unknown-but-supported chains to pass with a generic check
        if len(txid) < 20 or len(txid) > 128:
            raise ValueError(f"TXID length out of range for chain {chain}")
        return True

    if not pattern.match(txid):
        raise ValueError(
            f"Invalid TXID format for {chain}: {txid[:16]}..."
        )

    return True


# ═══════════════════════════════════════════════════════════════
# 2. IN-MEMORY RATE LIMITER (IP-BASED)
# ═══════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Sliding-window in-memory rate limiter.

    For production at scale, replace with Redis-based counting (e.g. INCR + EXPIRE).
    This placeholder is safe for single-process deployments.
    """

    def __init__(self, max_requests: int = 0, window_seconds: int = 60):
        self._max = max_requests or settings.RATE_LIMIT_PER_MINUTE
        self._window = window_seconds
        # ip -> list of timestamps
        self._store: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, ip: str) -> bool:
        """
        Check if the given IP has exceeded the rate limit.

        Returns True if limited (request should be rejected).
        """
        now = time.monotonic()
        cutoff = now - self._window

        # Prune old entries
        timestamps = self._store[ip]
        self._store[ip] = [t for t in timestamps if t > cutoff]

        if len(self._store[ip]) >= self._max:
            logger.warning("Rate limit exceeded for IP %s", ip)
            return True

        self._store[ip].append(now)
        return False

    def reset(self, ip: Optional[str] = None) -> None:
        """Clear rate limit state for an IP or all IPs."""
        if ip:
            self._store.pop(ip, None)
        else:
            self._store.clear()


# Global rate limiter instance
rate_limiter = RateLimiter()


# ═══════════════════════════════════════════════════════════════
# 3. DUPLICATE TXID CHECK (DB-BASED)
# ═══════════════════════════════════════════════════════════════

async def check_duplicate_txid(txid: str, db: AsyncSession) -> bool:
    """
    Check whether a TXID already exists in the database.

    Args:
        txid: Transaction hash to look up.
        db:   Async SQLAlchemy session.

    Returns:
        True if the TXID already exists (duplicate).
    """
    # Import here to avoid circular dependency at module level
    from app.models.transaction import Transaction

    stmt = select(Transaction.id).where(Transaction.txid == txid).limit(1)
    result = await db.execute(stmt)
    exists = result.scalar_one_or_none() is not None

    if exists:
        logger.warning("Duplicate TXID detected: %s", txid[:16])

    return exists
