"""
Transaction API endpoints.
Handles quote, deposit addresses, submission, and history.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import uuid
from datetime import datetime, timezone
import string
import random

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.core.config import settings
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.redis import enqueue_tx
from app.core.security import (
    check_duplicate_txid,
    rate_limiter,
    validate_txid_format,
)
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.schemas.transaction import VerifyRequest, VerifyResponse
from app.utils.security import get_current_user
from app.services.settings import get_inr_rate, get_maintenance_mode
from typing import Optional

logger = get_logger("api.transaction")
router = APIRouter(prefix="/transaction", tags=["transaction"])

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"

def _generate_reference() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

@router.get("/deposit-address/{chain}")
async def get_deposit_address_endpoint(chain: str):
    from app.services.settings import get_deposit_address
    addr = await get_deposit_address(chain)
    if not addr or addr == "MISSING_ADDRESS":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deposit address for {chain} not configured."
        )
    return {"chain": chain.lower(), "address": addr}

@router.get("/quote")
async def get_quote(chain: str, asset: str, amount: float):
    # Get live rate from DB
    rate = await get_inr_rate()
    gross_inr = amount * rate
    fee_percentage = 0.0
    fee_inr = 0.0
    net_inr = gross_inr
    
    return {
        "amount_crypto": amount,
        "asset": asset,
        "exchange_rate": rate,
        "gross_inr": gross_inr,
        "fee_percentage": fee_percentage,
        "platform_fee_inr": fee_inr,
        "amount_inr": net_inr,
        "net_inr": net_inr
    }

class SubmitRequest(VerifyRequest):
    payout_destination: str
    amount: float
    asset: str
    qr_code_base64: Optional[str] = None   # base64-encoded image (no data URL prefix)
    qr_code_mime: Optional[str] = None     # e.g. "image/png"

@router.post("/submit", response_model=VerifyResponse)
async def submit_transaction(
    body: SubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if await get_maintenance_mode():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Exchange is currently paused for maintenance."
        )
        
    ip = _client_ip(request)
    if rate_limiter.is_rate_limited(ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    try:
        validate_txid_format(body.txid, body.chain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if await check_duplicate_txid(body.txid, db):
        raise HTTPException(status_code=409, detail="Transaction already exists")

    tx = Transaction(
        txid=body.txid,
        reference=_generate_reference(),
        user_id=user.id,
        chain=body.chain,
        token=body.asset,
        amount=body.amount,
        payout_destination=body.payout_destination,
        status=TransactionStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    db.add(tx)
    await db.flush()
    
    # Enqueue for worker
    try:
        await enqueue_tx(body.txid)
    except Exception as exc:
        logger.error("Failed to enqueue TXID %s to Redis: %s", body.txid[:16], exc)
        # We've already committed to DB, so we can't rollback easily,
        # but the scheduler will eventually pick it up if it's in the DB.
        # However, for better UX we should ideally commit AFTER enqueueing,
        # but that Risks losing the record if the app crashes between MQ and DB.
        pass

    await db.commit()
    
    # Notify Telegram Admins Immediately
    from app.services.telegram.notifier import send_tx_notification
    tx_data = {
        "id": tx.id,
        "txid": tx.txid,
        "chain": tx.chain,
        "token": tx.token,
        "amount": tx.amount,
        "usd": 0.0,
        "inr": 0.0,
        "sender": "User Deposit",
        "receiver": "Platform",
        "timestamp": int(tx.created_at.timestamp()),
        "upi_id": tx.payout_destination,
        "username": getattr(user, "username", "Unknown")
    }
    # Save QR to temp file so the worker's verified notification can attach it.
    # We do NOT send an upfront notification here — the worker sends one
    # notification after verification with real USD/INR values + the QR.
    if body.qr_code_base64:
        asyncio.create_task(_save_qr_temp(body.txid, body.qr_code_base64, body.qr_code_mime))
    
    # Increment user tx count
    user.total_transactions += 1
    
    return VerifyResponse(
        success=True,
        status="processing",
        message="Transaction is being verified",
        data={
            "txid": body.txid, 
            "reference": tx.reference, 
            "amount_inr": 0, 
            "exchange_rate": 0
        },
    )


async def _save_qr_temp(
    txid: str,
    qr_base64: Optional[str],
    qr_mime: Optional[str],
) -> None:
    """
    Decode and save the QR image to a temp file keyed by txid.
    The notifier picks this file up automatically when the worker
    sends its verified notification (with real USD/INR values).
    File lives at: /tmp/qr_<txid_safe>.<ext>
    """
    if not qr_base64:
        return
    try:
        ext = (qr_mime or "image/png").split("/")[-1].replace("jpeg", "jpg")
        txid_safe = txid[:24].replace("/", "_")
        qr_path = os.path.join(tempfile.gettempdir(), f"qr_{txid_safe}.{ext}")
        with open(qr_path, "wb") as f:
            f.write(base64.b64decode(qr_base64))
        logger.info("[QR] Saved temp QR for txid=%s → %s", txid[:16], qr_path)
    except Exception:
        logger.exception("[QR] Failed to save QR for txid=%s", txid[:16])


async def _notify_with_qr(
    tx_data: dict,
    qr_base64: Optional[str],
    qr_mime: Optional[str],
) -> None:
    """
    Legacy helper kept for reference.
    No longer called at submit time — use _save_qr_temp instead.
    """
    from app.services.telegram.notifier import send_tx_notification, send_tx_photo_notification

    qr_path: Optional[str] = None

    if qr_base64:
        try:
            ext = (qr_mime or "image/png").split("/")[-1].replace("jpeg", "jpg")
            tmp_dir = tempfile.gettempdir()
            txid_safe = tx_data.get("txid", "unknown")[:24].replace("/", "_")
            qr_path = os.path.join(tmp_dir, f"qr_{txid_safe}.{ext}")
            with open(qr_path, "wb") as f:
                f.write(base64.b64decode(qr_base64))
            logger.info("[QR] Saved temp QR to %s", qr_path)
        except Exception:
            logger.exception("[QR] Failed to decode / save QR image")
            qr_path = None

    try:
        if qr_path:
            await send_tx_photo_notification(tx_data, qr_path)
        else:
            await send_tx_notification(tx_data)
    finally:
        if qr_path and os.path.exists(qr_path):
            try:
                os.remove(qr_path)
                logger.info("[QR] Cleaned up temp QR: %s", qr_path)
            except Exception:
                logger.warning("[QR] Could not remove temp QR: %s", qr_path)

@router.get("/history")
async def get_history(page: int = 1, limit: int = 10, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    offset = (page - 1) * limit
    res = await db.execute(
        select(Transaction)
        .filter(Transaction.user_id == user.id)
        .order_by(desc(Transaction.created_at))
        .offset(offset).limit(limit)
    )
    txs = res.scalars().all()
    
    count_res = await db.scalar(select(func.count(Transaction.id)).filter(Transaction.user_id == user.id))
    
    out = []
    for t in txs:
        out.append({
            "reference": t.reference,
            "chain": t.chain,
            "asset": t.token or "Crypto",
            "amount": float(t.amount) if t.amount else 0.0,
            "inr_value": float(t.inr_value) if t.inr_value else 0.0,
            "status": t.status.value,
            "created_at": t.created_at.isoformat()
        })
        
    return {
        "transactions": out,
        "total": count_res or 0,
        "page": page,
        "pages": ((count_res or 0) + limit - 1) // limit
    }

@router.get("/{txid}")
async def get_transaction(txid: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Transaction).where(Transaction.txid == txid).limit(1))
    tx = res.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return {
        "id": tx.id,
        "txid": tx.txid,
        "reference": tx.reference,
        "user_id": tx.user_id,
        "chain": tx.chain,
        "token": tx.token,
        "amount": float(tx.amount) if tx.amount else None,
        "usd_value": float(tx.usd_value) if tx.usd_value else None,
        "inr_value": float(tx.inr_value) if tx.inr_value else None,
        "sender_address": tx.sender_address,
        "receiver_address": tx.receiver_address,
        "status": tx.status.value,
        "retry_count": tx.retry_count,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "verified_at": tx.verified_at.isoformat() if tx.verified_at else None,
        "paid_at": tx.paid_at.isoformat() if tx.paid_at else None,
        "payout_destination": tx.payout_destination
    }
