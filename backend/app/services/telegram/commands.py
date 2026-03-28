"""
Admin command handlers for the Telegram bot.

Supported commands:
    /status   — system status + transaction count
    /setrate  — dynamically update INR conversion rate (persisted to DB)
    /paid     — mark a transaction as paid
    /pending  — revert a transaction to pending
    /fail     — mark a transaction as failed
    /info     — show full transaction details
    /help     — list available commands

All commands are gated by TELEGRAM_ADMIN_IDS.
Unauthorised users receive a rejection message.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_session
from app.core.logger import get_logger
from app.models.log import AdminLog
from app.models.transaction import Transaction, TransactionStatus
from app.services.settings import get_inr_rate, set_inr_rate

logger = get_logger("telegram.commands")

# ── Module-level state ──────────────────────────────────────────

# Transaction counter placeholder — incremented by the worker layer.
_tx_count: int = 0

# Whether commands have already been registered on the dispatcher
_registered: bool = False

router = Router(name="admin_commands")


# ── Public helpers ──────────────────────────────────────────────

async def get_current_inr_rate() -> float:
    """Return the current live INR rate from the database."""
    return await get_inr_rate()


def increment_tx_count(n: int = 1) -> None:
    """Increment the processed transactions counter."""
    global _tx_count
    _tx_count += n


# ── Admin guard ─────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    """Check if a Telegram user ID is in the admin list."""
    return user_id in settings.admin_ids_list


async def _reject(message: Message) -> None:
    """Send a polite rejection to non-admin users."""
    await message.reply(
        "🚫 <b>Access Denied</b>\n\n"
        "You are not authorised to use admin commands.",
    )
    logger.warning(
        "Unauthorised command attempt by user_id=%d (@%s)",
        message.from_user.id,
        message.from_user.username or "N/A",
    )


# ── Audit logging helper ───────────────────────────────────────

async def _log_admin_action(
    admin_username: str,
    action: str,
    target_id: str | None = None,
    note: str | None = None,
) -> None:
    """Persist an admin action to the admin_logs table."""
    try:
        async with get_session() as session:
            log_entry = AdminLog(
                id=str(uuid.uuid4()),
                admin_username=admin_username,
                action=action,
                target_id=target_id,
                note=note,
                created_at=datetime.now(timezone.utc),
            )
            session.add(log_entry)
            # commit happens automatically via get_session context manager
        logger.info(
            "Admin action logged: %s by %s (target=%s)",
            action, admin_username, target_id,
        )
    except Exception:
        logger.exception("Failed to log admin action: %s", action)


# ── Transaction lookup helper ──────────────────────────────────

async def _find_transaction(txid: str) -> Transaction | None:
    """Find a transaction by TXID (exact match)."""
    async with get_session() as session:
        stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


# ── /paid <txid> ────────────────────────────────────────────────

@router.message(Command("paid"))
async def cmd_paid(message: Message) -> None:
    """Mark a transaction as PAID with timestamp."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Usage:</b>  <code>/paid &lt;txid&gt;</code>\n"
            "Example:  <code>/paid 0xabc123...</code>"
        )
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                await message.reply(
                    f"❌ <b>Transaction not found</b>\n\n"
                    f"TXID: <code>{txid}</code>\n"
                    f"No matching record in the database."
                )
                return

            now = datetime.now(timezone.utc)
            tx.status = TransactionStatus.PAID
            tx.paid_at = now
            # commit happens via context manager

        await message.reply(
            f"✅ <b>Payment marked as PAID</b>\n\n"
            f"<b>TXID:</b>  <code>{txid}</code>\n"
            f"<b>Paid at:</b>  {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"Dashboard will reflect this change instantly."
        )

        await _log_admin_action(
            admin_username=admin_name,
            action="MARK_PAID",
            target_id=txid,
            note=f"Status changed to PAID at {now.isoformat()}",
        )

        logger.info(
            "Admin %s marked TXID %s as PAID",
            admin_name, txid[:16],
        )

    except Exception as exc:
        logger.exception("Error processing /paid command for TXID %s", txid)
        await message.reply(
            f"❌ <b>Error</b>\n\n"
            f"Failed to update transaction: {exc}"
        )


# ── /pending <txid> ─────────────────────────────────────────────

@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    """Revert a transaction status to PENDING."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Usage:</b>  <code>/pending &lt;txid&gt;</code>\n"
            "Example:  <code>/pending 0xabc123...</code>"
        )
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                await message.reply(
                    f"❌ <b>Transaction not found</b>\n\n"
                    f"TXID: <code>{txid}</code>"
                )
                return

            old_status = tx.status.value
            tx.status = TransactionStatus.PENDING

        await message.reply(
            f"🔄 <b>Status reverted to PENDING</b>\n\n"
            f"<b>TXID:</b>  <code>{txid}</code>\n"
            f"<b>Previous status:</b>  {old_status.upper()}"
        )

        await _log_admin_action(
            admin_username=admin_name,
            action="MARK_PENDING",
            target_id=txid,
            note=f"Status changed from {old_status} to pending",
        )

        logger.info(
            "Admin %s reverted TXID %s to PENDING (was %s)",
            admin_name, txid[:16], old_status,
        )

    except Exception as exc:
        logger.exception("Error processing /pending command for TXID %s", txid)
        await message.reply(
            f"❌ <b>Error</b>\n\n"
            f"Failed to update transaction: {exc}"
        )


# ── /fail <txid> ────────────────────────────────────────────────

@router.message(Command("fail"))
async def cmd_fail(message: Message) -> None:
    """Mark a transaction as FAILED."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Usage:</b>  <code>/fail &lt;txid&gt;</code>\n"
            "Example:  <code>/fail 0xabc123...</code>"
        )
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                await message.reply(
                    f"❌ <b>Transaction not found</b>\n\n"
                    f"TXID: <code>{txid}</code>"
                )
                return

            old_status = tx.status.value
            tx.status = TransactionStatus.FAILED

        await message.reply(
            f"🚫 <b>Transaction marked as FAILED</b>\n\n"
            f"<b>TXID:</b>  <code>{txid}</code>\n"
            f"<b>Previous status:</b>  {old_status.upper()}"
        )

        await _log_admin_action(
            admin_username=admin_name,
            action="MARK_FAILED",
            target_id=txid,
            note=f"Status changed from {old_status} to failed",
        )

        logger.info(
            "Admin %s marked TXID %s as FAILED (was %s)",
            admin_name, txid[:16], old_status,
        )

    except Exception as exc:
        logger.exception("Error processing /fail command for TXID %s", txid)
        await message.reply(
            f"❌ <b>Error</b>\n\n"
            f"Failed to update transaction: {exc}"
        )


# ── /info <txid> ────────────────────────────────────────────────

@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    """Return full details of a transaction."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Usage:</b>  <code>/info &lt;txid&gt;</code>\n"
            "Example:  <code>/info 0xabc123...</code>"
        )
        return

    txid = parts[1].strip()

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                await message.reply(
                    f"❌ <b>Transaction not found</b>\n\n"
                    f"TXID: <code>{txid}</code>\n"
                    f"No matching record in the database."
                )
                return

            # Build info response
            paid_str = (
                tx.paid_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                if tx.paid_at else "—"
            )
            created_str = (
                tx.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                if tx.created_at else "—"
            )

            text = (
                f"📋 <b>Transaction Details</b>\n"
                f"\n"
                f"<b>TXID:</b>  <code>{tx.txid}</code>\n"
                f"<b>Reference:</b>  <code>{tx.reference}</code>\n"
                f"<b>Chain:</b>  {tx.chain.upper()}\n"
                f"<b>Token:</b>  {(tx.token or 'Native').upper()}\n"
                f"\n"
                f"<b>Amount:</b>  {tx.amount or 0:,.6g}\n"
                f"<b>USD:</b>  ${tx.usd_value or 0:,.2f}\n"
                f"<b>INR:</b>  ₹{tx.inr_value or 0:,.2f}\n"
                f"\n"
                f"<b>Status:</b>  {tx.status.value.upper()}\n"
                f"<b>User ID:</b>  <code>{tx.user_id or 'N/A'}</code>\n"
                f"\n"
                f"<b>Created:</b>  {created_str}\n"
                f"<b>Paid at:</b>  {paid_str}\n"
                f"<b>Retries:</b>  {tx.retry_count}"
            )

            await message.reply(text)

        await _log_admin_action(
            admin_username=message.from_user.username or str(message.from_user.id),
            action="VIEW_INFO",
            target_id=txid,
        )

        logger.info(
            "Admin %d requested /info for TXID %s",
            message.from_user.id, txid[:16],
        )

    except Exception as exc:
        logger.exception("Error processing /info command for TXID %s", txid)
        await message.reply(
            f"❌ <b>Error</b>\n\n"
            f"Failed to fetch transaction: {exc}"
        )


# ── /status ─────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Return system status and transaction count."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    current_rate = await get_inr_rate()

    text = (
        "📊 <b>System Status</b>\n"
        "\n"
        f"<b>Status:</b>  🟢 Online\n"
        f"<b>Environment:</b>  {settings.ENVIRONMENT}\n"
        f"<b>INR Rate:</b>  ₹{current_rate:,.2f}\n"
        f"<b>Transactions Processed:</b>  {_tx_count:,}\n"
        f"<b>Supported Chains:</b>  {', '.join(c.upper() for c in settings.chains_list)}\n"
        "\n"
        f"<b>Server Time:</b>  {now}"
    )

    await message.reply(text)
    logger.info("Admin %d requested /status", message.from_user.id)


# ── /setrate ────────────────────────────────────────────────────

@router.message(Command("setrate"))
async def cmd_setrate(message: Message) -> None:
    """Dynamically update the INR conversion rate (persisted to DB)."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Usage:</b>  <code>/setrate &lt;value&gt;</code>\n"
            "Example:  <code>/setrate 84</code>"
        )
        return

    raw_value = parts[1].strip()

    try:
        new_rate = float(raw_value)
    except ValueError:
        await message.reply(
            f"❌ <b>Invalid number:</b> <code>{raw_value}</code>\n"
            "Please provide a valid numeric value."
        )
        return

    if new_rate <= 0:
        await message.reply("❌ Rate must be a positive number.")
        return

    old_rate = await get_inr_rate()

    try:
        await set_inr_rate(new_rate)
    except RuntimeError as exc:
        await message.reply(
            f"❌ <b>Failed to save rate:</b> {exc}\n"
            "The rate was NOT updated."
        )
        return

    admin_name = message.from_user.username or str(message.from_user.id)

    await message.reply(
        f"✅ <b>INR Rate Updated</b>\n\n"
        f"<b>Old:</b>  ₹{old_rate:,.2f}\n"
        f"<b>New:</b>  ₹{new_rate:,.2f}\n\n"
        f"💾 Saved to database — applied instantly."
    )

    await _log_admin_action(
        admin_username=admin_name,
        action="SET_RATE",
        note=f"INR rate changed from {old_rate:.2f} to {new_rate:.2f}",
    )

    logger.info(
        "Admin %d updated INR rate: %.2f → %.2f (persisted to DB)",
        message.from_user.id,
        old_rate,
        new_rate,
    )


# ── /help ───────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """List available admin commands."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    text = (
        "📖 <b>Admin Commands</b>\n"
        "\n"
        "<b>Transaction Control:</b>\n"
        "/paid &lt;txid&gt; — Mark transaction as PAID\n"
        "/pending &lt;txid&gt; — Revert transaction to PENDING\n"
        "/fail &lt;txid&gt; — Mark transaction as FAILED\n"
        "/info &lt;txid&gt; — View full transaction details\n"
        "\n"
        "<b>System:</b>\n"
        "/status — System status &amp; transaction count\n"
        "/setrate &lt;value&gt; — Update INR conversion rate\n"
        "/help — Show this help message"
    )

    await message.reply(text)
    logger.info("Admin %d requested /help", message.from_user.id)


# ── Registration ────────────────────────────────────────────────

def register_admin_commands(dp: Dispatcher) -> None:
    """
    Attach the admin-command router to the dispatcher.
    Idempotent — safe to call multiple times.
    """
    global _registered
    if _registered:
        return
    dp.include_router(router)
    _registered = True
    logger.info("Admin command handlers registered (paid/pending/fail/info/status/setrate/help)")
