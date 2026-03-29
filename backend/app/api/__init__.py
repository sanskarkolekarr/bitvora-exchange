"""
API package — exposes route modules.
"""

from app.api.transaction import router as transaction_router
from app.api.status import router as status_router
from app.api.auth import router as auth_router
from app.api.user import router as user_router
from app.api.assets import router as assets_router
from app.api.support import router as support_router

__all__ = ["transaction_router", "status_router", "auth_router", "user_router", "assets_router", "support_router"]
