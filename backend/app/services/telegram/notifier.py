"""
Transaction notification system.

Sends richly-formatted transaction alerts to the configured Telegram group.
Includes automatic retry with exponential back-off so notifications are
never silently dropped.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError

from app.core.config import settings
from app.core.logger import get_logger
from app.services.telegram.bot import get_bot

logger = get_logger("telegram.notifier")

# ── Configuration ────────────────────────────────────────────────

MAX_RETRIES: int = 4
BASE_BACKOFF_SECONDS: float = 1.0  # doubles on each retry


# ── Public API ───────────────────────────────────────────────────

async def send_tx_notification(data: dict[str, Any]) -> bool:
    """
    Send a formatted transaction notification to the Telegram group.

    Args:
        data: Transaction payload with keys:
            txid, chain, token, amount, usd, inr,
            sender, receiver, timestamp

    Returns:
        True if the message was delivered; False after all retries failed.
    """
    group_id = settings.TELEGRAM_GROUP_ID
    if not group_id:
        logger.error("TELEGRAM_GROUP_ID not configured — notification skipped")
        return False

    message = _format_tx_message(data)
    return await _send_with_retry(chat_id=group_id, text=message)


# ── Message formatting ──────────────────────────────────────────

def _format_tx_message(data: dict[str, Any]) -> str:
    """
    Build a clean, human-readable HTML notification message.
    Includes UPI payout destination when available.
    """
    txid: str = data.get("txid", "unknown")
    chain: str = (data.get("chain") or "unknown").upper()
    token: str = (data.get("token") or "unknown").upper()
    amount: float = data.get("amount", 0.0)
    usd: float = data.get("usd", 0.0)
    inr: float = data.get("inr", 0.0)
    sender: str = data.get("sender", "unknown")
    receiver: str = data.get("receiver", "unknown")
    ts_raw: int = data.get("timestamp", 0)
    upi_id: str = data.get("upi_id", "")
    username: str = data.get("username", "")

    # Truncate long addresses for readability
    sender_short = _truncate_address(sender)
    receiver_short = _truncate_address(receiver)

    # Human-friendly timestamp
    if ts_raw:
        ts_str = datetime.fromtimestamp(ts_raw, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    else:
        ts_str = "N/A"

    # Build payout section if UPI is available
    payout_section = ""
    if upi_id:
        payout_section = (
            "\n"
            "💳 <b>PAYOUT INFO</b>\n"
            f"<b>User:</b>  {username or 'N/A'}\n"
            f"<b>UPI:</b>  <code>{upi_id}</code>\n"
            f"<b>Amount:</b>  ₹{inr:,.2f}\n"
        )

    return (
        "🚀 <b>New Transaction Verified</b>\n"
        "\n"
        f"<b>TXID:</b>  <code>{txid}</code>\n"
        f"<b>Chain:</b>  {chain}\n"
        f"<b>Token:</b>  {token}\n"
        f"<b>Amount:</b>  {amount:,.6g}\n"
        "\n"
        f"<b>USD:</b>  ${usd:,.2f}\n"
        f"<b>INR:</b>  ₹{inr:,.2f}\n"
        "\n"
        f"<b>Sender:</b>  <code>{sender_short}</code>\n"
        f"<b>Receiver:</b>  <code>{receiver_short}</code>\n"
        "\n"
        f"<b>Time:</b>  {ts_str}"
        f"{payout_section}"
    )


def _truncate_address(address: str, head: int = 6, tail: int = 4) -> str:
    """Shorten a blockchain address: 0xAbCdEf…9876"""
    if len(address) <= head + tail + 3:
        return address
    return f"{address[:head]}…{address[-tail:]}"


# ── Delivery with retry ─────────────────────────────────────────

async def _send_with_retry(
    chat_id: str,
    text: str,
    *,
    max_retries: int = MAX_RETRIES,
    base_backoff: float = BASE_BACKOFF_SECONDS,
) -> bool:
    """
    Attempt to send a message with exponential back-off.
    Handles Telegram rate-limit (429) and transient API errors.
    """
    bot = get_bot()
    attempt = 0

    while attempt <= max_retries:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                disable_web_page_preview=True,
            )
            logger.info(
                "Notification delivered to %s (attempt %d)", chat_id, attempt + 1
            )
            return True

        except TelegramRetryAfter as exc:
            # Telegram tells us exactly how long to wait
            wait = exc.retry_after + 0.5
            logger.warning(
                "Rate-limited by Telegram; sleeping %.1fs (attempt %d/%d)",
                wait,
                attempt + 1,
                max_retries + 1,
            )
            await asyncio.sleep(wait)
            attempt += 1

        except TelegramAPIError as exc:
            delay = base_backoff * (2 ** attempt)
            logger.error(
                "Telegram API error: %s — retrying in %.1fs (attempt %d/%d)",
                exc,
                delay,
                attempt + 1,
                max_retries + 1,
            )
            await asyncio.sleep(delay)
            attempt += 1

        except Exception:
            delay = base_backoff * (2 ** attempt)
            logger.exception(
                "Unexpected error sending message — retrying in %.1fs (attempt %d/%d)",
                delay,
                attempt + 1,
                max_retries + 1,
            )
            await asyncio.sleep(delay)
            attempt += 1

    logger.critical(
        "FAILED to deliver notification after %d attempts to chat %s",
        max_retries + 1,
        chat_id,
    )
    return False


# ── Convenience: send arbitrary alert ───────────────────────────

async def send_admin_alert(text: str) -> bool:
    """
    Send a plain-text alert to the admin group.
    Re-uses the same retry logic as transaction notifications.
    """
    group_id = settings.TELEGRAM_GROUP_ID
    if not group_id:
        logger.error("TELEGRAM_GROUP_ID not configured — alert skipped")
        return False
    return await _send_with_retry(chat_id=group_id, text=text)
