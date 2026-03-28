"""
Core infrastructure package.
Provides config, database, redis, security, and logging primitives.
"""

from app.core.config import settings
from app.core.logger import get_logger

__all__ = ["settings", "get_logger"]
