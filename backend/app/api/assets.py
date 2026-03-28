from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.setting import Setting

router = APIRouter(prefix="/assets", tags=["assets"])

# In-memory mock or simple DB fetch for these
@router.get("/rates")
async def get_rates():
    # Return mock rate or fetch from Setting
    return {
        "rates": {
            "USD": {"rate_inr": 88.50}
        }
    }

@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    # You could fetch distinct keys, but let's just return a mock so the frontend doesn't crash
    return {
        "settings": {
            "stat_volume": "₹1 Cr+",
            "stat_time": "~15 Min",
            "stat_assets": "4 Assets",
            "counter_min": 1250000,
            "counter_max": 2000000
        }
    }

@router.get("/status")
async def get_status():
    return {"maintenance": False}
