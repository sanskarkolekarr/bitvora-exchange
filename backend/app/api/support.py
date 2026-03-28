from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.ticket import SupportTicket
from app.models.user import User
from app.utils.security import get_current_user

router = APIRouter(prefix="/support", tags=["support"], dependencies=[Depends(get_current_user)])

class CreateTicketRequest(BaseModel):
    subject: str
    message: str
    contact: Optional[str] = None
    reference: Optional[str] = None

@router.post("/create")
async def create_ticket(req: CreateTicketRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ticket = SupportTicket(
        id=str(uuid.uuid4()),
        user_id=user.id,
        subject=req.subject,
        message=req.message,
        contact=req.contact,
        reference=req.reference,
        status="open",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db.add(ticket)
    await db.commit()
    return {"success": True, "ticket_id": ticket.id}

@router.get("/my-tickets")
async def get_my_tickets(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    res = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == user.id)
        .order_by(desc(SupportTicket.created_at))
        .limit(limit)
        .offset(offset)
    )
    tickets = res.scalars().all()
    return {"tickets": [
        {
            "id": t.id,
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
