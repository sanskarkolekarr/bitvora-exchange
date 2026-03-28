from __future__ import annotations

import uuid

from sqlalchemy import Column, String, Integer, Float

from app.core.database import Base


class Setting(Base):
    """Global settings stored in DB."""
    __tablename__ = "settings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(100), unique=True, index=True, nullable=False)
    value_str = Column(String(500), nullable=True)
    value_int = Column(Integer, nullable=True)
    value_float = Column(Float, nullable=True)
