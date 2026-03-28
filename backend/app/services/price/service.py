"""
Price cache service — the heart of the price engine.

Maintains an in-memory cache refreshed every 60 seconds by a background
asyncio task. All consumer code reads from the cache; the external API
is NEVER hit per-request.

Public API:
    get_price(token)       → float
    get_all_prices()       → dict snapshot
    start_price_updater()  → launch background refresh loop
    stop_price_updater()   → cancel the loop cleanly
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

from app.core.logger import get_logger
from app.services.price.providers import close_provider_session, fetch_prices

logger = get_logger("price.service")

# ── Constants ───────────────────────────────────────────────────
_REFRESH_INTERVAL: int = 60          # seconds between cache refreshes
_STALE_THRESHOLD: int = 300          # 5 min — warn if cache older than this
_INITIAL_RETRY_DELAY: float = 5.0    # first retry on startup failure
_MAX_RETRY_DELAY: float = 60.0       # cap exponential backoff

# ── Supported token whitelist ───────────────────────────────────
SUPPORTED_TOKENS: frozenset[str] = frozenset({"BTC", "ETH", "BNB", "USDT", "USDC"})

# ── Global in-memory cache ──────────────────────────────────────
_PRICE_CACHE: Dict[str, float] = {}
_last_updated: float = 0.0           # epoch timestamp of last successful refresh
_cache_lock: asyncio.Lock = asyncio.Lock()  # guards writes; reads are atomic on dicts

# ── Background task handle ──────────────────────────────────────
_updater_task: Optional[asyncio.Task] = None


# ── Cache internals ─────────────────────────────────────────────

async def _refresh_cache() -> bool:
    """
    Fetch fresh prices and merge into the cache.

    Merge strategy:
        • New prices overwrite old ones.
        • Tokens NOT in the fresh payload retain their cached value
          (fail-safe: never drop a price just because one fetch missed it).

    Returns True if at least one price was updated.
    """
    global _last_updated

    fresh = await fetch_prices()
    if not fresh:
        logger.warning("Price refresh returned empty — keeping stale cache")
        return False

    async with _cache_lock:
        updated_count = 0
        for token in SUPPORTED_TOKENS:
            new_price = fresh.get(token)
            if new_price is not None and new_price > 0:
                old = _PRICE_CACHE.get(token)
                _PRICE_CACHE[token] = new_price
                if old != new_price:
                    updated_count += 1

        _last_updated = time.monotonic()

    logger.info(
        "Price cache refreshed — %d tokens updated, cache size %d",
        updated_count,
        len(_PRICE_CACHE),
    )
    return True


async def _ensure_cache_warm() -> None:
    """
    Called on first read if the cache is empty.
    Blocks until at least one successful fetch completes.
    Uses exponential backoff to avoid hammering a down API.
    """
    if _PRICE_CACHE:
        return

    delay = _INITIAL_RETRY_DELAY
    while not _PRICE_CACHE:
        logger.info("Cache cold — fetching prices immediately")
        success = await _refresh_cache()
        if success:
            return
        logger.warning(
            "Initial price fetch failed — retrying in %.1fs", delay
        )
        await asyncio.sleep(delay)
        delay = min(delay * 2, _MAX_RETRY_DELAY)


# ── Background updater ─────────────────────────────────────────

async def _updater_loop() -> None:
    """
    Infinite loop that refreshes the cache every _REFRESH_INTERVAL seconds.
    Handles errors gracefully — never crashes the task.
    """
    # Warm the cache on first run
    await _ensure_cache_warm()

    while True:
        await asyncio.sleep(_REFRESH_INTERVAL)

        try:
            await _refresh_cache()
        except Exception as exc:
            # Defensive: no exception should escape fetch_prices,
            # but guard against truly unexpected failures.
            logger.error(
                "Unexpected error in price updater: %s", exc, exc_info=True
            )

        # Staleness warning
        age = time.monotonic() - _last_updated
        if age > _STALE_THRESHOLD:
            logger.warning(
                "Price cache is %.0fs stale (threshold %ds)",
                age,
                _STALE_THRESHOLD,
            )


async def start_price_updater() -> None:
    """
    Launch the background price refresh task.
    Safe to call multiple times — will not create duplicate tasks.
    """
    global _updater_task

    if _updater_task is not None and not _updater_task.done():
        logger.debug("Price updater already running")
        return

    _updater_task = asyncio.create_task(
        _updater_loop(), name="price-updater"
    )
    logger.info(
        "Price updater started (interval=%ds, stale_threshold=%ds)",
        _REFRESH_INTERVAL,
        _STALE_THRESHOLD,
    )


async def stop_price_updater() -> None:
    """
    Cancel the background updater and close the HTTP session.
    Call during app shutdown.
    """
    global _updater_task

    if _updater_task is not None and not _updater_task.done():
        _updater_task.cancel()
        try:
            await _updater_task
        except asyncio.CancelledError:
            pass
        logger.info("Price updater stopped")

    _updater_task = None
    await close_provider_session()


# ── Public API ──────────────────────────────────────────────────

async def get_price(token: str) -> float:
    """
    Get the cached USD price for a single token.

    Args:
        token: Uppercase symbol (e.g. "BTC", "ETH").

    Returns:
        USD price as a float.

    Raises:
        ValueError: If the token is not supported or has no cached price.
    """
    token_upper = token.upper().strip()

    if token_upper not in SUPPORTED_TOKENS:
        raise ValueError(
            f"Unsupported token: '{token}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_TOKENS))}"
        )

    # Ensure cache is warm (no-op if already populated)
    await _ensure_cache_warm()

    price = _PRICE_CACHE.get(token_upper)
    if price is None or price <= 0:
        raise ValueError(
            f"Price unavailable for {token_upper} — cache may be stale"
        )

    return price


async def get_all_prices() -> Dict[str, float]:
    """
    Return a frozen snapshot of ALL cached prices.
    Useful for bulk display / dashboards.

    Returns:
        {"BTC": 65000.0, "ETH": 3000.0, ...}
    """
    await _ensure_cache_warm()
    # Return a copy so callers cannot mutate the cache
    return dict(_PRICE_CACHE)


def get_cache_age() -> float:
    """
    Return the age of the cache in seconds (since last successful refresh).
    Returns float('inf') if the cache has never been populated.
    """
    if _last_updated == 0.0:
        return float("inf")
    return time.monotonic() - _last_updated


def is_cache_stale() -> bool:
    """Check whether the cache exceeds the staleness threshold."""
    return get_cache_age() > _STALE_THRESHOLD
