"""
BITVORA EXCHANGE — Stats & Analytics Service
Mirrors the Telegram bot's services/stats.py.

Database-backed trading statistics tracker using Supabase instead of SQLite.
Calculates accurate lifetime, daily, and timing metrics.
"""

import logging
from datetime import datetime, timezone, timedelta
from database import get_supabase

logger = logging.getLogger("bitvora.stats")

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


def get_daily_stats() -> tuple[float, int]:
    """
    Returns (today_volume_inr, today_trade_count).
    Matches the old stats.py logic but adapted for INR and Supabase.
    """
    db = get_supabase()
    
    # Calculate start of today in UTC equivalent to midnight IST
    now_ist = datetime.now(IST)
    start_of_day_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day_utc = start_of_day_ist.astimezone(UTC).isoformat()
    
    res = (
        db.table("transactions")
        .select("amount_inr, id")
        .eq("status", "payout_sent")
        .gte("payout_sent_at", start_of_day_utc)
        .execute()
    )
    
    if not res.data:
        return 0.0, 0
        
    volume = sum(float(tx.get("amount_inr", 0)) for tx in res.data)
    trades = len(res.data)
    
    return volume, trades


def get_lifetime_stats() -> dict:
    """
    Returns complete analytics for professional admin panels.
    Matches the telegram bot /stats panel logic.
    """
    db = get_supabase()
    
    # Lifetime Volume & Trades
    res_all = (
        db.table("transactions")
        .select("amount_inr, id, created_at, payout_sent_at")
        .eq("status", "payout_sent")
        .execute()
    )
    
    lifetime_volume = 0.0
    lifetime_trades = 0
    total_minutes = 0
    valid_orders = 0
    last_trade_time = None
    
    # To compute average_deal_time accurately
    for tx in (res_all.data or []):
        inr = float(tx.get("amount_inr", 0))
        lifetime_volume += inr
        lifetime_trades += 1
        
        c = tx.get("created_at")
        p = tx.get("payout_sent_at")
        
        if p:
            try:
                p_dt = datetime.fromisoformat(p.replace("Z", "+00:00"))
                if not last_trade_time or p_dt > last_trade_time:
                    last_trade_time = p_dt
            except Exception:
                pass
                
        if c and p:
            try:
                c_dt = datetime.fromisoformat(c.replace("Z", "+00:00"))
                p_dt = datetime.fromisoformat(p.replace("Z", "+00:00"))
                total_minutes += int((p_dt - c_dt).total_seconds() / 60)
                valid_orders += 1
            except Exception:
                pass

    avg_time = int(total_minutes / valid_orders) if valid_orders > 0 else 0
    
    # Last trade timer
    last_trade_ago = "Never"
    if last_trade_time:
        now = datetime.now(UTC)
        diff = now - last_trade_time
        mins = int(diff.total_seconds() / 60)
        
        if mins < 60:
            last_trade_ago = f"{mins} minutes ago"
        elif mins < 1440:
            last_trade_ago = f"{mins // 60} hours ago"
        else:
            last_trade_ago = f"{mins // 1440} days ago"

    # Largest Trade Today
    now_ist = datetime.now(IST)
    start_of_day_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day_utc = start_of_day_ist.astimezone(UTC).isoformat()
    
    res_today = (
        db.table("transactions")
        .select("amount_inr")
        .eq("status", "payout_sent")
        .gte("payout_sent_at", start_of_day_utc)
        .execute()
    )
    
    largest_trade = 0.0
    if res_today.data:
        largest_trade = max(float(tx.get("amount_inr", 0)) for tx in res_today.data)
        
    return {
        "lifetime_volume": lifetime_volume,
        "lifetime_trades": lifetime_trades,
        "largest_trade_today": largest_trade,
        "average_deal_time": avg_time,
        "last_trade_ago": last_trade_ago
    }
