"""
User entity representing an exchange customer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Numeric, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """Registered user on the platform."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    default_upi = Column(String(100), nullable=True)
    is_banned = Column(Boolean, default=False, nullable=False)
    
    total_transactions = Column(Numeric(10, 0), default=0, nullable=False)
    total_inr_received = Column(Numeric(20, 2), default=0, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # relations
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    payment_methods = relationship("UserPayment", back_populates="user", cascade="all, delete-orphan")
