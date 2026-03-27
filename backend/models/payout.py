"""
BITVORA EXCHANGE — Pydantic Models: Payout
"""

from pydantic import BaseModel, Field
from typing import Optional


class PayoutQueueItem(BaseModel):
    id: str
    transaction_id: str
    chain: str
    asset: str
    txid: str
    amount_inr: float
    payout_destination: str
    status: str
    explorer_url: Optional[str] = None
    queued_at: str
    admin_note: Optional[str] = None


class MarkPaidRequest(BaseModel):
    admin_note: Optional[str] = None


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=3)


class AdminStatsResponse(BaseModel):
    total_volume_inr: float
    total_transactions: int
    pending_count: int
    verifying_count: int
    verified_count: int
    payout_queued_count: int
    payout_sent_count: int
    failed_count: int
    expired_count: int
    total_fees_collected: float
    average_processing_minutes: Optional[float] = None
    sent_today: Optional[int] = None
    volume_today: Optional[float] = None
    largest_trade_today: Optional[float] = None
    last_trade_ago: Optional[str] = None
    average_deal_time: Optional[int] = None
