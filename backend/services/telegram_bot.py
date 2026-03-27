import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from config import settings
from database import get_supabase
from datetime import datetime, timezone

from utils.middleware import set_maintenance_mode, is_maintenance_mode

logger = logging.getLogger("bitvora.telegram")

bot = None
dp = Dispatcher()

if settings.TG_BOT_TOKEN:
    bot = Bot(token=settings.TG_BOT_TOKEN)

async def send_order_notification(tx: dict):
    if not bot or not settings.TG_CHAT_ID:
        return
        
    try:
        msg = (
            f"🚨 <b>NEW PAYOUT RECEIVED</b> 🚨\n\n"
            f"<b>User:</b> <code>{tx.get('username', 'N/A')}</code>\n"
            f"<b>Ref:</b> <code>{tx.get('reference')}</code>\n"
            f"<b>TXID:</b> <code>{tx.get('txid')}</code>\n"
            f"<b>Chain:</b> {tx.get('chain', '').upper()}\n"
            f"<b>Asset:</b> {tx.get('asset', '').upper()}\n"
            f"<b>Amount Crypto:</b> {tx.get('amount_crypto')}\n"
            f"<b>Amount INR:</b> ₹{tx.get('amount_inr', 0)}\n"
            f"<b>UPI/Payout:</b> <code>{tx.get('payout_destination')}</code>\n\n"
            f"To mark paid, reply with:\n"
            f"<code>/paid {tx.get('reference')}</code>\n\n"
            f"To reject, reply with:\n"
            f"<code>/reject {tx.get('reference')} [reason]</code>"
        )
        await bot.send_message(chat_id=settings.TG_CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send telegram notification: {e}")

@dp.message(Command("paid"))
async def cmd_paid(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("Usage: /paid <reference> [note]")
        return
        
    reference = args[1].strip()
    note = args[2].strip() if len(args) > 2 else None
    
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    
    tx_res = db.table("transactions").select("*").eq("reference", reference).execute()
    if not tx_res.data:
        await message.reply("Transaction not found.")
        return
        
    tx = tx_res.data[0]
    tx_id = tx["id"]
    
    if tx["status"] not in ("payout_queued", "verified"):
        await message.reply(f"Cannot mark paid. Transaction status is {tx['status']}.")
        return
        
    db.table("transactions").update({"status": "payout_sent", "payout_sent_at": now}).eq("id", tx_id).execute()
    db.table("payout_queue").update({"status": "completed", "processed_at": now, "admin_note": note}).eq("transaction_id", tx_id).execute()
    db.table("admin_log").insert({"admin_username": f"tg_{message.from_user.username}", "action": "mark_paid", "target_id": tx_id, "note": note}).execute()
    
    await message.reply(f"✅ Transaction <code>{reference}</code> marked as PAID successfully.", parse_mode="HTML")

@dp.message(Command("reject"))
async def cmd_reject(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Usage: /reject <reference> <reason>")
        return
        
    reference = args[1].strip()
    reason = args[2].strip()
    
    db = get_supabase()
    tx_res = db.table("transactions").select("*").eq("reference", reference).execute()
    if not tx_res.data:
        await message.reply("Transaction not found.")
        return
        
    tx = tx_res.data[0]
    tx_id = tx["id"]
    
    db.table("transactions").update({"status": "failed", "error_message": reason}).eq("id", tx_id).execute()
    db.table("payout_queue").update({"status": "failed", "admin_note": reason}).eq("transaction_id", tx_id).execute()
    db.table("admin_log").insert({"admin_username": f"tg_{message.from_user.username}", "action": "reject", "target_id": tx_id, "note": reason}).execute()
    
    await message.reply(f"❌ Transaction <code>{reference}</code> rejected.", parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    db = get_supabase()
    today = datetime.now(timezone.utc).date().isoformat()
    
    res = db.table("transactions").select("status, amount_inr").gte("created_at", today).execute()
    
    stats = {"total_vol": 0, "successful": 0, "pending": 0, "failed": 0}
    for tx in res.data:
        if tx["status"] == "payout_sent":
            stats["total_vol"] += tx.get("amount_inr", 0)
            stats["successful"] += 1
        elif tx["status"] in ("pending", "verifying", "verified", "payout_queued"):
            stats["pending"] += 1
        elif tx["status"] == "failed":
            stats["failed"] += 1
            
    msg = (
        f"📊 <b>DAILY STATS ({today})</b>\n\n"
        f"💰 <b>Volume:</b> ₹{stats['total_vol']:,.2f}\n"
        f"✅ <b>Successful:</b> {stats['successful']}\n"
        f"⏳ <b>Pending:</b> {stats['pending']}\n"
        f"❌ <b>Rejected:</b> {stats['failed']}\n"
    )
    await message.reply(msg, parse_mode="HTML")

@dp.message(Command("pending"))
async def cmd_pending(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    db = get_supabase()
    res = db.table("transactions").select("reference, asset, amount_crypto, amount_inr").in_("status", ["verified", "payout_queued"]).order("created_at", desc=True).limit(10).execute()
    
    if not res.data:
        await message.reply("No pending payouts at the moment! 🥳")
        return
        
    lines = ["⏳ <b>PENDING PAYOUTS</b>\n"]
    for tx in res.data:
        lines.append(f"• <code>{tx['reference']}</code> | {tx['asset']} | ₹{tx.get('amount_inr', 0):,}")
        
    await message.reply("\n".join(lines), parse_mode="HTML")

@dp.message(Command("find"))
async def cmd_find(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    q = message.text.split(maxsplit=1)
    if len(q) < 2:
        await message.reply("Usage: /find <ref_or_txid>")
        return
        
    db = get_supabase()
    term = q[1].strip()
    res = db.table("transactions").select("*").or_(f"reference.eq.{term},txid.eq.{term}").execute()
    
    if not res.data:
        await message.reply("No transaction found for that identifier.")
        return
        
    tx = res.data[0]
    msg = (
        f"🔍 <b>TX DATA</b>\n\n"
        f"<b>Ref:</b> <code>{tx['reference']}</code>\n"
        f"<b>Status:</b> <code>{tx['status'].upper()}</code>\n"
        f"<b>User ID:</b> <code>{tx['user_id']}</code>\n"
        f"<b>Payer UPI:</b> <code>{tx.get('payout_destination', 'N/A')}</code>\n"
        f"<b>Amount Crypto:</b> {tx['amount_crypto']} {tx['asset']}\n"
        f"<b>Amount INR:</b> ₹{tx.get('amount_inr', 0):,}\n"
        f"<b>Created:</b> {tx['created_at']}\n"
    )
    await message.reply(msg, parse_mode="HTML")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("Usage: /ban <username> [reason]")
        return
        
    username = args[1].strip().lower()
    reason = args[2].strip() if len(args) > 2 else "Violated terms"
    
    db = get_supabase()
    res = db.table("users").update({"is_banned": True}).eq("username", username).execute()
    
    if not res.data:
        await message.reply("User not found.")
        return
        
    await message.reply(f"🚫 User <b>{username}</b> has been BANNED.\nReason: {reason}", parse_mode="HTML")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Usage: /unban <username>")
        return
        
    username = args[1].strip().lower()
    db = get_supabase()
    res = db.table("users").update({"is_banned": False}).eq("username", username).execute()
    
    if not res.data:
        await message.reply("User not found.")
        return
        
    await message.reply(f"✅ User <b>{username}</b> has been UNBANNED.", parse_mode="HTML")

@dp.message(Command("maintenance"))
async def cmd_mt(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    args = message.text.split()
    if len(args) < 2:
        mode = "ON" if is_maintenance_mode() else "OFF"
        await message.reply(f"Maintenance mode is currently <b>{mode}</b>.\nUse: <code>/maintenance on</code> or <code>/maintenance off</code>", parse_mode="HTML")
        return
        
    state = args[1].lower() == "on"
    set_maintenance_mode(state)
    await message.reply(f"⚙️ Maintenance mode <b>{'ENABLED' if state else 'DISABLED'}</b>.", parse_mode="HTML")

@dp.message(Command("setperusd"))
async def cmd_setperusd(message: Message):
    if str(message.from_user.id) not in settings.admin_ids_list:
        return
        
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Usage: /setperusd <rate>")
        return
        
    try:
        rate = float(args[1])
        if rate <= 0: raise ValueError()
    except ValueError:
        await message.reply("Invalid rate.")
        return
        
    db = get_supabase()
    db.table("exchange_rates").upsert({"asset": "USD", "rate_inr": rate, "source": "admin", "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="asset").execute()
    await message.reply(f"✅ USD Rate updated to <b>₹{rate}</b>.", parse_mode="HTML")

async def telegram_worker():
    if not bot:
        logger.warning("Telegram bot token not provided. Worker exiting.")
        return
    logger.info("Telegram bot worker polling started.")
    try:
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        logger.info("Telegram worker cancelled via shutdown.")
    finally:
        if bot.session:
            await bot.session.close()
