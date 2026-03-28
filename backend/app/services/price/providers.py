"""
Price providers — async fetchers for external price APIs.

Primary:   CoinGecko (free /simple/price endpoint)
Fallback:  Binance (/api/v3/ticker/price)

All functions return Dict[str, float] mapping uppercase token symbols to USD prices.
Rate-limit safe: only called by the 60s background updater, never per-request.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

import aiohttp

from app.core.logger import get_logger

logger = get_logger("price.providers")

# ── Token ID mappings ───────────────────────────────────────────
# CoinGecko uses its own slug identifiers.
_COINGECKO_IDS: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
}

# Binance uses trading-pair symbols (against USDT, except USDT itself).
_BINANCE_SYMBOLS: Dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "BNB": "BNBUSDT",
    "USDC": "USDCUSDT",
    # USDT has no pair — hardcoded to 1.0
}

# ── HTTP defaults ───────────────────────────────────────────────
_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BitvoraExchange/2.0",
}

# Reusable session (created lazily, destroyed on shutdown)
_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    """Lazy singleton HTTP session with connection pooling."""
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(
            limit=10,           # max simultaneous connections
            ttl_dns_cache=300,  # DNS cache 5 min
            enable_cleanup_closed=True,
        )
        _session = aiohttp.ClientSession(
            connector=connector,
            timeout=_TIMEOUT,
            headers=_HEADERS,
        )
    return _session


async def close_provider_session() -> None:
    """Gracefully close the shared HTTP session. Call on app shutdown."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
        logger.info("Provider HTTP session closed")


# ── CoinGecko (primary) ────────────────────────────────────────

_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


async def fetch_from_coingecko() -> Dict[str, float]:
    """
    Fetch USD prices for all supported tokens from CoinGecko.

    Returns:
        {"BTC": 65000.0, "ETH": 3000.0, ...}

    Raises:
        aiohttp.ClientError / asyncio.TimeoutError on network failure.
        ValueError if the response body is malformed.
    """
    session = await _get_session()

    ids_csv = ",".join(_COINGECKO_IDS.values())
    params = {"ids": ids_csv, "vs_currencies": "usd"}

    async with session.get(_COINGECKO_URL, params=params) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise ValueError(
                f"CoinGecko returned HTTP {resp.status}: {body[:200]}"
            )

        data: dict = await resp.json(content_type=None)

    # Reverse-map CoinGecko slugs → uppercase symbols
    slug_to_symbol = {slug: sym for sym, slug in _COINGECKO_IDS.items()}
    prices: Dict[str, float] = {}

    for slug, sym in slug_to_symbol.items():
        entry = data.get(slug)
        if not entry or "usd" not in entry:
            logger.warning("CoinGecko: missing price for %s (%s)", sym, slug)
            continue
        price = float(entry["usd"])
        if price <= 0:
            logger.warning("CoinGecko: zero/negative price for %s: %s", sym, price)
            continue
        prices[sym] = price

    if not prices:
        raise ValueError("CoinGecko returned no valid prices")

    logger.debug("CoinGecko prices: %s", prices)
    return prices


# ── Binance (fallback) ──────────────────────────────────────────

_BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"


async def fetch_from_binance() -> Dict[str, float]:
    """
    Fetch USD prices for all supported tokens from Binance.
    Uses individual symbol requests in parallel for speed.

    Returns:
        {"BTC": 65000.0, "ETH": 3000.0, ...}
    """
    session = await _get_session()
    prices: Dict[str, float] = {}

    async def _fetch_one(symbol: str, token: str) -> None:
        try:
            async with session.get(
                _BINANCE_URL, params={"symbol": symbol}
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Binance: HTTP %s for %s", resp.status, symbol
                    )
                    return
                data = await resp.json(content_type=None)
                price = float(data.get("price", 0))
                if price > 0:
                    prices[token] = price
                else:
                    logger.warning("Binance: zero price for %s", token)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning("Binance: failed for %s — %s", token, exc)

    tasks = [
        _fetch_one(symbol, token)
        for token, symbol in _BINANCE_SYMBOLS.items()
    ]
    await asyncio.gather(*tasks)

    # USDT is pegged at 1.0 — no Binance pair needed
    prices.setdefault("USDT", 1.0)

    if not prices:
        raise ValueError("Binance returned no valid prices")

    logger.debug("Binance prices: %s", prices)
    return prices


# ── Unified fetch with fallback ─────────────────────────────────

async def fetch_prices() -> Dict[str, float]:
    """
    Fetch latest USD prices. Tries CoinGecko first; falls back to Binance.

    Returns:
        {"BTC": 65000.0, "ETH": 3000.0, "BNB": 600.0, "USDT": 1.0, "USDC": 1.0}

    Never raises to the caller — returns empty dict on total failure
    (the cache layer handles staleness).
    """
    # ── Primary: CoinGecko ──────────────────────────────────────
    try:
        prices = await fetch_from_coingecko()
        logger.info(
            "Prices fetched via CoinGecko (%d tokens)", len(prices)
        )
        return prices
    except Exception as exc:
        logger.warning("CoinGecko fetch failed: %s — trying Binance", exc)

    # ── Fallback: Binance ───────────────────────────────────────
    try:
        prices = await fetch_from_binance()
        logger.info(
            "Prices fetched via Binance fallback (%d tokens)", len(prices)
        )
        return prices
    except Exception as exc:
        logger.error("Binance fallback also failed: %s", exc)

    # Total failure — return empty, cache layer keeps old values
    return {}
