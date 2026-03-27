"""
BITVORA EXCHANGE — Pydantic Models: Transaction
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# --- Request Models ---


class TransactionSubmitRequest(BaseModel):
    chain: str = Field(..., description="Blockchain name e.g. ethereum, bsc, tron")
    asset: str = Field(..., description="Asset ticker e.g. ETH, USDT, BTC")
    txid: str = Field(..., min_length=10, description="On-chain transaction ID")
    amount: float = Field(..., gt=0, description="Amount of crypto sent")
    payout_destination: Optional[str] = Field(
        None, min_length=3, description="UPI ID or bank account number"
    )


class TransactionQuoteRequest(BaseModel):
    chain: str
    asset: str
    amount: float = Field(..., gt=0)


# --- Response Models ---


class TransactionSubmitResponse(BaseModel):
    reference: str
    status: str = "pending"
    message: str = "Transaction submitted successfully. Verification in progress."
    exchange_rate: Optional[float] = None
    amount_inr: Optional[float] = None



class TransactionQuoteResponse(BaseModel):
    chain: str
    asset: str
    amount_crypto: float
    exchange_rate: float
    platform_fee_pct: float
    platform_fee_inr: float
    amount_inr: float
    deposit_address: str


class TransactionStatusResponse(BaseModel):
    reference: str
    chain: str
    asset: str
    status: str
    amount_crypto: Optional[float] = None
    amount_inr: Optional[float] = None
    exchange_rate: Optional[float] = None
    platform_fee_pct: Optional[float] = None
    platform_fee_inr: Optional[float] = None
    confirmations: int = 0
    required_confirmations: int = 0
    payout_destination_masked: Optional[str] = None
    explorer_url: Optional[str] = None
    created_at: Optional[str] = None
    verified_at: Optional[str] = None
    payout_queued_at: Optional[str] = None
    payout_sent_at: Optional[str] = None
    error_message: Optional[str] = None


class DepositAddressResponse(BaseModel):
    chain: str
    address: str
    is_active: bool = True
