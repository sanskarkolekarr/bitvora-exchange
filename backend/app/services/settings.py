"""
Dynamic settings service — reads/writes settings from the DB.

Provides an in-memory cache with instant invalidation on writes.
Falls back to .env values if the database is unreachable.

Public API:
    get_inr_rate()   → float   (cached, DB-backed)
    set_inr_rate()   → float   (writes to DB, invalidates cache)
    seed_defaults()  → None    (insert defaults on startup)
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logger import get_logger
from app.models.setting import Setting

logger = get_logger("services.settings")

# ── In-memory cache ─────────────────────────────────────────────
_inr_rate_cache: Optional[float] = None
_cache_timestamp: float = 0.0
_CACHE_TTL: float = 30.0  # seconds — re-read from DB every 30s
_cache_lock: asyncio.Lock = asyncio.Lock()


async def _read_setting_from_db(key: str) -> Optional[str]:
    """
    Read a single setting value from the database.
    Returns None if not found or on DB error.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Setting.value_str).where(Setting.key == key)
            )
            row = result.scalar_one_or_none()
            return row
    except Exception as exc:
        logger.warning("Failed to read setting '%s' from DB: %s", key, exc)
        return None


async def _write_setting_to_db(key: str, value: str) -> bool:
    """
    Write (upsert) a setting into the database.
    Returns True on success, False on failure.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Setting).where(Setting.key == key)
            )
            existing = result.scalar_one_or_none()

            try:
                v_float = float(value)
            except ValueError:
                v_float = 0.0

            if existing:
                existing.value_str = value
                existing.value_float = v_float
            else:
                new_setting = Setting(
                    key=key,
                    value_str=value,
                    value_float=v_float,
                )
                session.add(new_setting)

            await session.commit()
            return True
    except Exception as exc:
        logger.error("Failed to write setting '%s' to DB: %s", key, exc)
        return False


# ── INR Rate API ────────────────────────────────────────────────

async def get_inr_rate() -> float:
    """
    Get the current INR rate.

    Priority:
        1. In-memory cache (if fresh, < CACHE_TTL seconds old)
        2. Database (settings table, key='INR_RATE')
        3. Fallback: .env INR_RATE via config.settings

    The cache is invalidated on write or after TTL expiry.
    """
    global _inr_rate_cache, _cache_timestamp

    # Fast path — return cached value if fresh
    now = time.monotonic()
    if _inr_rate_cache is not None and (now - _cache_timestamp) < _CACHE_TTL:
        return _inr_rate_cache

    # Slow path — read from DB
    async with _cache_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _inr_rate_cache is not None and (now - _cache_timestamp) < _CACHE_TTL:
            return _inr_rate_cache

        db_value = await _read_setting_from_db("INR_RATE")

        if db_value is not None:
            try:
                rate = float(db_value)
                if rate > 0:
                    _inr_rate_cache = rate
                    _cache_timestamp = time.monotonic()
                    logger.debug("INR rate loaded from DB: %.2f", rate)
                    return rate
            except (ValueError, TypeError):
                logger.warning("Invalid INR_RATE in DB: '%s'", db_value)

        # Fallback to .env
        fallback = settings.INR_RATE
        _inr_rate_cache = fallback
        _cache_timestamp = time.monotonic()
        logger.warning(
            "INR rate falling back to .env value: %.2f", fallback
        )
        return fallback


async def set_inr_rate(new_rate: float) -> float:
    """
    Update the INR rate in the database and invalidate the cache.
    Returns the new rate on success.

    Raises:
        ValueError: If the rate is not positive.
        RuntimeError: If the DB write fails.
    """
    global _inr_rate_cache, _cache_timestamp

    if new_rate <= 0:
        raise ValueError(f"INR rate must be positive, got {new_rate}")

    success = await _write_setting_to_db("INR_RATE", str(new_rate))
    if not success:
        raise RuntimeError("Failed to persist INR rate to database")

    # Immediately update the cache
    async with _cache_lock:
        _inr_rate_cache = new_rate
        _cache_timestamp = time.monotonic()

    logger.info("INR rate updated to %.2f and cached", new_rate)
    return new_rate


def invalidate_inr_cache() -> None:
    """Force the next get_inr_rate() call to re-read from DB."""
    global _inr_rate_cache, _cache_timestamp
    _inr_rate_cache = None
    _cache_timestamp = 0.0
    logger.debug("INR rate cache invalidated")


# ── Maintenance Mode API ────────────────────────────────────────

_maintenance_cache: Optional[bool] = None
_maintenance_timestamp: float = 0.0

async def get_maintenance_mode() -> bool:
    """Check if the exchange is in maintenance mode."""
    global _maintenance_cache, _maintenance_timestamp

    now = time.monotonic()
    if _maintenance_cache is not None and (now - _maintenance_timestamp) < _CACHE_TTL:
        return _maintenance_cache

    async with _cache_lock:
        now = time.monotonic()
        if _maintenance_cache is not None and (now - _maintenance_timestamp) < _CACHE_TTL:
            return _maintenance_cache

        db_value = await _read_setting_from_db("MAINTENANCE_MODE")
        if db_value is not None:
            _maintenance_cache = (db_value.lower() == "true")
        else:
            _maintenance_cache = False
            
        _maintenance_timestamp = time.monotonic()
        return _maintenance_cache

async def set_maintenance_mode(active: bool) -> bool:
    """Enable or disable maintenance mode."""
    global _maintenance_cache, _maintenance_timestamp

    success = await _write_setting_to_db("MAINTENANCE_MODE", str(active).lower())
    if not success:
        raise RuntimeError("Failed to set maintenance mode")

    async with _cache_lock:
        _maintenance_cache = active
        _maintenance_timestamp = time.monotonic()

    logger.info("Maintenance mode set to %s", active)
    return active


# ── Startup seeding ─────────────────────────────────────────────

async def seed_defaults() -> None:
    """
    Insert default settings into the database if they don't exist.
    Called once during app startup.
    """
    db_value = await _read_setting_from_db("INR_RATE")
    if db_value is None:
        env_rate = settings.INR_RATE
        success = await _write_setting_to_db("INR_RATE", str(env_rate))
        if success:
            logger.info(
                "Seeded INR_RATE=%.2f from .env into settings table", env_rate
            )
        else:
            logger.warning("Could not seed INR_RATE into settings table")
    else:
        logger.info("INR_RATE already exists in DB: %s", db_value)

    # Seed maintenance mode
    maint_val = await _read_setting_from_db("MAINTENANCE_MODE")
    if maint_val is None:
        await _write_setting_to_db("MAINTENANCE_MODE", "false")
        logger.info("Seeded MAINTENANCE_MODE=false")
