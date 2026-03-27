"""
BITVORA EXCHANGE — Security Utilities
JWT verification, user dependency, admin dependency.
"""

import logging
from fastapi import Depends, HTTPException, Header
from jose import jwt, JWTError
from config import settings
from database import get_supabase

logger = logging.getLogger("bitvora.security")


async def get_current_user(authorization: str = Header(...)) -> dict:
    """
    FastAPI dependency: extracts Bearer token, verifies JWT,
    checks user is not banned, returns user dict.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = authorization.replace("Bearer ", "")

    db = get_supabase()
    try:
        user_data = db.auth.get_user(token)
        if not user_data or not user_data.user:
            raise Exception()
        user_id = user_data.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Fetch user from DB and check ban status
    result = db.table("users").select("*").eq("id", user_id).execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = result.data[0]

    if user.get("is_banned", False):
        raise HTTPException(
            status_code=403, detail="Your account has been suspended."
        )

    return user


async def verify_admin(
    authorization: str = Header(None), x_admin_key: str = Header(None)
) -> str:
    """
    FastAPI dependency for admin routes.
    Validates the static ADMIN_SECRET_KEY.
    Matches either:
    1. Authorization: Bearer <key>
    2. X-Admin-Key: <key>
    Returns 404 (not 403) to hide admin route existence.
    """
    # Try X-Admin-Key first (used by frontend)
    if x_admin_key and x_admin_key == settings.ADMIN_SECRET_KEY:
        return "admin"

    # Fallback to standard Authorization header
    expected = f"Bearer {settings.ADMIN_SECRET_KEY}"
    if authorization and authorization == expected:
        return "admin"

    raise HTTPException(status_code=404, detail="Not found")
