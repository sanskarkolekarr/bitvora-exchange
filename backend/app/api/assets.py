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
async def get_settings():
    from app.services.settings import get_all_settings_dict
    db_settings = await get_all_settings_dict()

    # Parse out addresses to nested dictionary pattern for frontend compat
    addresses = {}
    for key, val in db_settings.items():
        if key.endswith("_ADDRESS"):
            chain = key.replace("_ADDRESS", "").lower()
            addresses[chain] = val

    return {
        "settings": {
            "addresses": addresses,
            "meta": db_settings
        }
    }

@router.get("/status")
async def get_status():
    return {"maintenance": False}
