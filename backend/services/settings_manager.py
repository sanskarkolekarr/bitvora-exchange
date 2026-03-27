"""
BITVORA EXCHANGE — Settings Manager
Cached in-memory store for platform settings (fee%, min_amount, etc).
Reloads from DB every 5 minutes. Admin can flush cache via API.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("bitvora.settings_manager")

# ─── In-memory cache ────────────────────────────────────────────
_cache: dict = {}
_cache_loaded_at: Optional[datetime] = None
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _load_from_db() -> dict:
    """Synchronous DB read — only called when cache is stale."""
    try:
        from database import get_supabase
        db = get_supabase()
        result = db.table("settings").select("*").execute()
        data = {row["key"]: row["value"] for row in (result.data or [])}
        return data
    except Exception as e:
        logger.warning(f"Settings DB read failed: {e}")
        return {}


def _ensure_cache():
    global _cache, _cache_loaded_at
    now = datetime.now(timezone.utc)
    if (
        _cache_loaded_at is None
        or (now - _cache_loaded_at).total_seconds() > _CACHE_TTL_SECONDS
    ):
        fresh = _load_from_db()
        _cache.update(fresh)
        _cache_loaded_at = now


def get_platform_fee() -> float:
    """Returns current platform fee as decimal. Default 1.5%."""
    _ensure_cache()
    try:
        return float(_cache.get("platform_fee_pct", "0.015"))
    except (ValueError, TypeError):
        return 0.015


def get_min_transaction_usd() -> float:
    """Minimum transaction value in USD equivalent. Default $1."""
    _ensure_cache()
    try:
        return float(_cache.get("min_transaction_usd", "1.0"))
    except (ValueError, TypeError):
        return 1.0


def get_max_transaction_usd() -> float:
    """Maximum transaction value in USD equivalent. Default $50,000."""
    _ensure_cache()
    try:
        return float(_cache.get("max_transaction_usd", "50000.0"))
    except (ValueError, TypeError):
        return 50000.0


def get_setting(key: str, default: str = "") -> str:
    """Generic getter for any settings key."""
    _ensure_cache()
    return _cache.get(key, default)


def flush_cache():
    """Force cache reload on next access (call after admin update)."""
    global _cache_loaded_at
    _cache_loaded_at = None
    logger.info("Settings cache flushed")


def update_setting_in_cache(key: str, value: str):
    """Optimistically update local cache (avoids TTL wait after admin writes)."""
    _cache[key] = value
    logger.debug(f"Settings cache updated: {key}={value}")
