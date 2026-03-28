"""
Admin Logs entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.core.database import Base


class AdminLog(Base):
    """Audit log for admin actions."""
    __tablename__ = "admin_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_username = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    note = Column(Text, nullable=True)
    target_id = Column(String(100), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
