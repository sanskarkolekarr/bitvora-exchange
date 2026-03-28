"""
User payment details (UPI) — audit-friendly, linked to user accounts.

Stores payment method history so admin can track changes.
Only the latest entry per user is considered "active".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserPayment(Base):
    """Stores user UPI payment destinations with audit trail."""

    __tablename__ = "user_payments"

    # ── Primary key ──────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ── Foreign key to users ─────────────────────────────────────
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── UPI ID (masked in public responses) ──────────────────────
    upi_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    # ── Whether this is the currently active payment method ──────
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # ── Timestamps ───────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationship ─────────────────────────────────────────────
    user = relationship("User", back_populates="payment_methods")

    # ── Table-level indexes ──────────────────────────────────────
    __table_args__ = (
        Index("ix_user_payments_user_active", "user_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserPayment(id={self.id}, user_id={self.user_id}, "
            f"upi={self.upi_id[:6]}***, active={self.is_active})>"
        )
