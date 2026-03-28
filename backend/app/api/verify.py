"""
POST /verify-tx — Transaction verification endpoint.

Flow:
  1. Rate-limit by IP
  2. Validate TXID format
  3. Check duplicate TXID in DB
  4. Create pending DB entry
  5. Optional fast verifier check (single attempt, short timeout)
  6. Push to Redis queue for worker processing
  7. Return immediately
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.redis import enqueue_tx
from app.core.security import (
    check_duplicate_txid,
    rate_limiter,
    validate_txid_format,
)
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import VerifyRequest, VerifyResponse

logger = get_logger("api.verify")

router = APIRouter(tags=["verification"])

# ── Quick-check timeout (seconds) ──────────────────────────────
_QUICK_CHECK_TIMEOUT: float = 2.0


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


async def _optional_quick_check(txid: str, chain: str) -> Optional[dict]:
    """
    Single, non-blocking attempt to verify via the verifier service.

    Returns verification data dict on success, None on failure/timeout.
    This MUST NOT loop or retry — one shot only.
    """
    try:
        from app.services.verifier import verify_tx

        result = await asyncio.wait_for(
            verify_tx(txid, chain),
            timeout=_QUICK_CHECK_TIMEOUT,
        )

        if isinstance(result, dict) and result.get("success"):
            data = result.get("data", {})
            # Enrich with price conversion if verifier returned amount
            amount = data.get("amount")
            token = data.get("token")
            if amount and token:
                try:
                    from app.services.price.converter import convert
                    conversion = await convert(token, amount)
                    return {
                        "amount": amount,
                        "usd_value": conversion.get("total_usd"),
                        "inr_value": conversion.get("total_inr"),
                        "sender_address": data.get("sender"),
                        "receiver_address": data.get("receiver"),
                    }
                except Exception:
                    return {
                        "amount": amount,
                        "sender_address": data.get("sender"),
                        "receiver_address": data.get("receiver"),
                    }
        return None
    except asyncio.TimeoutError:
        logger.info("Quick check timed out for TX %s — deferring to queue", txid[:16])
        return None
    except ImportError:
        logger.debug("Verifier service not available — skipping quick check")
        return None
    except Exception as exc:
        logger.warning("Quick check failed for TX %s: %s", txid[:16], exc)
        return None


# ── Endpoint ────────────────────────────────────────────────────


@router.post(
    "/verify-tx",
    response_model=VerifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a transaction for verification",
    responses={
        400: {"description": "Invalid TXID format or unsupported chain"},
        409: {"description": "Transaction already exists"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def verify_transaction(
    body: VerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> VerifyResponse:
    """
    Accepts a TXID for asynchronous blockchain verification.

    The endpoint validates the input, stores a pending record, performs an
    optional single-shot fast check, then enqueues the TXID for full
    worker-driven verification.  Response time target: < 100 ms.
    """

    ip = _client_ip(request)

    # ── STEP 1: Rate limiting ───────────────────────────────────
    if rate_limiter.is_rate_limited(ip):
        logger.warning("Rate limited IP %s on /verify-tx", ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Too many requests. Limit: {settings.RATE_LIMIT_PER_MINUTE}/min",
            },
        )

    # ── STEP 2: Validate TXID format ───────────────────────────
    try:
        validate_txid_format(body.txid, body.chain)
    except ValueError as exc:
        logger.info("Invalid TXID rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_txid",
                "message": str(exc),
            },
        )

    # ── STEP 3: Check duplicate ────────────────────────────────
    if await check_duplicate_txid(body.txid, db):
        logger.info("Duplicate TXID %s — returning already_processed", body.txid[:16])
        return VerifyResponse(
            success=True,
            status="already_processed",
            message="This transaction has already been submitted for verification",
            data={"txid": body.txid},
        )

    # ── STEP 4: Create pending DB entry ────────────────────────
    tx = Transaction(
        txid=body.txid,
        chain=body.chain,
        token=body.token,
        status=TransactionStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    db.add(tx)
    await db.flush()  # assign PK without committing yet
    logger.info("Created pending TX record id=%s txid=%s", tx.id, body.txid[:16])

    # ── STEP 5: Optional quick check (single attempt) ──────────
    quick_result = await _optional_quick_check(body.txid, body.chain)

    if quick_result:
        # Quick check succeeded — update record and return immediately
        tx.status = TransactionStatus.CONFIRMED
        tx.amount = quick_result.get("amount")
        tx.usd_value = quick_result.get("usd_value")
        tx.inr_value = quick_result.get("inr_value")
        tx.sender_address = quick_result.get("sender_address")
        tx.receiver_address = quick_result.get("receiver_address")
        tx.verified_at = datetime.now(timezone.utc)

        # Commit is handled by the get_db dependency on success
        logger.info("Quick check confirmed TX %s", body.txid[:16])

        return VerifyResponse(
            success=True,
            status="confirmed",
            message="Transaction verified successfully",
            data={
                "txid": body.txid,
                "amount": tx.amount,
                "usd_value": tx.usd_value,
                "inr_value": tx.inr_value,
            },
        )

    # ── STEP 6: Enqueue for worker processing ──────────────────
    enqueued = await enqueue_tx(body.txid)
    if enqueued:
        logger.info("TX %s enqueued for worker processing", body.txid[:16])
    else:
        logger.info("TX %s already in queue (enqueue_tx returned False)", body.txid[:16])

    # ── STEP 7: Return accepted response ───────────────────────
    return VerifyResponse(
        success=True,
        status="processing",
        message="Transaction is being verified",
        data={"txid": body.txid},
    )
