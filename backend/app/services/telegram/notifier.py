"""
Transaction notification system.

Sends richly-formatted transaction alerts to the configured Telegram group.
Includes automatic retry with exponential back-off so notifications are
never silently dropped.
"""

from __future__ import annotations

import asyncio
import glob
import os
from datetime import datetime, timezone
from typing import Any

from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

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

    Automatically attaches the user's QR code if a temp file was saved
    during the submit step (keyed by txid). This gives a single message
    with both verified USD/INR values AND the QR image.

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

    # Auto-detect QR file saved at submit time (pattern: /tmp/qr_<txid[:24]>.*)
    txid = data.get("txid", "")
    qr_path = _find_qr_temp(txid)

    if qr_path:
        logger.info("[QR] Found temp QR for txid=%s — sending as photo", txid[:16])
        result = await send_tx_photo_notification(data, qr_path)
        # Clean up temp file
        try:
            os.remove(qr_path)
            logger.info("[QR] Cleaned up temp QR: %s", qr_path)
        except Exception:
            logger.warning("[QR] Could not remove temp QR: %s", qr_path)
        return result

    # No QR — fall back to plain text
    message = _format_tx_message(data)

    db_id = data.get("id")
    if db_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Mark Paid", callback_data=f"paid:{db_id}"),
                InlineKeyboardButton(text="❌ Fail", callback_data=f"fail:{db_id}")
            ]
        ])
    else:
        markup = None

    return await _send_with_retry(chat_id=group_id, text=message, reply_markup=markup)


def _find_qr_temp(txid: str) -> str | None:
    """Look for a QR temp file matching /tmp/qr_<txid[:24]>.*"""
    if not txid:
        return None
    import tempfile
    txid_safe = txid[:24].replace("/", "_")
    pattern = os.path.join(tempfile.gettempdir(), f"qr_{txid_safe}.*")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


async def send_tx_photo_notification(data: dict[str, Any], photo_path: str) -> bool:
    """
    Send a transaction notification where the QR code photo is the primary
    message and order details are sent as the caption.

    Falls back to a plain text notification if photo delivery fails.
    """
    group_id = settings.TELEGRAM_GROUP_ID
    if not group_id:
        logger.error("TELEGRAM_GROUP_ID not configured — notification skipped")
        return False

    caption = _format_tx_message(data)
    # Telegram caption max is 1024 chars; trim if needed
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    db_id = data.get("id")
    if db_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Mark Paid", callback_data=f"paid:{db_id}"),
                InlineKeyboardButton(text="❌ Fail", callback_data=f"fail:{db_id}")
            ]
        ])
    else:
        markup = None

    # Try sending as photo with caption
    try:
        photo_input = FSInputFile(photo_path)
        bot = get_bot()
        await bot.send_photo(
            chat_id=group_id,
            photo=photo_input,
            caption=caption,
            reply_markup=markup,
        )
        logger.info("[QR] Photo notification delivered to %s", group_id)
        return True
    except Exception as exc:
        logger.error("[QR] Photo send failed (%s), falling back to text", exc)
        # Fallback: send plain text message
        return await _send_with_retry(chat_id=group_id, text=caption, reply_markup=markup)

async def send_support_ticket(data: dict[str, Any]) -> bool:
    """
    Send a formatted support ticket notification to the Telegram report group.
    Falls back to TELEGRAM_GROUP_ID if TELEGRAM_REPORT_GROUP_ID is not configured.
    """
    group_id = settings.TELEGRAM_REPORT_GROUP_ID or settings.TELEGRAM_GROUP_ID
    if not group_id:
        logger.error("No TELEGRAM_REPORT_GROUP_ID configured — ticket skipped")
        return False

    ticket_id = data.get("id", "unknown")
    subject = data.get("subject", "No Subject")
    message_text = data.get("message", "No Message")
    contact = data.get("contact", "Not provided")
    reference = data.get("reference", "Not provided")
    user_id = data.get("user_id", "Unknown")

    # Format message
    message = (
        "🎫 <b>New Support Ticket</b>\n"
        "\n"
        f"<b>Subject:</b> {subject}\n"
        f"<b>Reference:</b> <code>{reference}</code>\n"
        f"<b>Contact:</b> {contact}\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        "\n"
        "<b>Message:</b>\n"
        f"{message_text}\n"
        "\n"
        f"<i>Ticket ID: {ticket_id}</i>\n"
        "⚡ <b>Action Required:</b> @xchanzer"
    )

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

    # We no longer need a separate payout_section as per new design

    return (
        "🚀 <b>New Transaction Submitted</b>\n"
        "\n"
        f"👤 <b>User:</b> {username or 'N/A'}\n"
        f"💳 <b>UPI:</b> <code>{upi_id or 'Not Set'}</code>\n"
        "\n"
        f"<b>Chain:</b> {chain}\n"
        f"<b>Token:</b> {token}\n"
        "\n"
        f"<b>Amount:</b> {amount:,.6g}\n"
        f"<b>USD Value:</b> ${usd:,.2f}\n"
        f"<b>INR Value:</b> ₹{inr:,.2f}\n"
        "\n"
        "<b>TXID:</b>\n"
        f"<code>{txid}</code>\n"
        "\n"
        "<b>Sender:</b>\n"
        f"<code>{sender}</code>\n"
        "\n"
        "<b>Receiver:</b>\n"
        f"<code>{receiver}</code>\n"
        "\n"
        "<b>Time:</b>\n"
        f"{ts_str}\n"
        "\n"
        "⚡ <b>Action Required:</b> @xchanzer"
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
    reply_markup: InlineKeyboardMarkup | None = None,
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
                reply_markup=reply_markup,
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
