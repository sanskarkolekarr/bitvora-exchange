"""
Telegram integration service.
Provides bot initialization, transaction notifications, and admin commands.
"""

from app.services.telegram.bot import get_bot, get_dispatcher, start_polling, stop_polling
from app.services.telegram.notifier import send_tx_notification
from app.services.telegram.commands import register_admin_commands

__all__ = [
    "get_bot",
    "get_dispatcher",
    "start_polling",
    "stop_polling",
    "send_tx_notification",
    "register_admin_commands",
]
