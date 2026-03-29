from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.ticket import SupportTicket
from app.models.user import User
from app.utils.security import get_current_user
from app.services.telegram import notifier

router = APIRouter(prefix="/support", tags=["support"], dependencies=[Depends(get_current_user)])

class CreateTicketRequest(BaseModel):
    subject: str
    message: str
    contact: Optional[str] = None
    reference: Optional[str] = None

@router.post("/create")
async def create_ticket(
    req: CreateTicketRequest, 
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(get_current_user)
):
    ticket = SupportTicket(
        id=str(uuid.uuid4()),
        user_id=user.id,
        subject=req.subject,
        message=req.message,
        contact=req.contact,
        reference=req.reference,
        status="open"
    )
    db.add(ticket)
    await db.commit()

    # Trigger Telegram Alert
    ticket_data = {
        "id": ticket.id,
        "subject": ticket.subject,
        "message": ticket.message,
        "contact": ticket.contact,
        "reference": ticket.reference,
        "user_id": user.id,
    }
    bg_tasks.add_task(notifier.send_support_ticket, ticket_data)

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
