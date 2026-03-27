"""
BITVORA EXCHANGE — Transaction Routes
Submit, quote, deposit address.
"""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends, Query
from models.transaction import (
    TransactionSubmitRequest,
    TransactionSubmitResponse,
    TransactionQuoteResponse,
    DepositAddressResponse,
)
from utils.security import get_current_user
from utils.txid_ledger import is_txid_processed, register_txid
from database import get_supabase
from config import settings
from services.price_manager import get_cached_rate
from services.settings_manager import get_platform_fee, get_min_transaction_usd, get_max_transaction_usd

logger = logging.getLogger("bitvora.routes.transaction")
router = APIRouter(prefix="/transaction", tags=["Transactions"])


@router.post("/submit", response_model=TransactionSubmitResponse)
async def submit_transaction(
    body: TransactionSubmitRequest, user: dict = Depends(get_current_user)
):
    db = get_supabase()
    chain = body.chain.lower()
    asset = body.asset.upper()
    txid = body.txid.strip().lower()

    # --- Validation Cascade ---

    # 1. Chain supported?
    if chain not in settings.deposit_addresses:
        raise HTTPException(status_code=400, detail="Unsupported chain")

    # 2. Asset supported on chain?
    chain_assets = settings.supported_assets.get(chain, [])
    if asset not in chain_assets:
        raise HTTPException(
            status_code=400, detail=f"{asset} is not supported on {chain}"
        )

    # 3. Pending transaction limit
    pending = (
        db.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user["id"])
        .in_("status", ["pending", "pending_retry", "verifying", "verified", "payout_queued"])
        .execute()
    )
    if pending.count and pending.count >= settings.MAX_PENDING_TRANSACTIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail="Maximum pending transactions reached. Complete or wait for existing ones.",
        )

    # 4. TXID uniqueness — ledger first
    if await is_txid_processed(txid):
        raise HTTPException(
            status_code=409, detail="This transaction ID has already been submitted"
        )

    # 5. TXID uniqueness — transactions table
    existing_tx = (
        db.table("transactions").select("id").eq("txid", txid).execute()
    )
    if existing_tx.data:
        raise HTTPException(
            status_code=409, detail="This transaction ID has already been submitted"
        )

    # --- Build Transaction ---
    reference = f"TXN_{uuid.uuid4().hex[:12].upper()}"
    deposit_address = settings.deposit_addresses[chain]
    required_confs = settings.confirmation_thresholds[chain]
    explorer_url = f"{settings.explorer_base_urls[chain]}{body.txid.strip()}"

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=30)

    tx_id = str(uuid.uuid4())

    tx_row = {
        "id": tx_id,
        "reference": reference,
        "user_id": user["id"],
        "chain": chain,
        "asset": asset,
        "txid": txid,
        "amount_crypto": body.amount,
        "deposit_address": deposit_address,
        "payout_destination": body.payout_destination or user.get("default_upi"),
        "status": "pending",
        "required_confirmations": required_confs,
        "explorer_url": explorer_url,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }

    # Attach exchange rate if available
    rate = get_cached_rate(asset)
    if rate:
        fee_pct = get_platform_fee()  # dynamic — set via admin panel
        gross_inr = body.amount * rate
        fee_inr = gross_inr * fee_pct
        net_inr = gross_inr - fee_inr
        tx_row["exchange_rate"] = rate
        tx_row["platform_fee_pct"] = fee_pct
        tx_row["platform_fee_inr"] = round(fee_inr, 2)
        tx_row["amount_inr"] = round(net_inr, 2)

    try:
        db.table("transactions").insert(tx_row).execute()
        await register_txid(txid, chain, tx_id)
    except Exception as e:
        logger.error(f"Transaction insert failed: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to submit transaction. Please try again."
        )

    logger.info(f"Transaction {reference} submitted by user {user['username']}")

    return TransactionSubmitResponse(
        reference=reference,
        exchange_rate=tx_row.get("exchange_rate"),
        amount_inr=tx_row.get("amount_inr"),
    )


@router.get("/quote", response_model=TransactionQuoteResponse)
async def get_quote(
    chain: str = Query(...),
    asset: str = Query(...),
    amount: float = Query(..., gt=0),
):
    chain = chain.lower()
    asset = asset.upper()

    if chain not in settings.deposit_addresses:
        raise HTTPException(status_code=400, detail="Unsupported chain")

    chain_assets = settings.supported_assets.get(chain, [])
    if asset not in chain_assets:
        raise HTTPException(
            status_code=400, detail=f"{asset} is not supported on {chain}"
        )

    rate = get_cached_rate(asset)
    if not rate:
        raise HTTPException(
            status_code=503, detail="Exchange rates temporarily unavailable"
        )

    fee_pct = get_platform_fee()  # dynamic — set via admin panel
    gross_inr = amount * rate
    fee_inr = gross_inr * fee_pct
    net_inr = gross_inr - fee_inr

    return TransactionQuoteResponse(
        chain=chain,
        asset=asset,
        amount_crypto=amount,
        exchange_rate=rate,
        platform_fee_pct=fee_pct,
        platform_fee_inr=round(fee_inr, 2),
        amount_inr=round(net_inr, 2),
        deposit_address=settings.deposit_addresses[chain],
    )


@router.get("/deposit-address/{chain}", response_model=DepositAddressResponse)
async def get_deposit_address(chain: str):
    chain = chain.lower()
    if chain not in settings.deposit_addresses:
        raise HTTPException(status_code=400, detail="Unsupported chain")

    return DepositAddressResponse(
        chain=chain,
        address=settings.deposit_addresses[chain],
    )


@router.get("/history")
async def get_history(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    db = get_supabase()
    offset = (page - 1) * limit

    result = (
        db.table("transactions")
        .select("*", count="exact")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "transactions": result.data,
        "total": result.count,
        "page": page,
        "limit": limit,
    }
