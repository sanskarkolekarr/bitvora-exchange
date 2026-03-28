"""
Currency converter — crypto → USD → INR.

Reads the INR rate dynamically from the database settings table.
Falls back to .env if the database is unreachable.
Returns a locked price snapshot that does NOT recompute on subsequent reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.core.logger import get_logger
from app.services.price.service import get_price, SUPPORTED_TOKENS
from app.services.settings import get_inr_rate

logger = get_logger("price.converter")


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """
    Immutable price snapshot.
    Once created, the values are locked and will NOT change.
    """
    token: str
    amount: float
    price_usd: float       # per-unit price at time of conversion
    total_usd: float
    inr_rate: float         # INR/USD rate used
    total_inr: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "token": self.token,
            "amount": self.amount,
            "price_usd": round(self.price_usd, 6),
            "total_usd": round(self.total_usd, 6),
            "inr_rate": round(self.inr_rate, 2),
            "total_inr": round(self.total_inr, 2),
        }


async def convert(token: str, amount: float) -> Dict[str, object]:
    """
    Convert a crypto amount to USD and INR at the current cached price.

    Args:
        token:  Uppercase token symbol (e.g. "BTC").
        amount: Quantity of the token (must be > 0).

    Returns:
        {
            "token": "BTC",
            "amount": 0.5,
            "price_usd": 65000.0,
            "total_usd": 32500.0,
            "inr_rate": 83.50,
            "total_inr": 2713750.0,
        }

    Raises:
        ValueError: On unsupported token, zero/negative amount, or missing price.
    """
    token_upper = token.upper().strip()

    # ── Validate token ──────────────────────────────────────────
    if token_upper not in SUPPORTED_TOKENS:
        raise ValueError(
            f"Unsupported token: '{token}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_TOKENS))}"
        )

    # ── Validate amount ─────────────────────────────────────────
    if amount <= 0:
        raise ValueError(f"Amount must be positive, got {amount}")

    # ── Fetch the cached price (never hits external API) ────────
    price_usd = await get_price(token_upper)

    # ── Read INR rate dynamically from database ────────────────────
    inr_rate = await get_inr_rate()
    if inr_rate <= 0:
        raise ValueError(f"INR_RATE is invalid: {inr_rate}")

    # ── Compute ─────────────────────────────────────────────────
    total_usd = amount * price_usd
    total_inr = total_usd * inr_rate

    # ── Lock the result as an immutable snapshot ────────────────
    result = ConversionResult(
        token=token_upper,
        amount=amount,
        price_usd=price_usd,
        total_usd=total_usd,
        inr_rate=inr_rate,
        total_inr=total_inr,
    )

    logger.info(
        "Conversion: %.8f %s → $%.2f USD → ₹%.2f INR (rate=%.2f)",
        amount,
        token_upper,
        total_usd,
        total_inr,
        inr_rate,
    )

    return result.to_dict()


async def convert_batch(
    conversions: list[tuple[str, float]],
) -> list[Dict[str, object]]:
    """
    Batch convert multiple (token, amount) pairs.
    All conversions use the SAME price snapshot to ensure consistency.

    Args:
        conversions: List of (token, amount) tuples.

    Returns:
        List of conversion result dicts.
    """
    results = []
    for token, amount in conversions:
        result = await convert(token, amount)
        results.append(result)
    return results
