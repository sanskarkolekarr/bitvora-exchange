"""
BITVORA EXCHANGE — Support Routes
Public route for submitting support tickets.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from database import get_supabase
import logging

logger = logging.getLogger("api")

router = APIRouter(prefix="/support", tags=["Support"])


class SupportSubmitRequest(BaseModel):
    subject: str
    message: str
    reference: Optional[str] = None
    contact: Optional[str] = None


@router.post("/submit")
async def submit_ticket(req: SupportSubmitRequest):
    try:
        db = get_supabase()
        
        insert_data = {
            "subject": req.subject,
            "message": req.message,
            "reference": req.reference,
            "contact": req.contact
        }
        
        result = db.table("support_tickets").insert(insert_data).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to insert ticket.")
            
        ticket_id = result.data[0]["id"]
        return {"ticket_id": ticket_id, "status": "success"}

    except Exception as e:
        logger.error(f"Failed to submit ticket: {e}")
        raise HTTPException(status_code=500, detail=str(e))
