"""
Configuration system using Pydantic v2 BaseSettings.
All values are validated on startup. Access via the global `settings` singleton.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings sourced from environment variables / .env file.
    Validated eagerly on first access.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ──────────────────────────────────────────────
    ENVIRONMENT: str = "development"

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bitvora"

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Exchange rates ───────────────────────────────────────────
    INR_RATE: float = 83.50

    # ── Supported blockchain chains ──────────────────────────────
    SUPPORTED_CHAINS: str = "ethereum,bsc,tron,bitcoin"

    # ── Wallet addresses (per chain) ─────────────────────────────
    DEPOSIT_ADDRESS_ETHEREUM: str = ""
    DEPOSIT_ADDRESS_BSC: str = ""
    DEPOSIT_ADDRESS_TRON: str = ""
    DEPOSIT_ADDRESS_BITCOIN: str = ""
    DEPOSIT_ADDRESS_LITECOIN: str = ""
    DEPOSIT_ADDRESS_SOLANA: str = ""
    DEPOSIT_ADDRESS_TON: str = ""

    # ── RPC endpoints (per chain) ────────────────────────────────
    RPC_ETHEREUM: str = "https://eth.llamarpc.com"
    RPC_BSC: str = "https://bsc-dataseed.binance.org"
    RPC_TRON: str = "https://api.trongrid.io"
    RPC_BITCOIN: str = "https://blockstream.info/api"
    RPC_LITECOIN: str = "https://litecoinblockexplorer.net/api"
    RPC_SOLANA: str = "https://api.mainnet-beta.solana.com"
    RPC_TON: str = "https://tonapi.io/v2"

    # ── USDT Token Contracts (per chain) ─────────────────────────
    USDT_ETH_CONTRACT: str = "0xdac17f958d2ee523a2206206994597c13d831ec7"
    USDT_BSC_CONTRACT: str = "0x55d398326f99059ff775485246999027b3197955"
    USDT_TRON_CONTRACT: str = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

    # ── USDC Token Contracts (per chain) ─────────────────────────
    USDC_ETH_CONTRACT: str = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    USDC_BSC_CONTRACT: str = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
    USDC_TRON_CONTRACT: str = "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8"

    # ── Deposit Limits ───────────────────────────────────────────
    MIN_DEPOSIT_AMOUNT: float = 1.0
    MAX_DEPOSIT_AMOUNT: float = 5000.0

    # ── Telegram ─────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_GROUP_ID: str = ""
    TELEGRAM_REPORT_GROUP_ID: str = ""
    TELEGRAM_ADMIN_IDS: str = ""  # comma-separated Telegram user IDs
    ADMIN_SECRET_KEY: str = "fallback-secret-key-123456789"

    @property
    def admin_ids_list(self) -> list[int]:
        """Parse comma-separated TELEGRAM_ADMIN_IDS into a list of ints."""
        if not self.TELEGRAM_ADMIN_IDS.strip():
            return []
        return [int(uid.strip()) for uid in self.TELEGRAM_ADMIN_IDS.split(",") if uid.strip()]

    # ── Rate limiting ────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    MAX_PENDING_TRANSACTIONS_PER_USER: int = 3

    # ── DB Pool tuning ───────────────────────────────────────────
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 300

    # ── Redis tuning ─────────────────────────────────────────────
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_LOCK_TIMEOUT: int = 60  # seconds

    # ═══════════════════════════════════════════════════════════════
    # DERIVED HELPERS
    # ═══════════════════════════════════════════════════════════════

    @property
    def chains_list(self) -> list[str]:
        """Parse the comma-separated SUPPORTED_CHAINS string into a list."""
        return [c.strip().lower() for c in self.SUPPORTED_CHAINS.split(",") if c.strip()]

    @property
    def wallet_addresses(self) -> dict[str, str]:
        """Return a chain -> address mapping for all configured wallets."""
        return {
            chain: getattr(self, f"DEPOSIT_ADDRESS_{chain.upper()}", "")
            for chain in self.chains_list
        }

    @property
    def rpc_endpoint_lists(self) -> dict[str, list[str]]:
        """
        Return chain -> [rpc_url, ...] mapping.
        Supports comma-separated multi-RPC in env vars for fallback.
        Deduplicates and strips whitespace.
        """
        result: dict[str, list[str]] = {}
        for chain in self.chains_list:
            raw = getattr(self, f"RPC_{chain.upper()}", "")
            endpoints = list(dict.fromkeys(
                url.strip() for url in raw.split(",") if url.strip()
            ))
            if endpoints:
                result[chain] = endpoints
        return result

    @property
    def rpc_endpoints(self) -> dict[str, str]:
        """Return a chain -> primary rpc_url mapping (first endpoint)."""
        return {
            chain: urls[0]
            for chain, urls in self.rpc_endpoint_lists.items()
        }

    @property
    def token_contracts(self) -> dict[str, dict[str, dict[str, str | int]]]:
        """
        Return chain -> {contract_address: {symbol, decimals}} mapping.
        Built from USDT_*_CONTRACT and USDC_*_CONTRACT env vars.
        All EVM contract addresses are lowercased for comparison.
        """
        registry: dict[str, dict[str, dict]] = {}

        # ── Mapping: (env_attr, chain_key, symbol, decimals) ──
        token_defs = [
            # USDT
            ("USDT_ETH_CONTRACT", "ethereum", "USDT", 6),
            ("USDT_BSC_CONTRACT", "bsc",      "USDT", 18),
            ("USDT_TRON_CONTRACT", "tron",     "USDT", 6),
            # USDC
            ("USDC_ETH_CONTRACT", "ethereum", "USDC", 6),
            ("USDC_BSC_CONTRACT", "bsc",      "USDC", 18),
            ("USDC_TRON_CONTRACT", "tron",    "USDC", 6),
        ]

        for attr, chain, symbol, decimals in token_defs:
            contract = getattr(self, attr, "").strip()
            if not contract:
                continue
            # EVM addresses: lowercase for reliable matching
            if chain in ("ethereum", "bsc"):
                contract = contract.lower()
            registry.setdefault(chain, {})[contract] = {
                "symbol": symbol,
                "decimals": decimals,
            }

        return registry

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    # ─── Validators ──────────────────────────────────────────────

    @field_validator("INR_RATE")
    @classmethod
    def validate_inr_rate(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("INR_RATE must be positive")
        return v

    @field_validator("MIN_DEPOSIT_AMOUNT")
    @classmethod
    def validate_min_deposit(cls, v: float) -> float:
        if v < 0:
            raise ValueError("MIN_DEPOSIT_AMOUNT cannot be negative")
        return v

    @field_validator("MAX_DEPOSIT_AMOUNT")
    @classmethod
    def validate_max_deposit(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("MAX_DEPOSIT_AMOUNT must be positive")
        return v

    @model_validator(mode="after")
    def validate_database_url(self) -> "Settings":
        """Ensure DATABASE_URL uses the async driver."""
        if self.DATABASE_URL and "asyncpg" not in self.DATABASE_URL:
            self.DATABASE_URL = self.DATABASE_URL.replace(
                "postgresql://", "postgresql+asyncpg://"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton factory. Cached after first call."""
    return Settings()


# Global convenience instance
settings: Settings = get_settings()
