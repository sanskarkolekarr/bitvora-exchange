"""
BITVORA EXCHANGE — Auth Routes
Registration, login, logout, refresh — all via Supabase Auth.
"""

import logging
from fastapi import APIRouter, HTTPException
from models.user import (
    RegisterRequest,
    LoginRequest,
    AuthResponse,
    RefreshRequest,
    MessageResponse,
)
from database import get_supabase

logger = logging.getLogger("bitvora.routes.auth")
router = APIRouter(prefix="/auth", tags=["Authentication"])


def _synthetic_email(username: str) -> str:
    """Generate internal-only email from username."""
    return f"{username.lower()}@bitvora.internal"


@router.post("/register", response_model=MessageResponse)
async def register(body: RegisterRequest):
    db = get_supabase()
    email = _synthetic_email(body.username)

    # Check if username already taken
    existing = (
        db.table("users")
        .select("id")
        .eq("username", body.username.lower())
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="Username is unavailable")

    # Create Supabase Auth user
    try:
        auth_result = db.auth.admin.create_user(
            {
                "email": email,
                "password": body.password,
                "email_confirm": True,
            }
        )
    except Exception as e:
        logger.error(f"Auth creation failed: {e}")
        raise HTTPException(
            status_code=400, detail=str(e)
        )

    user_id = auth_result.user.id

    # Insert platform profile
    try:
        db.table("users").insert(
            {
                "id": str(user_id),
                "username": body.username.lower(),
                "default_upi": body.default_upi,
            }
        ).execute()
    except Exception as e:
        logger.error(f"User profile insert failed: {e}")
        # Attempt cleanup of auth user
        try:
            db.auth.admin.delete_user(str(user_id))
        except Exception:
            pass
        raise HTTPException(
            status_code=500, detail=f"Insert failed: {str(e)}"
        )

    return MessageResponse(message="Account created successfully.")


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    # Isolated client so we don't pollute the global service-role singleton with a user session
    from config import settings
    from supabase import create_client
    local_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    email = _synthetic_email(body.username)

    try:
        result = local_db.auth.sign_in_with_password(
            {"email": email, "password": body.password}
        )
    except Exception:
        # Same generic message for all failures — prevents username enumeration
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not result.session:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return AuthResponse(
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout():
    # Client-side token discard is primary. Server-side is best-effort.
    return MessageResponse(message="Logged out successfully.")


@router.post("/refresh", response_model=AuthResponse)
async def refresh(body: RefreshRequest):
    from config import settings
    from supabase import create_client
    local_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

    try:
        result = local_db.auth.refresh_session(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if not result.session:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return AuthResponse(
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
    )
