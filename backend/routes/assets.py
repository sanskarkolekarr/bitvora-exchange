"""
BITVORA EXCHANGE — Assets Routes
Public endpoints for chain info and exchange rates.
"""

from fastapi import APIRouter
from database import get_supabase
from config import settings

router = APIRouter(prefix="/assets", tags=["Assets"])


@router.get("/chains")
async def get_chains():
    """Returns all supported chains with their deposit addresses and token lists."""
    chains = []
    for chain, address in settings.deposit_addresses.items():
        if not address:
            continue
        chains.append(
            {
                "chain": chain,
                "deposit_address": address,
                "tokens": settings.supported_assets.get(chain, []),
                "required_confirmations": settings.confirmation_thresholds.get(
                    chain, 1
                ),
                "explorer_base": settings.explorer_base_urls.get(chain, ""),
            }
        )
    return {"chains": chains}


@router.get("/rates")
async def get_rates():
    """Returns current INR exchange rates for all supported assets."""
    db = get_supabase()
    result = db.table("exchange_rates").select("*").execute()

    rates = {}
    for row in result.data:
        rates[row["asset"]] = {
            "rate_inr": row["rate_inr"],
            "source": row["source"],
            "updated_at": row["updated_at"],
        }

    return {"rates": rates}

@router.get("/settings")
async def get_settings():
    db = get_supabase()
    try:
        result = db.table("settings").select("*").execute()
        settings_dict = {row["key"]: row["value"] for row in result.data}
        return {"settings": settings_dict}
    except Exception:
        return {"settings": {}}


@router.get("/platform-config")
async def get_public_platform_config():
    """Public endpoint: returns safe platform config for the frontend."""
    from services.settings_manager import (
        get_platform_fee, get_min_transaction_usd,
        get_max_transaction_usd, get_setting
    )
    return {
        "platform_fee_pct": get_platform_fee(),
        "platform_fee_display": f"{get_platform_fee() * 100:.2f}%",
        "min_transaction_usd": get_min_transaction_usd(),
        "max_transaction_usd": get_max_transaction_usd(),
        "announcement": get_setting("announcement"),
        "announcement_active": get_setting("announcement_active", "false"),
        "support_email": get_setting("support_email"),
        "support_telegram": get_setting("support_telegram"),
    }


@router.get("/status")
async def get_platform_status():
    """Public: returns current maintenance state."""
    from utils.middleware import is_maintenance_mode
    return {"maintenance": is_maintenance_mode()}


@router.get("/recent-payouts")
async def get_recent_payouts():
    """Public: returns last 10 anonymized completed payouts."""
    db = get_supabase()
    try:
        result = (
            db.table("transactions")
            .select("asset, chain, amount_inr, payout_sent_at")
            .eq("status", "payout_sent")
            .order("payout_sent_at", desc=True)
            .limit(15)
            .execute()
        )
        payouts = [
            {
                "asset": row["asset"],
                "chain": row["chain"],
                "amount_inr": row["amount_inr"],
                "payout_sent_at": row["payout_sent_at"],
            }
            for row in result.data
            if row.get("payout_sent_at") and row.get("amount_inr")
        ]
        return {"payouts": payouts}
    except Exception as e:
        return {"payouts": []}
@router.get("/live-counter")
async def get_live_counter():
    """Returns a deterministic randomized count based on a 10-minute window."""
    db = get_supabase()
    try:
        # Get settings from DB
        result = db.table("settings").select("*").in_("key", ["counter_min", "counter_max"]).execute()
        settings_dict = {row["key"]: int(row["value"]) for row in result.data}
        
        c_min = settings_dict.get("counter_min", 1250000)
        c_max = settings_dict.get("counter_max", 1500000)
        
        import time
        import hashlib
        # Use current 10-minute block as seed
        window = int(time.time() / 600)
        seed_str = f"bitvora_counter_{window}"
        seed_hash = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16)
        
        # Calculate deterministic value in range
        count = c_min + (seed_hash % (c_max - c_min + 1))
        
        return {"count": count}
    except Exception:
        return {"count": 0}
