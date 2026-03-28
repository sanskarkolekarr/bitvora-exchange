"""
GET /status/{txid} — Transaction status lookup endpoint.

Returns the current verification status and value data for a given TXID.
Read-only, lightweight, no side-effects.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.security import rate_limiter
from app.models.transaction import Transaction
from app.schemas.transaction import StatusResponse

logger = get_logger("api.status")

router = APIRouter(tags=["status"])


# ── Helpers ─────────────────────────────────────────────────────


def _client_ip(request: Request) -> str:
    """Extract the real client IP, respecting common proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ── Endpoint ────────────────────────────────────────────────────


@router.get(
    "/status/{txid}",
    response_model=StatusResponse,
    summary="Check the verification status of a transaction",
    responses={
        404: {"description": "Transaction not found"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def get_transaction_status(
    txid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """
    Look up the current status for a previously submitted TXID.

    Returns financial values (USD / INR) when the transaction has been
    confirmed by a worker.
    """
    ip = _client_ip(request)

    # ── Rate limiting ──────────────────────────────────────────
    if rate_limiter.is_rate_limited(ip):
        logger.warning("Rate limited IP %s on /status", ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Too many requests. Limit: {settings.RATE_LIMIT_PER_MINUTE}/min",
            },
        )

    # ── Query DB ───────────────────────────────────────────────
    txid_clean = txid.strip()

    stmt = select(Transaction).where(
        or_(Transaction.txid == txid_clean, Transaction.reference == txid_clean)
    ).limit(1)
    result = await db.execute(stmt)
    tx = result.scalar_one_or_none()

    if tx is None:
        logger.info("Status lookup miss for query %s", txid_clean[:16])
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "message": "Transaction not found. Verify the reference code and try again.",
            },
        )

    logger.info(
        "Status lookup hit for query %s → %s",
        txid_clean[:16],
        tx.status.value,
    )

    payout_masked = tx.payout_destination
    if payout_masked and "@" in payout_masked:
        parts = payout_masked.split("@")
        name = parts[0]
        if len(name) > 3:
            payout_masked = f"{name[:2]}***{name[-1]}@{parts[1]}"
        else:
            payout_masked = f"***@{parts[1]}"

    c = (tx.chain or "").strip().lower()
    explorer_url = None
    if "eth" in c:
        explorer_url = f"https://etherscan.io/tx/{tx.txid}"
    elif "bsc" in c or "binance" in c:
        explorer_url = f"https://bscscan.com/tx/{tx.txid}"
    elif "tron" in c or "trx" in c:
        explorer_url = f"https://tronscan.org/#/transaction/{tx.txid}"
    elif "sol" in c:
        explorer_url = f"https://solscan.io/tx/{tx.txid}"
    elif "ton" in c:
        explorer_url = f"https://tonviewer.com/transaction/{tx.txid}"
    elif "pol" in c or "matic" in c:
        explorer_url = f"https://polygonscan.com/tx/{tx.txid}"

    exchange_rate = None
    if tx.inr_value and tx.amount and tx.amount > 0:
        exchange_rate = tx.inr_value / tx.amount

    return StatusResponse(
        txid=tx.txid,
        reference=tx.reference,
        status=tx.status.value,
        amount_crypto=float(tx.amount) if tx.amount else None,
        amount_inr=float(tx.inr_value) if tx.inr_value else None,
        asset=tx.token,
        chain=tx.chain,
        exchange_rate=exchange_rate,
        payout_destination=tx.payout_destination,
        payout_destination_masked=payout_masked,
        created_at=tx.created_at,
        updated_at=tx.verified_at or tx.paid_at or tx.created_at,
        verified_at=tx.verified_at,
        paid_at=tx.paid_at,
        explorer_url=explorer_url,
        error_message="Verification failed" if tx.status.value == "failed" else None
    )
