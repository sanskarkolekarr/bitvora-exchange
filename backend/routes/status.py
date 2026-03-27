"""
BITVORA EXCHANGE — Status Routes
Transaction status lookup by reference token.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from models.transaction import TransactionStatusResponse
from utils.security import get_current_user
from database import get_supabase

logger = logging.getLogger("bitvora.routes.status")
router = APIRouter(prefix="/status", tags=["Status"])


def _mask_destination(dest: str | None) -> str | None:
    """Show only last 4 characters of payout destination."""
    if not dest or len(dest) < 5:
        return dest
    return "•" * (len(dest) - 4) + dest[-4:]


@router.get("/{reference}", response_model=TransactionStatusResponse)
async def get_status(reference: str, user: dict = Depends(get_current_user)):
    db = get_supabase()

    result = (
        db.table("transactions")
        .select("*")
        .eq("reference", reference.upper())
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    tx = result.data[0]

    # Verify ownership
    if tx["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return TransactionStatusResponse(
        reference=tx["reference"],
        chain=tx["chain"],
        asset=tx["asset"],
        status=tx["status"],
        amount_crypto=tx.get("amount_crypto"),
        amount_inr=tx.get("amount_inr"),
        exchange_rate=tx.get("exchange_rate"),
        platform_fee_pct=tx.get("platform_fee_pct"),
        platform_fee_inr=tx.get("platform_fee_inr"),
        confirmations=tx.get("confirmations", 0),
        required_confirmations=tx.get("required_confirmations", 0),
        payout_destination_masked=_mask_destination(tx.get("payout_destination")),
        explorer_url=tx.get("explorer_url"),
        created_at=tx.get("created_at"),
        verified_at=tx.get("verified_at"),
        payout_queued_at=tx.get("payout_queued_at"),
        payout_sent_at=tx.get("payout_sent_at"),
        error_message=tx.get("error_message"),
    )
