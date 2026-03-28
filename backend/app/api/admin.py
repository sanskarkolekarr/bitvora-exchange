from datetime import datetime, timezone
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, desc

from app.core.database import get_db
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.ticket import SupportTicket
from app.models.log import AdminLog
from app.utils.security import admin_required, get_current_user
from app.services.settings import get_inr_rate, set_inr_rate

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_required)])

@router.get("/stats")
async def get_admin_stats(db: AsyncSession = Depends(get_db)):
    # Calculate stats
    pending = await db.scalar(select(func.count(Transaction.id)).filter(Transaction.status == "pending"))
    verifying = await db.scalar(select(func.count(Transaction.id)).filter(Transaction.status == "processing"))
    payout_sent = await db.scalar(select(func.count(Transaction.id)).filter(Transaction.status == "confirmed"))
    failed = await db.scalar(select(func.count(Transaction.id)).filter(Transaction.status == "failed"))
    
    # Financials
    total_tx = await db.scalar(select(func.count(Transaction.id)).filter(Transaction.status == "confirmed"))
    res = await db.execute(select(func.sum(Transaction.inr_value)).filter(Transaction.status == "confirmed"))
    total_vol = res.scalar() or 0.0
    
    # Let's say fees is ~1% of volume for display purposes
    total_fees = total_vol * 0.01

    # Get current INR rate from DB
    current_inr_rate = await get_inr_rate()

    return {
        "pending_count": pending or 0,
        "verifying_count": verifying or 0,
        "verified_count": 0,
        "payout_queued_count": 0,  # We don't have a specific queued status right now
        "payout_sent_count": payout_sent or 0,
        "failed_count": failed or 0,
        "expired_count": 0,
        "total_volume_inr": float(total_vol),
        "total_fees_collected": float(total_fees),
        "total_transactions": total_tx or 0,
        "average_processing_minutes": 2, # Mock
        "current_inr_rate": current_inr_rate,
    }

@router.get("/transactions")
async def list_transactions(limit: int = 20, offset: int = 0, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Transaction).order_by(desc(Transaction.created_at)).limit(limit).offset(offset))
    txs = res.scalars().all()
    
    out = []
    for t in txs:
        out.append({
            "id": t.id,
            "reference": t.reference,
            "chain": t.chain,
            "asset": "Crypto",  # Adjust for actual token parsing if needed
            "amount_inr": float(t.inr_value) if t.inr_value else 0.0,
            "status": "payout_sent" if t.status.value == "confirmed" else t.status.value,
            "txid": t.txid,
            "explorer_url": f"https://tronscan.org/#/transaction/{t.txid}" if t.chain.lower() == "tron" else f"https://etherscan.io/tx/{t.txid}",
            "created_at": t.created_at.isoformat()
        })
    return {"transactions": out}

@router.get("/users")
async def list_users(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).order_by(desc(User.created_at)).limit(limit))
    users = res.scalars().all()
    return {"users": [
        {
            "id": u.id,
            "username": u.username,
            "default_upi": u.default_upi,
            "total_transactions": u.total_transactions,
            "total_inr_received": float(u.total_inr_received),
            "is_banned": u.is_banned,
            "created_at": u.created_at.isoformat()
        } for u in users
    ]}

@router.post("/{action}/{user_id}")
async def toggle_ban(action: str, user_id: str, db: AsyncSession = Depends(get_db)):
    if action not in ["ban", "unban"]:
        raise HTTPException(status_code=404, detail="Unknown action")
    
    val = (action == "ban")
    await db.execute(update(User).where(User.id == user_id).values(is_banned=val))
    await db.commit()
    return {"success": True}

@router.get("/logs")
async def get_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AdminLog).order_by(desc(AdminLog.created_at)).limit(limit))
    logs = res.scalars().all()
    return {"logs": [
        {
            "id": log.id,
            "admin_username": log.admin_username,
            "action": log.action,
            "note": log.note,
            "target_id": log.target_id,
            "timestamp": log.created_at.isoformat()
        } for log in logs
    ]}

@router.post("/transaction/{txid}/paid")
async def mark_tx_paid(txid: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_user)):
    res = await db.execute(select(Transaction).where(Transaction.txid == txid).limit(1))
    tx = res.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    old_status = tx.status.value
    tx.status = TransactionStatus.PAID
    tx.paid_at = datetime.now(timezone.utc)
    
    log = AdminLog(
        admin_username=admin.username,
        action="MARK_PAID",
        target_id=txid,
        note=f"Status changed from {old_status} to paid",
        created_at=datetime.now(timezone.utc)
    )
    db.add(log)
    await db.commit()
    return {"success": True, "status": "paid"}

@router.post("/transaction/{txid}/failed")
async def mark_tx_failed(txid: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_user)):
    res = await db.execute(select(Transaction).where(Transaction.txid == txid).limit(1))
    tx = res.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    old_status = tx.status.value
    tx.status = TransactionStatus.FAILED
    
    log = AdminLog(
        admin_username=admin.username,
        action="MARK_FAILED",
        target_id=txid,
        note=f"Status changed from {old_status} to failed",
        created_at=datetime.now(timezone.utc)
    )
    db.add(log)
    await db.commit()
    return {"success": True, "status": "failed"}

@router.get("/tickets")
async def list_tickets(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SupportTicket).order_by(desc(SupportTicket.created_at)).limit(limit).offset(offset))
    tickets = res.scalars().all()
    return {"tickets": [
        {
            "id": t.id,
            "user_id": t.user_id,
            "subject": t.subject,
            "message": t.message,
            "contact": t.contact,
            "reference": t.reference,
            "status": t.status,
            "admin_note": t.admin_note,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat()
        } for t in tickets
    ]}

class ReplyTicketRequest(BaseModel):
    note: str
    status: Optional[str] = "resolved"

@router.post("/tickets/{ticket_id}/reply")
async def reply_ticket(ticket_id: str, req: ReplyTicketRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_user)):
    res = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id).limit(1))
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket.admin_note = req.note
    if req.status:
        ticket.status = req.status
    ticket.updated_at = datetime.now(timezone.utc)
    
    log = AdminLog(
        admin_username=admin.username,
        action="REPLY_TICKET",
        target_id=ticket_id,
        note=f"Replied to ticket and set status to {req.status}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(log)
    await db.commit()
    return {"success": True}

@router.get("/payout-queue")
async def payout_queue(db: AsyncSession = Depends(get_db)):
    """Return confirmed transactions with user UPI for payout processing."""
    result = await db.execute(
        select(Transaction, User.username, User.default_upi)
        .outerjoin(User, Transaction.user_id == User.id)
        .where(Transaction.status == "confirmed")
        .order_by(desc(Transaction.verified_at))
        .limit(50)
    )
    rows = result.all()

    queue = []
    for tx, username, upi in rows:
        queue.append({
            "id": tx.id,
            "reference": tx.reference,
            "chain": tx.chain,
            "inr_value": float(tx.inr_value) if tx.inr_value else 0.0,
            "username": username or "N/A",
            "upi_id": upi or "NOT SET",
            "verified_at": tx.verified_at.isoformat() if tx.verified_at else None,
        })

    return {"queue": queue}



# ── INR Rate Settings ──────────────────────────────────────────

class UpdateINRRateRequest(BaseModel):
    """Request body for updating the INR rate."""
    rate: float

    @field_validator("rate")
    @classmethod
    def validate_rate(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("INR rate must be a positive number")
        if v > 500:
            raise ValueError("INR rate seems unreasonably high (max 500)")
        return round(v, 2)


@router.get("/settings/inr-rate")
async def get_inr_rate_endpoint():
    """Get the current INR/USD conversion rate."""
    rate = await get_inr_rate()
    return {
        "key": "INR_RATE",
        "value": rate,
        "source": "database",
    }


@router.put("/settings/inr-rate")
async def update_inr_rate_endpoint(body: UpdateINRRateRequest):
    """
    Update the INR/USD conversion rate.
    The new rate is persisted to the database and applied instantly.
    """
    old_rate = await get_inr_rate()

    try:
        new_rate = await set_inr_rate(body.rate)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "old_rate": old_rate,
        "new_rate": new_rate,
        "message": f"INR rate updated from ₹{old_rate:.2f} to ₹{new_rate:.2f}",
    }
