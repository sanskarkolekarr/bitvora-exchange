"""
Pydantic v2 schemas for transaction verification API.

These schemas define the wire format — no business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerifyRequest(BaseModel):
    """Incoming transaction verification request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    txid: str = Field(
        ...,
        min_length=20,
        max_length=128,
        description="Blockchain transaction hash / ID",
        examples=["0xabc123..."],
    )
    chain: str = Field(
        ...,
        min_length=2,
        max_length=32,
        description="Blockchain name (ethereum, bsc, tron, ...)",
        examples=["ethereum"],
    )
    token: Optional[str] = Field(
        default=None,
        max_length=32,
        description="Token symbol (USDT, ETH, etc.) — optional",
        examples=["USDT"],
    )

    @field_validator("chain")
    @classmethod
    def normalise_chain(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("txid")
    @classmethod
    def normalise_txid(cls, v: str) -> str:
        return v.strip()


class VerifyResponse(BaseModel):
    """Standard response for verification endpoints."""

    success: bool = Field(
        ..., description="Whether the operation succeeded"
    )
    status: str = Field(
        ..., description="Current transaction status"
    )
    message: str = Field(
        ..., description="Human-readable result message"
    )
    data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional payload with detailed verification data",
    )


class StatusResponse(BaseModel):
    """Lightweight status-check response."""
    txid: str = Field(..., description="Transaction hash")
    reference: str = Field(..., description="Short reference ID")
    status: str = Field(..., description="Current verification status")
    amount_crypto: Optional[float] = Field(None, description="Amount of crypto")
    amount_inr: Optional[float] = Field(None, description="Amount in INR")
    asset: Optional[str] = Field(None, description="Token symbol")
    chain: Optional[str] = Field(None, description="Blockchain network")
    exchange_rate: Optional[float] = Field(None, description="Exchange rate applied")
    payout_destination: Optional[str] = Field(None, description="Payout destination")
    payout_destination_masked: Optional[str] = Field(None, description="Masked payout destination")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    explorer_url: Optional[str] = Field(None, description="Block explorer URL")
    created_at: Optional[datetime] = Field(None, description="Timestamp created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp updated")
    verified_at: Optional[datetime] = Field(None, description="Timestamp verified")
    paid_at: Optional[datetime] = Field(None, description="Timestamp paid")
