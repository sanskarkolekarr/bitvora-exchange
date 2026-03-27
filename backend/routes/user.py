"""
BITVORA EXCHANGE — User Routes
Stats and profile information.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from models.user import UserProfile
from utils.security import get_current_user
from database import get_supabase

class UpdateUPIRequest(BaseModel):
    upi: str

router = APIRouter(prefix="/user", tags=["User"])


@router.get("/stats", response_model=UserProfile)
async def get_user_stats(user: dict = Depends(get_current_user)):
    return UserProfile(
        username=user["username"],
        created_at=user["created_at"],
        total_transactions=user.get("total_transactions", 0),
        total_inr_received=user.get("total_inr_received", 0.0),
        default_upi=user.get("default_upi"),
        is_banned=user.get("is_banned", False),
    )


@router.post("/update-upi")
async def update_upi(body: UpdateUPIRequest, user: dict = Depends(get_current_user)):
    db = get_supabase()
    
    # Update public.users table
    res = db.table("users").update({"default_upi": body.upi}).eq("id", user["id"]).execute()
    
    if len(res.data) == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"status": "success", "message": "UPI ID updated"}
