"""
Transaction ORM model.

Optimised for high-throughput reads/writes with:
- Unique index on TXID (critical for dedup)
- Composite index on (chain, status) for queue queries
- Index on status for worker polling
- Index on created_at for time-range scans
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    func,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship # Added relationship

from app.core.database import Base


class TransactionStatus(str, enum.Enum):
    """Possible lifecycle states for a transaction."""
    PENDING = "pending"
    PROCESSING = "processing"
    CONFIRMED = "confirmed"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class Transaction(Base):
    """
    Core transaction record.

    Each row represents a single crypto-to-INR verification request.
    The TXID column has a UNIQUE constraint to prevent double-processing.
    """

    __tablename__ = "transactions"

    # ── Primary key ──────────────────────────────────────────────
    id: Mapped[str] = mapped_column( # Changed type to str for UUID
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()) # Changed to UUID generation
    )

    # ── Transaction identity ─────────────────────────────────────
    txid: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column( # Added reference column
        String(12), unique=True, index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column( # Added user_id column
        ForeignKey("users.id"), index=True, nullable=True
    )
    chain: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    token: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )

    # ── Financial data ───────────────────────────────────────────
    amount: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    usd_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    inr_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )

    # ── Addresses ────────────────────────────────────────────────
    sender_address: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default=None
    )
    receiver_address: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default=None
    )

    # ── Status & retry ───────────────────────────────────────────
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, native_enum=False, length=16),
        nullable=False,
        default=TransactionStatus.PENDING,
        server_default="pending",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    telegram_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ── Timestamps ───────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    payout_destination: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )
    user = relationship("User", back_populates="transactions")

    # ── Table-level indexes ──────────────────────────────────────
    __table_args__ = (
        # Composite index for worker queries: "give me pending TXs on ethereum"
        Index("ix_transactions_chain_status", "chain", "status"),
        # Status-only index for dashboard / polling
        Index("ix_transactions_status", "status"),
        # Time-range queries (audit, reporting)
        Index("ix_transactions_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction(id={self.id}, txid={self.txid[:12]}..., "
            f"chain={self.chain}, status={self.status.value})>"
        )
