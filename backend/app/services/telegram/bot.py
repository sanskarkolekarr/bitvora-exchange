"""
Telegram bot initialization and lifecycle management.

Initializes a global aiogram Bot + Dispatcher using the BOT_TOKEN from
core/config.py. Exposes start/stop helpers for integration with the
FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("telegram.bot")

# ── Global singletons ───────────────────────────────────────────

_bot: Optional[Bot] = None
_dispatcher: Optional[Dispatcher] = None
_polling_task: Optional[asyncio.Task] = None


def get_bot() -> Bot:
    """
    Return the global Bot instance, creating it on first call.
    Raises RuntimeError if TELEGRAM_BOT_TOKEN is not configured.
    """
    global _bot
    if _bot is not None:
        return _bot

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Add it to .env before starting the Telegram service."
        )

    _bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logger.info("Bot instance created (parse_mode=HTML)")
    return _bot


def get_dispatcher() -> Dispatcher:
    """
    Return the global Dispatcher instance, creating it on first call.
    The dispatcher is where command handlers are registered.
    """
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher

    _dispatcher = Dispatcher()
    logger.info("Dispatcher instance created")
    return _dispatcher


# ── Lifecycle helpers ────────────────────────────────────────────

async def start_polling() -> None:
    """
    Begin long-polling in a background task.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _polling_task

    if _polling_task is not None and not _polling_task.done():
        logger.warning("Polling already running; ignoring duplicate start")
        return

    # Ensure bot + dispatcher exist
    bot = get_bot()
    dp = get_dispatcher()

    # Import and register commands before polling starts
    from app.services.telegram.commands import register_admin_commands
    register_admin_commands(dp)

    async def _poll() -> None:
        try:
            # Force-kill any lingering Telegram polling session
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Cleared old webhook/polling session")
            # Wait for Telegram to release the old getUpdates lock
            await asyncio.sleep(3)
            logger.info("Starting long-polling …")
            await dp.start_polling(
                bot,
                handle_signals=False,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
        except asyncio.CancelledError:
            logger.info("Polling cancelled gracefully")
        except Exception:
            logger.exception("Polling crashed unexpectedly")

    _polling_task = asyncio.create_task(_poll(), name="telegram-polling")
    logger.info("Polling background task scheduled")


async def stop_polling() -> None:
    """
    Gracefully shut down the bot and dispatcher.
    """
    global _bot, _dispatcher, _polling_task

    if _polling_task is not None and not _polling_task.done():
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
        logger.info("Polling task cancelled")

    dp = _dispatcher
    if dp is not None:
        try:
            await dp.stop_polling()
            logger.info("Dispatcher stopped")
        except RuntimeError:
            pass  # Polling wasn't started yet — safe to ignore

    bot = _bot
    if bot is not None:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass  # best-effort cleanup
        try:
            session = bot.session
            if session:
                await session.close()
        except Exception:
            pass  # best-effort cleanup
        logger.info("Bot session closed")

    _bot = None
    _dispatcher = None
    _polling_task = None
    logger.info("Telegram service fully shut down")
