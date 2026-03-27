"""
BITVORA EXCHANGE — CoinGecko Price Helper
Compatibility layer matching the Telegram bot's services/coingecko.py interface.
Delegates to the existing price_manager module.
"""

from services.price_manager import get_cached_rate as get_price

__all__ = ["get_price"]
