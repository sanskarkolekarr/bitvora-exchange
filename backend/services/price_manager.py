"""
BITVORA EXCHANGE — Price Manager Worker
Fetches live INR rates from CoinGecko and upserts exchange_rates table.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict
import httpx
from database import get_supabase

logger = logging.getLogger("bitvora.worker.price_manager")

# In-memory cache for instant reads during transaction processing
_rate_cache: Dict[str, float] = {}
_cache_updated_at: Optional[datetime] = None

# CoinGecko ID mapping
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "TRX": "tron",
    "TON": "the-open-network",
    "USDT": "tether",
    "USDC": "usd-coin",
    "LTC": "litecoin",
}


def get_cached_rate(asset: str) -> Optional[float]:
    """Read rate from in-memory cache. No DB query needed."""
    return _rate_cache.get(asset.upper())


def get_all_cached_rates() -> Dict[str, float]:
    """Return full cache snapshot."""
    return dict(_rate_cache)


async def _fetch_rates() -> Dict[str, float]:
    """Fetch current rates from CoinGecko, using custom USD rate if set."""
    db = get_supabase()
    custom_usd_res = db.table("exchange_rates").select("rate_inr").eq("asset", "USD").execute()
    custom_usd_rate = None
    if custom_usd_res.data:
        custom_usd_rate = float(custom_usd_res.data[0]["rate_inr"])

    ids = ",".join(COINGECKO_IDS.values())
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd,inr"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    rates = {}
    if custom_usd_rate:
        rates["USD"] = custom_usd_rate
        for asset, gecko_id in COINGECKO_IDS.items():
            usd_price = data.get(gecko_id, {}).get("usd")
            if usd_price is not None:
                rates[asset] = round(float(usd_price) * custom_usd_rate, 2)
    else:
        for asset, gecko_id in COINGECKO_IDS.items():
            price = data.get(gecko_id, {}).get("inr")
            if price is not None:
                rates[asset] = round(float(price), 2)

    return rates


async def _upsert_rates(rates: Dict[str, float]):
    """Write rates to Supabase exchange_rates table."""
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    for asset, rate in rates.items():
        db.table("exchange_rates").upsert(
            {
                "asset": asset,
                "rate_inr": rate,
                "source": "coingecko",
                "updated_at": now,
            },
            on_conflict="asset",
        ).execute()


async def price_manager_worker():
    """
    Runs every 60 seconds. Fetches rates from CoinGecko,
    updates the DB, and refreshes the in-memory cache.
    """
    global _rate_cache, _cache_updated_at

    logger.info("Price manager worker started")

    while True:
        try:
            rates = await _fetch_rates()

            if rates:
                # Update in-memory cache
                _rate_cache.update(rates)
                _cache_updated_at = datetime.now(timezone.utc)

                # Persist to DB
                await _upsert_rates(rates)

                logger.info(
                    f"Updated {len(rates)} exchange rates — BTC: ₹{rates.get('BTC', 'N/A'):,.0f}"
                )
            else:
                logger.warning("CoinGecko returned empty rates — using cached values")

        except asyncio.CancelledError:
            logger.info("Price manager worker cancelled")
            break
        except Exception as e:
            logger.error(f"Price manager error: {e} — falling back to cached rates")

        await asyncio.sleep(60)
