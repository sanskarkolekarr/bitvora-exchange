"""
Admin command handlers for the Telegram bot.

    /status      — system status + transaction count
    /ping        — check if bot is working
    /setrate     — dynamically update INR conversion rate (persisted to DB)
    /pending     — list confirmed but unpaid transactions
    /paid        — mark a transaction as paid
    /success     — mark a transaction as successful (CONFIRMED)
    /revert      — revert a transaction to pending
    /fail        — mark a transaction as failed
    /refund      — mark a transaction as refunded
    /delete      — permanently delete a transaction record
    /info        — show full transaction details
    /history     — show last 5 transactions for a user
    /user        — view user profile and stats
    /users       — view all registered users
    /ban         — ban a user from the platform
    /unban       — unban a user
    /stats       — show 24-hour financial volume
    /maintenance — toggle global maintenance mode
    /help        — list available commands

All commands are gated by TELEGRAM_ADMIN_IDS.
Unauthorised users receive a rejection message.
"""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone, timedelta

from aiogram import Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func, delete, desc

from app.core.config import settings
from app.core.database import get_session
from app.core.logger import get_logger
from app.models.log import AdminLog
from app.models.user import User
from app.models.transaction import Transaction, TransactionStatus
from app.services.settings import (
    get_inr_rate, 
    set_inr_rate,
    get_maintenance_mode,
    set_maintenance_mode
)

logger = get_logger("telegram.commands")

# ── Module-level state ──────────────────────────────────────────

_tx_count: int = 0
_registered: bool = False

router = Router(name="admin_commands")


# ── Public helpers ──────────────────────────────────────────────

async def get_current_inr_rate() -> float:
    return await get_inr_rate()

def increment_tx_count(n: int = 1) -> None:
    global _tx_count
    _tx_count += n


# ── Admin guard ─────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids_list

async def _reject(message: Message | CallbackQuery) -> None:
    text = "🚫 <b>Access Denied</b>\n\nYou are not authorised to use admin commands."
    if isinstance(message, Message):
        await message.reply(text)
    else:
        await message.answer(text, show_alert=True)
        
    user = message.from_user
    logger.warning("Unauthorised command attempt by user_id=%d (@%s)", user.id, user.username or "N/A")


# ── Audit logging helper ───────────────────────────────────────

async def _log_admin_action(
    admin_username: str,
    action: str,
    target_id: str | None = None,
    note: str | None = None,
) -> None:
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
        logger.info("Admin action logged: %s by %s (target=%s)", action, admin_username, target_id)
    except Exception:
        logger.exception("Failed to log admin action: %s", action)


# ── Core Action Logic ───────────────────────────────────────────

async def _update_transaction_status(
    txid: str, 
    new_status: TransactionStatus, 
    admin_name: str
) -> tuple[bool, str]:
    """Core logic to update status, return (success, message)."""
    try:
        async with get_session() as session:
            stmt = select(Transaction).where(
                (Transaction.txid == txid) | (Transaction.id == txid)
            ).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                return False, f"❌ <b>Transaction not found</b>\n\nTXID: <code>{txid}</code>"

            old_status = tx.status.value
            tx.status = new_status
            
            if new_status == TransactionStatus.PAID:
                tx.paid_at = datetime.now(timezone.utc)

        # Build response message based on status
        if new_status == TransactionStatus.PAID:
            msg = (
                f"✅ <b>Payment marked as PAID</b>\n\n"
                f"<b>TXID:</b>  <code>{txid}</code>\n"
                f"<b>Paid at:</b>  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                f"Dashboard will reflect this change instantly."
            )
            action = "MARK_PAID"
        elif new_status == TransactionStatus.FAILED:
            msg = (
                f"🚫 <b>Transaction marked as FAILED</b>\n\n"
                f"<b>TXID:</b>  <code>{txid}</code>\n"
                f"<b>Previous status:</b>  {old_status.upper()}"
            )
            action = "MARK_FAILED"
        elif new_status == TransactionStatus.REFUNDED:
            msg = (
                f"⏪ <b>Transaction marked as REFUNDED</b>\n\n"
                f"<b>TXID:</b>  <code>{txid}</code>\n"
                f"<b>Previous status:</b>  {old_status.upper()}"
            )
            action = "MARK_REFUNDED"
        elif new_status == TransactionStatus.CONFIRMED:
            msg = (
                f"✅ <b>Transaction marked as SUCCESS (CONFIRMED)</b>\n\n"
                f"<b>TXID:</b>  <code>{txid}</code>\n"
                f"<b>Previous status:</b>  {old_status.upper()}"
            )
            action = "MARK_SUCCESS"
        else: # PENDING
            msg = (
                f"🔄 <b>Status reverted to PENDING</b>\n\n"
                f"<b>TXID:</b>  <code>{txid}</code>\n"
                f"<b>Previous status:</b>  {old_status.upper()}"
            )
            action = "MARK_PENDING"

        await _log_admin_action(
            admin_username=admin_name,
            action=action,
            target_id=txid,
            note=f"Status changed from {old_status} to {new_status.value}",
        )

        logger.info("Admin %s marked TXID %s as %s (was %s)", admin_name, txid[:16], new_status.value.upper(), old_status)
        return True, msg

    except Exception as exc:
        logger.exception("Error processing status update for TXID %s", txid)
        return False, f"❌ <b>Error</b>\n\nFailed to update transaction: {html.escape(str(exc))}"


# ── Inline Button Callbacks ──────────────────────────────────────

@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _reject(callback)
        return

    txid = callback.data.split(":", 1)[1]
    admin_name = callback.from_user.username or str(callback.from_user.id)
    
    success, msg_text = await _update_transaction_status(txid, TransactionStatus.PAID, admin_name)
    
    await callback.answer("Marked as PAID!" if success else "Failed to mark paid.", show_alert=not success)
    
    if success and callback.message:
        original_text = callback.message.html_text or ""
        new_text = original_text + f"\n\n✅ <b>Action:</b> Marked PAID by @{admin_name}"
        try:
            await callback.message.edit_text(new_text, reply_markup=None)
        except Exception:
            pass

@router.callback_query(F.data.startswith("fail:"))
async def cb_fail(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _reject(callback)
        return

    txid = callback.data.split(":", 1)[1]
    admin_name = callback.from_user.username or str(callback.from_user.id)
    
    success, msg_text = await _update_transaction_status(txid, TransactionStatus.FAILED, admin_name)
    
    await callback.answer("Marked as FAILED!" if success else "Failed to mark failed.", show_alert=not success)
    
    if success and callback.message:
        original_text = callback.message.html_text or ""
        new_text = original_text + f"\n\n🚫 <b>Action:</b> Marked FAILED by @{admin_name}"
        try:
            await callback.message.edit_text(new_text, reply_markup=None)
        except Exception:
            pass


# ── Action Commands ──────────────────────────────────────────────

@router.message(Command("paid"))
async def cmd_paid(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/paid &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)
    _, msg_text = await _update_transaction_status(txid, TransactionStatus.PAID, admin_name)
    await message.reply(msg_text)

@router.message(Command("fail"))
async def cmd_fail(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/fail &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)
    _, msg_text = await _update_transaction_status(txid, TransactionStatus.FAILED, admin_name)
    await message.reply(msg_text)

@router.message(Command("refund"))
async def cmd_refund(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/refund &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)
    _, msg_text = await _update_transaction_status(txid, TransactionStatus.REFUNDED, admin_name)
    await message.reply(msg_text)

@router.message(Command("success"))
async def cmd_success(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/success &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)
    _, msg_text = await _update_transaction_status(txid, TransactionStatus.CONFIRMED, admin_name)
    await message.reply(msg_text)

@router.message(Command("revert"))
async def cmd_revert(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/revert &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)
    _, msg_text = await _update_transaction_status(txid, TransactionStatus.PENDING, admin_name)
    await message.reply(msg_text)

@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/delete &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                await message.reply("❌ <b>Transaction not found</b>")
                return

            await session.delete(tx)
            
        await _log_admin_action(admin_name, "DELETE_TX", txid, "Transaction physically deleted from database")
        await message.reply(f"🗑️ <b>Transaction Deleted</b>\n\n<b>TXID:</b> <code>{txid}</code>\nPermanently removed from database.")
    except Exception as exc:
        await message.reply(f"❌ <b>Error:</b> {html.escape(str(exc))}")


# ── User Management ──────────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/ban &lt;username_or_id&gt;</code>")
        return

    target = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        async with get_session() as session:
            stmt = select(User).where((User.username == target) | (User.id == target)).limit(1)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                await message.reply("❌ <b>User not found</b>")
                return

            if user.is_banned:
                await message.reply("⚠️ <b>User is already banned.</b>")
                return

            user.is_banned = True
            
        await _log_admin_action(admin_name, "BAN_USER", user.id, f"Banned user {user.username}")
        await message.reply(f"🔨 <b>User Banned</b>\n\n<b>Username:</b> {user.username}\n<b>ID:</b> <code>{user.id}</code>\n\nThey can no longer use the API or dashboard.")
    except Exception as exc:
        await message.reply(f"❌ <b>Error:</b> {html.escape(str(exc))}")

@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/unban &lt;username_or_id&gt;</code>")
        return

    target = parts[1].strip()
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        async with get_session() as session:
            stmt = select(User).where((User.username == target) | (User.id == target)).limit(1)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                await message.reply("❌ <b>User not found</b>")
                return

            if not user.is_banned:
                await message.reply("⚠️ <b>User is not banned.</b>")
                return

            user.is_banned = False
            
        await _log_admin_action(admin_name, "UNBAN_USER", user.id, f"Unbanned user {user.username}")
        await message.reply(f"🔓 <b>User Unbanned</b>\n\n<b>Username:</b> {user.username}\nAccess restored.")
    except Exception as exc:
        await message.reply(f"❌ <b>Error:</b> {html.escape(str(exc))}")

@router.message(Command("user"))
async def cmd_user(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/user &lt;username_or_id&gt;</code>")
        return

    target = parts[1].strip()

    try:
        async with get_session() as session:
            stmt = select(User).where((User.username == target) | (User.id == target)).limit(1)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                await message.reply("❌ <b>User not found</b>")
                return

            join_date = user.created_at.strftime("%Y-%m-%d") if user.created_at else "Unknown"
            status_text = "🔴 BANNED" if user.is_banned else "🟢 Active"

            text = (
                f"👤 <b>User Profile</b>\n\n"
                f"<b>Username:</b>  {user.username}\n"
                f"<b>User ID:</b>  <code>{user.id}</code>\n"
                f"<b>Status:</b>  {status_text}\n"
                f"<b>Join Date:</b>  {join_date}\n\n"
                f"<b>Default UPI:</b>  <code>{user.default_upi or 'Not Set'}</code>\n"
                f"<b>Total Txs:</b>  {user.total_transactions}\n"
                f"<b>Total INR Rs:</b>  ₹{user.total_inr_received:,.2f}"
            )
            await message.reply(text)

    except Exception as exc:
        await message.reply(f"❌ <b>Error:</b> {html.escape(str(exc))}")

@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    try:
        async with get_session() as session:
            count_res = await session.execute(select(func.count(User.id)))
            total_count = count_res.scalar_one()

            stmt = select(User).order_by(desc(User.created_at)).limit(50)
            res = await session.execute(stmt)
            users = res.scalars().all()

            if not users:
                await message.reply("No users found in database.")
                return

            lines = [
                "👥 <b>Platform Users</b>",
                f"Total Database Users: <b>{total_count}</b>\n"
            ]

            for u in users:
                status = "🔴" if u.is_banned else "🟢"
                uname = f"@{u.username}" if u.username else "Unknown"
                lines.append(f"{status} {uname} | Tx: {u.total_transactions} | <code>{u.id}</code>")

            if total_count > 50:
                lines.append("\n... <i>(showing 50 most recent users)</i>")

            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n... [Truncated by Telegram]"
                
            await message.reply(text)

    except Exception as exc:
        logger.error("Error in /users: %s", exc)
        await message.reply(f"❌ <b>Error:</b> {html.escape(str(exc))}")


# ── Advanced Queries ───────────────────────────────────────────

@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/history &lt;username_or_id&gt;</code>")
        return

    target = parts[1].strip()

    try:
        async with get_session() as session:
            stmt_u = select(User).where((User.username == target) | (User.id == target)).limit(1)
            result_u = await session.execute(stmt_u)
            user = result_u.scalar_one_or_none()

            if user is None:
                await message.reply("❌ <b>User not found</b>")
                return

            stmt_t = select(Transaction).where(Transaction.user_id == user.id).order_by(desc(Transaction.created_at)).limit(5)
            result_t = await session.execute(stmt_t)
            txs = result_t.scalars().all()

        if not txs:
            await message.reply(f"📚 <b>No transactions found for {user.username}</b>")
            return

        lines = [f"📚 <b>Recent History: {user.username}</b>\n"]
        for idx, tx in enumerate(txs, start=1):
            amt = tx.amount or 0.0
            inr = tx.inr_value or 0.0
            date_str = tx.created_at.strftime("%b %d, %H:%M UTC") if tx.created_at else "N/A"
            lines.append(f"{idx}. <b>{tx.status.value.upper()}</b> | {tx.chain.upper()}")
            lines.append(f"   <i>{date_str}</i>")
            lines.append(f"   Amount: {amt:,.4g} -> ₹{inr:,.2f}")
            lines.append(f"   TXID: <code>{tx.txid[-12:]}</code>\n")

        await message.reply("\n".join(lines))

    except Exception as exc:
        logger.exception("Error processing /history")
        await message.reply(f"❌ <b>Error fetching history:</b> {html.escape(str(exc))}")

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    try:
        hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        
        async with get_session() as session:
            stmt = select(
                func.count(Transaction.id),
                func.sum(Transaction.inr_value),
                func.sum(Transaction.usd_value)
            ).where(
                (Transaction.created_at >= hours_ago) & 
                (Transaction.status == TransactionStatus.PAID)
            )
            result = await session.execute(stmt)
            count, total_inr, total_usd = result.one()
            
            stmt_pend = select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.CONFIRMED)
            pend_res = await session.execute(stmt_pend)
            pending_count = pend_res.scalar_one()

        count = count or 0
        total_inr = total_inr or 0.0
        total_usd = total_usd or 0.0
        
        text = (
            "📈 <b>24-Hour Financial Stats</b>\n\n"
            f"<b>Paid Transactions:</b> {count}\n"
            f"<b>Volume Paid (INR):</b> ₹{total_inr:,.2f}\n"
            f"<b>Volume In (USD):</b> ${total_usd:,.2f}\n\n"
            f"<b>Pending Queue:</b> {pending_count} payouts waiting"
        )
        await message.reply(text)

    except Exception as exc:
        logger.exception("Error processing /stats")
        await message.reply(f"❌ <b>Error generating stats:</b> {html.escape(str(exc))}")


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    """List all confirmed but un-paid transactions."""
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.status == TransactionStatus.CONFIRMED).order_by(Transaction.created_at.asc()).limit(20)
            result = await session.execute(stmt)
            txs = result.scalars().all()

        if not txs:
            await message.reply("✅ <b>No pending payouts!</b> All confirmed transactions have been paid.")
            return

        lines = ["⏳ <b>Pending Payouts</b>\n"]
        for idx, tx in enumerate(txs, start=1):
            upi = tx.payout_destination or "Not Set"
            user = tx.user_id or "Unknown"
            amt = tx.inr_value or 0.0
            lines.append(f"{idx}. <b>User:</b> {user}")
            lines.append(f"   <b>UPI:</b> <code>{upi}</code>")
            lines.append(f"   <b>INR:</b> ₹{amt:,.2f}")
            lines.append(f"   <b>TXID:</b> <code>{tx.txid}</code>\n")

        if len(txs) == 20:
            lines.append("<i>... limited to oldest 20 records.</i>")

        await message.reply("\n".join(lines))
        logger.info("Admin %d checked /pending list", message.from_user.id)

    except Exception as exc:
        logger.exception("Error processing /pending list")
        await message.reply(f"❌ <b>Error fetching list:</b> {html.escape(str(exc))}")


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/info &lt;txid&gt;</code>")
        return

    txid = parts[1].strip()

    try:
        async with get_session() as session:
            stmt = select(Transaction).where(Transaction.txid == txid).limit(1)
            result = await session.execute(stmt)
            tx = result.scalar_one_or_none()

            if tx is None:
                await message.reply("❌ <b>Transaction not found</b>")
                return

            paid_str = tx.paid_at.strftime("%Y-%m-%d %H:%M:%S UTC") if tx.paid_at else "—"
            created_str = tx.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if tx.created_at else "—"

            text = (
                f"📋 <b>Transaction Details</b>\n\n"
                f"👤 <b>User ID:</b>  <code>{tx.user_id or 'N/A'}</code>\n"
                f"💳 <b>UPI ID:</b>  <code>{tx.payout_destination or 'N/A'}</code>\n"
                f"<b>Status:</b>  {tx.status.value.upper()}\n"
                f"<b>Chain:</b>  {tx.chain.upper()}\n"
                f"<b>Token:</b>  {(tx.token or 'Native').upper()}\n\n"
                f"<b>Amount:</b>  {tx.amount or 0:,.6g}\n"
                f"<b>USD:</b>  ${tx.usd_value or 0:,.2f}\n"
                f"<b>INR:</b>  ₹{tx.inr_value or 0:,.2f}\n\n"
                f"<b>TXID:</b>  <code>{tx.txid}</code>\n"
                f"<b>Reference:</b>  <code>{tx.reference}</code>\n"
                f"<b>Sender:</b>  <code>{tx.sender_address or '—'}</code>\n\n"
                f"<b>Created:</b>  {created_str}\n"
                f"<b>Paid at:</b>  {paid_str}"
            )

            await message.reply(text)

    except Exception as exc:
        logger.exception("Error processing /info for %s", txid)
        await message.reply(f"❌ <b>Error:</b> {html.escape(str(exc))}")


# ── System Overrides ───────────────────────────────────────────

@router.message(Command("maintenance"))
async def cmd_maintenance(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().lower().split(maxsplit=1)
    if len(parts) < 2 or parts[1] not in ["on", "off"]:
        current = await get_maintenance_mode()
        status_txt = "ON 🔴" if current else "OFF 🟢"
        await message.reply(f"⚠️ <b>Usage:</b>  <code>/maintenance on|off</code>\n\nCurrently: {status_txt}")
        return

    turn_on = parts[1] == "on"
    admin_name = message.from_user.username or str(message.from_user.id)

    try:
        await set_maintenance_mode(turn_on)
        state_txt = "ENABLED 🔴" if turn_on else "DISABLED 🟢"
        await message.reply(f"🛑 <b>Maintenance Mode: {state_txt}</b>\n\nUsers " + ("cannot" if turn_on else "can now") + " create new transactions.")
        await _log_admin_action(admin_name, "TOGGLE_MAINTENANCE", None, f"Turned {'ON' if turn_on else 'OFF'}")
    except RuntimeError as exc:
        await message.reply(f"❌ <b>Error setting maintenance mode:</b> {exc}")


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return
    await message.reply("🏓 <b>Pong!</b> Bot is working fine.")

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    current_rate = await get_current_inr_rate()
    maintenance = await get_maintenance_mode()

    text = (
        "📊 <b>System Status</b>\n\n"
        f"<b>Status:</b>  " + ("🔴 MAINTENANCE" if maintenance else "🟢 Online") + "\n"
        f"<b>Environment:</b>  {settings.ENVIRONMENT}\n"
        f"<b>INR Rate:</b>  ₹{current_rate:,.2f}\n"
        f"<b>Transactions Processed:</b>  {_tx_count:,}\n"
        f"<b>Supported Chains:</b>  {', '.join(c.upper() for c in settings.chains_list)}\n\n"
        f"<b>Server Time:</b>  {now}"
    )
    await message.reply(text)


@router.message(Command("setrate"))
async def cmd_setrate(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>Usage:</b>  <code>/setrate &lt;value&gt;</code>")
        return

    try:
        new_rate = float(parts[1].strip())
    except ValueError:
        await message.reply("❌ <b>Invalid number.</b>")
        return

    if new_rate <= 0:
        await message.reply("❌ Rate must be positive.")
        return

    old_rate = await get_current_inr_rate()

    try:
        await set_inr_rate(new_rate)
    except RuntimeError as exc:
        await message.reply(f"❌ <b>Failed to save rate:</b> {exc}")
        return

    await message.reply(f"✅ <b>INR Rate Updated</b>\n\n<b>Old:</b> ₹{old_rate:,.2f}\n<b>New:</b> ₹{new_rate:,.2f}")
    await _log_admin_action(
        message.from_user.username or str(message.from_user.id),
        "SET_RATE",
        note=f"INR rate changed from {old_rate:.2f} to {new_rate:.2f}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _reject(message)
        return

    text = (
        "📖 <b>Admin Commands</b>\n\n"
        "<b>Transactions:</b>\n"
        "/paid &lt;txid&gt; — Mark PAID\n"
        "/success &lt;txid&gt; — Mark CONFIRMED\n"
        "/fail &lt;txid&gt; — Mark FAILED\n"
        "/refund &lt;txid&gt; — Mark REFUNDED\n"
        "/revert &lt;txid&gt; — Revert to PENDING\n"
        "/delete &lt;txid&gt; — Delete from DB\n\n"
        "<b>Users:</b>\n"
        "/users — List all users\n"
        "/ban &lt;user&gt; — Ban a user\n"
        "/unban &lt;user&gt; — Unban a user\n"
        "/user &lt;user&gt; — View profile\n"
        "/history &lt;user&gt; — Recent txs\n\n"
        "<b>Queries:</b>\n"
        "/pending — List confirmed payouts\n"
        "/info &lt;txid&gt; — View tx details\n"
        "/stats — 24-hr financial volume\n\n"
        "<b>System:</b>\n"
        "/maintenance on|off — Toggle system lock\n"
        "/setrate &lt;value&gt; — Update INR conversion\n"
        "/status — System overview\n"
        "/ping — Check heartbeat"
    )
    await message.reply(text)


# ── Registration ────────────────────────────────────────────────

def register_admin_commands(dp: Dispatcher) -> None:
    global _registered
    if _registered:
        return
    dp.include_router(router)
    _registered = True
    logger.info("Advanced admin command handlers registered")
