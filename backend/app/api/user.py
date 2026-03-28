"""
User API — profile, UPI management, and transaction history.

Security:
    - All endpoints require JWT authentication (get_current_user)
    - UPI IDs are validated with strict regex before saving
    - Sensitive data (hashed_password) never exposed
"""

import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc
from pydantic import BaseModel, field_validator

from app.core.database import get_db
from app.core.logger import get_logger
from app.models.user import User
from app.models.user_payment import UserPayment
from app.models.transaction import Transaction
from app.utils.security import get_current_user

logger = get_logger("api.user")

router = APIRouter(prefix="/user", tags=["user"], dependencies=[Depends(get_current_user)])


# ═══════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════

# UPI format: alphanumeric/dot/hyphen/underscore @ alphanumeric handle
# Examples: user@paytm, name.surname@oksbi, 9876543210@ybl
_UPI_PATTERN = re.compile(r"^[a-zA-Z0-9.\-_]{2,50}@[a-zA-Z][a-zA-Z0-9]{2,30}$")


def validate_upi_format(upi: str) -> str:
    """
    Validates and normalises a UPI ID.

    Raises ValueError if format is invalid.
    Returns cleaned (trimmed, lowercase) UPI ID.
    """
    cleaned = upi.strip().lower()

    if not cleaned:
        raise ValueError("UPI ID cannot be empty")

    if len(cleaned) < 5 or len(cleaned) > 80:
        raise ValueError("UPI ID must be between 5 and 80 characters")

    if not _UPI_PATTERN.match(cleaned):
        raise ValueError(
            "Invalid UPI format. Expected: username@provider (e.g. name@paytm, 9876543210@ybl)"
        )

    return cleaned


# ═══════════════════════════════════════════════════════════════
# REQUEST / RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════

class SaveUpiRequest(BaseModel):
    """Request body for saving/updating UPI ID."""
    upi: str

    @field_validator("upi")
    @classmethod
    def validate_upi(cls, v: str) -> str:
        return validate_upi_format(v)


class UpiUpdateReq(BaseModel):
    """Legacy request schema — kept for backwards compatibility."""
    upi: str


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@router.post("/save-upi")
async def save_upi(
    req: SaveUpiRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Save or update the user's UPI ID.

    - Validates UPI format (strict regex)
    - Deactivates any previous payment methods
    - Creates a new UserPayment record (audit trail)
    - Updates the User.default_upi field for quick access
    """
    cleaned_upi = req.upi  # Already validated by Pydantic

    # ── Deactivate all existing payment methods for this user ──
    await db.execute(
        update(UserPayment)
        .where(UserPayment.user_id == user.id, UserPayment.is_active == True)
        .values(is_active=False)
    )

    # ── Create new payment record ──────────────────────────────
    new_payment = UserPayment(
        user_id=user.id,
        upi_id=cleaned_upi,
        is_active=True,
    )
    db.add(new_payment)

    # ── Also update the quick-access field on User ─────────────
    user.default_upi = cleaned_upi
    db.add(user)

    await db.flush()

    logger.info("UPI saved for user %s: %s***", user.username, cleaned_upi[:6])

    return {
        "success": True,
        "upi_id": cleaned_upi,
        "message": "UPI ID saved successfully",
    }


@router.post("/update-upi")
async def update_upi(
    req: UpiUpdateReq,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Legacy endpoint — redirects to save-upi logic.
    Kept for backwards compatibility with existing frontend.
    """
    # Validate manually since legacy schema doesn't auto-validate
    try:
        cleaned = validate_upi_format(req.upi)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # Deactivate old, create new
    await db.execute(
        update(UserPayment)
        .where(UserPayment.user_id == user.id, UserPayment.is_active == True)
        .values(is_active=False)
    )

    new_payment = UserPayment(
        user_id=user.id,
        upi_id=cleaned,
        is_active=True,
    )
    db.add(new_payment)

    user.default_upi = cleaned
    db.add(user)
    await db.flush()

    logger.info("UPI updated (legacy) for user %s: %s***", user.username, cleaned[:6])

    return {"success": True}


@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user)):
    """
    Return user profile data — excludes sensitive fields.

    Never exposes: hashed_password, internal IDs in raw form.
    """
    return {
        "username": user.username,
        "default_upi": user.default_upi,
        "total_transactions": int(user.total_transactions),
        "total_inr_received": float(user.total_inr_received),
        "is_banned": user.is_banned,
        "member_since": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/stats")
async def get_user_stats(user: User = Depends(get_current_user)):
    """Return dashboard stats for the authenticated user."""
    return {
        "total_transactions": int(user.total_transactions),
        "total_inr_received": float(user.total_inr_received),
        "default_upi": user.default_upi,
    }


@router.get("/payment-history")
async def get_payment_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the user's UPI change history (audit trail)."""
    result = await db.execute(
        select(UserPayment)
        .where(UserPayment.user_id == user.id)
        .order_by(desc(UserPayment.created_at))
        .limit(20)
    )
    payments = result.scalars().all()

    return {
        "payments": [
            {
                "upi_id": _mask_upi(p.upi_id),
                "is_active": p.is_active,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ]
    }


@router.get("/transactions")
async def list_my_transactions(
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the authenticated user's transactions."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(desc(Transaction.created_at))
        .limit(min(limit, 50))
        .offset(offset)
    )
    txs = result.scalars().all()

    return {
        "transactions": [
            {
                "reference": t.reference,
                "chain": t.chain,
                "token": t.token,
                "amount_crypto": float(t.amount) if t.amount else None,
                "amount_inr": float(t.inr_value) if t.inr_value else None,
                "status": t.status.value,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txs
        ]
    }


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _mask_upi(upi: str) -> str:
    """Partially mask a UPI ID for display: 'user@paytm' → 'us***@paytm'."""
    if not upi or "@" not in upi:
        return "***"
    parts = upi.split("@", 1)
    username = parts[0]
    provider = parts[1]
    if len(username) <= 2:
        masked = username[0] + "***"
    else:
        masked = username[:2] + "***"
    return f"{masked}@{provider}"
