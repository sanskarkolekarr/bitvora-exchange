"""
BITVORA EXCHANGE — Admin Routes
All controls connected to DB and frontend.
Protected by ADMIN_SECRET_KEY — completely separate from user JWTs.
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Any
from models.payout import (
    PayoutQueueItem,
    MarkPaidRequest,
    RejectRequest,
    AdminStatsResponse,
)
from utils.security import verify_admin
from utils.middleware import set_maintenance_mode, is_maintenance_mode
from database import get_supabase

logger = logging.getLogger("bitvora.routes.admin")
router = APIRouter(prefix="/admin", tags=["Admin"])


def _log_action(admin: str, action: str, target_id: str = None, note: str = None):
    """Append to admin_log table."""
    try:
        db = get_supabase()
        db.table("admin_log").insert({
            "admin_username": admin,
            "action": action,
            "target_id": target_id,
            "note": note,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to log admin action: {e}")


# ════════════════════════════════════════════════
# Payout Queue
# ════════════════════════════════════════════════

@router.get("/payout-queue")
async def get_payout_queue(admin: str = Depends(verify_admin)):
    db = get_supabase()
    queue = (
        db.table("payout_queue")
        .select("*, transactions(*)")
        .eq("status", "pending")
        .order("queued_at", desc=False)
        .execute()
    )
    items = []
    for row in queue.data:
        tx = row.get("transactions", {})
        items.append({
            "id": row["id"],
            "transaction_id": row["transaction_id"],
            "chain": tx.get("chain", ""),
            "asset": tx.get("asset", ""),
            "txid": tx.get("txid", ""),
            "amount_inr": row["amount_inr"],
            "payout_destination": row["payout_destination"],
            "status": row["status"],
            "explorer_url": tx.get("explorer_url"),
            "queued_at": row["queued_at"],
        })
    return {"queue": items, "count": len(items)}


@router.post("/mark-paid/{transaction_id}")
async def mark_paid(
    transaction_id: str,
    body: MarkPaidRequest = None,
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    tx_result = db.table("transactions").select("*").eq("id", transaction_id).execute()
    if not tx_result.data:
        raise HTTPException(status_code=404, detail="Not found")

    tx = tx_result.data[0]
    if tx["status"] not in ("payout_queued", "verified"):
        raise HTTPException(status_code=400, detail="Transaction is not in payout queue")

    db.table("transactions").update(
        {"status": "payout_sent", "payout_sent_at": now}
    ).eq("id", transaction_id).execute()

    db.table("payout_queue").update({
        "status": "completed",
        "processed_at": now,
        "admin_note": body.admin_note if body else None,
    }).eq("transaction_id", transaction_id).execute()

    # Update user stats
    user_result = db.table("users").select("total_inr_received, total_transactions").eq("id", tx["user_id"]).execute()
    if user_result.data:
        u = user_result.data[0]
        db.table("users").update({
            "total_inr_received": float(u.get("total_inr_received", 0)) + float(tx.get("amount_inr", 0)),
            "total_transactions": int(u.get("total_transactions", 0)) + 1,
        }).eq("id", tx["user_id"]).execute()

    _log_action(admin, "mark_paid", transaction_id, body.admin_note if body else None)
    logger.info(f"Admin marked {transaction_id} as paid")
    return {"message": "Transaction marked as paid", "reference": tx["reference"]}


@router.post("/reject/{transaction_id}")
async def reject_transaction(
    transaction_id: str,
    body: RejectRequest,
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    tx_result = db.table("transactions").select("*").eq("id", transaction_id).execute()
    if not tx_result.data:
        raise HTTPException(status_code=404, detail="Not found")

    db.table("transactions").update(
        {"status": "failed", "error_message": body.reason}
    ).eq("id", transaction_id).execute()

    db.table("payout_queue").update(
        {"status": "failed", "admin_note": body.reason}
    ).eq("transaction_id", transaction_id).execute()

    _log_action(admin, "reject", transaction_id, body.reason)
    return {"message": "Transaction rejected"}


# ════════════════════════════════════════════════
# Transaction & User Management
# ════════════════════════════════════════════════

@router.get("/transactions")
async def list_transactions(
    status: Optional[str] = Query(None),
    chain: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    query = db.table("transactions").select("*", count="exact")
    if status:
        query = query.eq("status", status)
    if chain:
        query = query.eq("chain", chain.lower())
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"transactions": result.data, "total": result.count, "limit": limit, "offset": offset}


@router.get("/users")
async def list_users(
    is_banned: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    query = db.table("users").select("*", count="exact")
    if is_banned is not None:
        query = query.eq("is_banned", is_banned)
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"users": result.data, "total": result.count}


@router.post("/ban/{user_id}")
async def ban_user(user_id: str, admin: str = Depends(verify_admin)):
    db = get_supabase()
    user_result = db.table("users").select("id").eq("id", user_id).execute()
    if not user_result.data:
        raise HTTPException(status_code=404, detail="Not found")
    db.table("users").update({"is_banned": True}).eq("id", user_id).execute()
    _log_action(admin, "ban_user", user_id)
    return {"message": "User banned"}


@router.post("/unban/{user_id}")
async def unban_user(user_id: str, admin: str = Depends(verify_admin)):
    db = get_supabase()
    db.table("users").update({"is_banned": False}).eq("id", user_id).execute()
    _log_action(admin, "unban_user", user_id)
    return {"message": "User unbanned"}


# ════════════════════════════════════════════════
# Support Tickets
# ════════════════════════════════════════════════

class SupportTicketUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None


@router.get("/support-tickets")
async def get_support_tickets(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    query = db.table("support_tickets").select("*", count="exact")
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"tickets": result.data, "total": result.count}


@router.post("/support-tickets/{ticket_id}/update")
async def update_support_ticket(
    ticket_id: str,
    req: SupportTicketUpdate,
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    ticket_res = db.table("support_tickets").select("*").eq("id", ticket_id).execute()
    if not ticket_res.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    update_data: dict = {"status": req.status}
    if req.admin_note is not None:
        update_data["admin_note"] = req.admin_note
    if req.status in ("resolved", "closed"):
        update_data["resolved_at"] = datetime.utcnow().isoformat()
    result = db.table("support_tickets").update(update_data).eq("id", ticket_id).execute()
    _log_action(admin, "update_support_ticket", ticket_id, f"status: {req.status}")
    return {"status": "success", "ticket": result.data[0] if result.data else {}}


# ════════════════════════════════════════════════
# Stats Dashboard
# ════════════════════════════════════════════════

@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(admin: str = Depends(verify_admin)):
    db = get_supabase()
    all_tx = db.table("transactions").select(
        "status, amount_inr, platform_fee_inr, created_at, payout_sent_at"
    ).execute()

    stats = {
        "total_volume_inr": 0.0,
        "total_transactions": 0,
        "pending_count": 0,
        "verifying_count": 0,
        "verified_count": 0,
        "payout_queued_count": 0,
        "payout_sent_count": 0,
        "failed_count": 0,
        "expired_count": 0,
        "total_fees_collected": 0.0,
    }
    processing_times = []

    for tx in all_tx.data:
        stats["total_transactions"] += 1
        s = tx.get("status", "")
        key = f"{s}_count"
        if key in stats:
            stats[key] += 1
        inr = float(tx.get("amount_inr") or 0)
        fee = float(tx.get("platform_fee_inr") or 0)
        if s == "payout_sent":
            stats["total_volume_inr"] += inr
            stats["total_fees_collected"] += fee
            created = tx.get("created_at")
            sent = tx.get("payout_sent_at")
            if created and sent:
                try:
                    c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    s2 = datetime.fromisoformat(sent.replace("Z", "+00:00"))
                    processing_times.append((s2 - c).total_seconds() / 60)
                except Exception:
                    pass

    stats["total_volume_inr"] = round(stats["total_volume_inr"], 2)
    stats["total_fees_collected"] = round(stats["total_fees_collected"], 2)
    if processing_times:
        stats["average_processing_minutes"] = round(sum(processing_times) / len(processing_times), 1)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_today_res = (
        db.table("transactions")
        .select("amount_inr")
        .eq("status", "payout_sent")
        .gte("payout_sent_at", today_str)
        .execute()
    )
    stats["sent_today"] = len(sent_today_res.data)
    stats["volume_today"] = round(
        sum(float(r.get("amount_inr") or 0) for r in sent_today_res.data), 2
    )

    from services.stats import get_lifetime_stats
    advanced_stats = get_lifetime_stats()
    stats["largest_trade_today"] = advanced_stats["largest_trade_today"]
    stats["last_trade_ago"] = advanced_stats["last_trade_ago"]
    stats["average_deal_time"] = advanced_stats["average_deal_time"]

    return AdminStatsResponse(**stats)


@router.get("/analytics")
async def get_analytics(days: int = Query(30, ge=1, le=90), admin: str = Depends(verify_admin)):
    from datetime import timedelta
    db = get_supabase()
    now_dt = datetime.now(timezone.utc)
    start_dt = now_dt - timedelta(days=days)
    start_str = start_dt.isoformat()

    tx_res = db.table("transactions").select(
        "created_at, amount_inr, platform_fee_inr, asset, status"
    ).gte("created_at", start_str).execute()

    user_res = db.table("users").select("created_at").gte("created_at", start_str).execute()

    daily_volume = {}
    daily_fees = {}
    daily_txs = {}
    daily_users = {}
    asset_volume = {}

    for i in range(days + 1):
        d = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        daily_volume[d] = 0.0
        daily_fees[d] = 0.0
        daily_txs[d] = 0
        daily_users[d] = 0

    for tx in (tx_res.data or []):
        date_str = tx.get("created_at", "")[:10]
        if not date_str or date_str not in daily_volume:
            continue
            
        inr = float(tx.get("amount_inr") or 0)
        fee = float(tx.get("platform_fee_inr") or 0)
        a = tx.get("asset", "UNK").upper()
        
        daily_txs[date_str] += 1
        
        if tx.get("status") in ("checked", "verified", "payout_queued", "payout_sent"):
            daily_volume[date_str] += inr
            daily_fees[date_str] += fee
            asset_volume[a] = asset_volume.get(a, 0) + inr

    for u in (user_res.data or []):
        date_str = u.get("created_at", "")[:10]
        if date_str in daily_users:
            daily_users[date_str] += 1

    chart_labels = sorted(daily_volume.keys())

    return {
        "chart_labels": chart_labels,
        "daily_volume": [round(daily_volume[l], 2) for l in chart_labels],
        "daily_fees": [round(daily_fees[l], 2) for l in chart_labels],
        "daily_txs": [daily_txs[l] for l in chart_labels],
        "daily_users": [daily_users[l] for l in chart_labels],
        "assets": list(asset_volume.keys()),
        "asset_volume": [round(v, 2) for v in asset_volume.values()]
    }



# ════════════════════════════════════════════════
# Maintenance
# ════════════════════════════════════════════════

@router.post("/maintenance/{mode}")
async def toggle_maintenance(mode: str, admin: str = Depends(verify_admin)):
    if mode == "on":
        set_maintenance_mode(True)
        _log_action(admin, "maintenance_on")
        return {"message": "Maintenance mode enabled"}
    elif mode == "off":
        set_maintenance_mode(False)
        _log_action(admin, "maintenance_off")
        return {"message": "Maintenance mode disabled"}
    else:
        raise HTTPException(status_code=400, detail="Use /maintenance/on or /maintenance/off")


# ════════════════════════════════════════════════
# Exchange Rate Override
# ════════════════════════════════════════════════

class SetRateRequest(BaseModel):
    asset: str = "USD"
    rate: float


@router.post("/rate")
async def set_asset_rate(req: SetRateRequest, admin: str = Depends(verify_admin)):
    """Manually set INR rate for any asset, overriding CoinGecko."""
    if req.rate <= 0:
        raise HTTPException(status_code=400, detail="Rate must be positive")
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    db.table("exchange_rates").upsert({
        "asset": req.asset.upper(),
        "rate_inr": req.rate,
        "source": "admin_override",
        "updated_at": now,
    }, on_conflict="asset").execute()
    _log_action(admin, "set_asset_rate", note=f"{req.asset.upper()} → INR {req.rate}")
    return {"message": f"{req.asset.upper()} rate set to INR {req.rate}"}


# ════════════════════════════════════════════════
# Platform Config — All Controls
# ════════════════════════════════════════════════

class PlatformConfigRequest(BaseModel):
    # Fee
    platform_fee_pct: Optional[float] = None        # 0.015 = 1.5%
    # Transaction limits (USD equivalent)
    min_transaction_usd: Optional[float] = None
    max_transaction_usd: Optional[float] = None
    # Homepage stats display override
    stat_volume: Optional[str] = None
    stat_time: Optional[str] = None
    stat_assets: Optional[str] = None
    # Live counter range
    counter_min: Optional[int] = None
    counter_max: Optional[int] = None
    # Contact / support links
    support_email: Optional[str] = None
    support_telegram: Optional[str] = None
    # Announcement banner
    announcement: Optional[str] = None
    announcement_active: Optional[str] = None       # "true" / "false"


@router.get("/platform-config")
async def get_platform_config(admin: str = Depends(verify_admin)):
    """Get ALL platform settings + live exchange rates in one call."""
    db = get_supabase()
    settings_result = db.table("settings").select("*").execute()
    config = {row["key"]: row["value"] for row in (settings_result.data or [])}

    rates_result = db.table("exchange_rates").select("*").execute()
    rates = {
        row["asset"]: {
            "rate_inr": float(row["rate_inr"]),
            "source": row.get("source", "coingecko"),
            "updated_at": row.get("updated_at"),
        }
        for row in (rates_result.data or [])
    }
    return {"settings": config, "rates": rates}


@router.post("/platform-config")
async def update_platform_config(req: PlatformConfigRequest, admin: str = Depends(verify_admin)):
    """Bulk-update any platform setting. Only provided (non-None) fields are changed."""
    from services.settings_manager import flush_cache, update_setting_in_cache

    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    updated_keys = []

    def _upsert(key: str, value: str):
        db.table("settings").upsert(
            {"key": key, "value": value, "updated_at": now}, on_conflict="key"
        ).execute()
        update_setting_in_cache(key, value)
        updated_keys.append(key)

    if req.platform_fee_pct is not None:
        if req.platform_fee_pct < 0 or req.platform_fee_pct > 0.5:
            raise HTTPException(status_code=400, detail="Fee must be between 0% and 50%")
        _upsert("platform_fee_pct", str(req.platform_fee_pct))

    if req.min_transaction_usd is not None:
        _upsert("min_transaction_usd", str(req.min_transaction_usd))
    if req.max_transaction_usd is not None:
        _upsert("max_transaction_usd", str(req.max_transaction_usd))
    if req.stat_volume is not None:
        _upsert("stat_volume", req.stat_volume)
    if req.stat_time is not None:
        _upsert("stat_time", req.stat_time)
    if req.stat_assets is not None:
        _upsert("stat_assets", req.stat_assets)
    if req.counter_min is not None:
        _upsert("counter_min", str(req.counter_min))
    if req.counter_max is not None:
        _upsert("counter_max", str(req.counter_max))
    if req.support_email is not None:
        _upsert("support_email", req.support_email)
    if req.support_telegram is not None:
        _upsert("support_telegram", req.support_telegram)
    if req.announcement is not None:
        _upsert("announcement", req.announcement)
    if req.announcement_active is not None:
        _upsert("announcement_active", req.announcement_active)

    flush_cache()
    _log_action(admin, "update_platform_config", note=f"Changed: {', '.join(updated_keys)}")
    return {"message": "Config updated", "updated": updated_keys}


# ════════════════════════════════════════════════
# Deposit Address Management
# ════════════════════════════════════════════════

class DepositAddressRequest(BaseModel):
    chain: str
    address: str


@router.get("/deposit-addresses")
async def list_deposit_addresses(admin: str = Depends(verify_admin)):
    """All deposit addresses — DB entry takes priority over .env."""
    from config import settings as cfg
    db = get_supabase()
    db_result = db.table("deposit_addresses").select("*").execute()
    db_addrs = {row["chain"]: row for row in (db_result.data or [])}

    result = []
    for chain, env_addr in cfg.deposit_addresses.items():
        db_entry = db_addrs.get(chain)
        result.append({
            "chain": chain,
            "address": db_entry["address"] if db_entry else env_addr,
            "source": "database" if db_entry else "env",
            "is_active": db_entry.get("is_active", True) if db_entry else bool(env_addr),
            "updated_at": db_entry.get("updated_at") if db_entry else None,
        })
    return {"addresses": result}


@router.post("/deposit-address")
async def update_deposit_address(req: DepositAddressRequest, admin: str = Depends(verify_admin)):
    """Update deposit address for a chain in DB (overrides .env config)."""
    from config import settings as cfg
    chain = req.chain.lower()
    if chain not in cfg.deposit_addresses:
        raise HTTPException(status_code=400, detail=f"Unknown chain: {chain}")
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    db.table("deposit_addresses").upsert({
        "chain": chain, "address": req.address,
        "is_active": True, "updated_at": now,
    }, on_conflict="chain").execute()
    _log_action(admin, "update_deposit_address", note=f"{chain} → {req.address[:24]}...")
    return {"message": f"Deposit address for {chain} updated"}


# ════════════════════════════════════════════════
# Admin Log
# ════════════════════════════════════════════════

@router.get("/logs")
async def list_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: str = Depends(verify_admin),
):
    db = get_supabase()
    result = (
        db.table("admin_log")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"logs": result.data, "total": result.count}


# ════════════════════════════════════════════════
# Legacy /settings (backwards compat)
# ════════════════════════════════════════════════

class UpdateSettingsRequest(BaseModel):
    stat_volume: Optional[str] = None
    stat_time: Optional[str] = None
    stat_assets: Optional[str] = None
    counter_min: Optional[int] = None
    counter_max: Optional[int] = None


@router.post("/settings")
async def update_settings_legacy(req: UpdateSettingsRequest, admin: str = Depends(verify_admin)):
    """Legacy endpoint — maps to /admin/platform-config."""
    pc = PlatformConfigRequest(
        stat_volume=req.stat_volume, stat_time=req.stat_time,
        stat_assets=req.stat_assets, counter_min=req.counter_min,
        counter_max=req.counter_max,
    )
    return await update_platform_config(pc, admin)
