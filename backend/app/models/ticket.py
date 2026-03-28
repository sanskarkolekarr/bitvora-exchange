"""
Support Ticket entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class SupportTicket(Base):
    """Customer support ticket."""
    __tablename__ = "support_tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    subject = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    contact = Column(String(100), nullable=True)
    reference = Column(String(100), nullable=True)  # txref
    status = Column(String(50), default="open", nullable=False)  # open, in_progress, resolved, closed
    admin_note = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", backref="tickets")
