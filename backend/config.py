"""
BITVORA EXCHANGE — Configuration
All settings loaded from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings
from typing import Dict, List


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    BITVORA_DOMAIN: str = "http://localhost:8000"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    # --- Supabase ---
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str

    # --- Cloudflare ---
    CLOUDFLARE_TUNNEL_TOKEN: str | None = None  # Required in production only

    # --- Admin ---
    ADMIN_SECRET_KEY: str

    # --- Telegram Notification Bot ---
    TG_BOT_TOKEN: str | None = None
    TG_CHAT_ID: str | None = None
    TG_ADMIN_IDS: str = "" # Comma-separated list of IDs

    @property
    def admin_ids_list(self) -> List[str]:
        return [i.strip() for i in self.TG_ADMIN_IDS.split(",") if i.strip()]

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379"

    # --- Sentry ---
    SENTRY_DSN: str | None = None

    # --- Rate Limiting ---
    RATE_LIMIT_PER_MINUTE: int = 60
    MAX_PENDING_TRANSACTIONS_PER_USER: int = 3


    # --- RPC Endpoints (primary — used as default) ---
    RPC_ETHEREUM: str = "https://eth.llamarpc.com"
    RPC_BSC: str = "https://bsc-dataseed.binance.org"
    RPC_TRON: str = "https://api.trongrid.io"
    RPC_SOLANA: str = "https://api.mainnet-beta.solana.com"
    RPC_TON: str = "https://toncenter.com/api/v2"
    RPC_BITCOIN: str = "https://blockstream.info/api"
    RPC_LITECOIN: str = "https://api.blockcypher.com/v1/ltc/main"

    # --- Deposit Addresses ---
    DEPOSIT_ADDRESS_ETHEREUM: str = ""
    DEPOSIT_ADDRESS_BSC: str = ""
    DEPOSIT_ADDRESS_TRON: str = ""
    DEPOSIT_ADDRESS_SOLANA: str = ""
    DEPOSIT_ADDRESS_TON: str = ""
    DEPOSIT_ADDRESS_BITCOIN: str = ""
    DEPOSIT_ADDRESS_LITECOIN: str = ""


    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    # --- Derived helpers ---

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def rpc_urls(self) -> Dict[str, str]:
        return {
            "ethereum": self.RPC_ETHEREUM,
            "bsc": self.RPC_BSC,
            "tron": self.RPC_TRON,
            "solana": self.RPC_SOLANA,
            "ton": self.RPC_TON,
            "bitcoin": self.RPC_BITCOIN,
            "litecoin": self.RPC_LITECOIN,
        }

    @property
    def fallback_rpc_urls(self) -> Dict[str, list]:
        """Ordered list of fallback RPCs per chain. Primary is index 0."""
        return {
            "ethereum": [self.RPC_ETHEREUM, "https://rpc.ankr.com/eth", "https://1rpc.io/eth"],
            "bsc": [self.RPC_BSC, "https://rpc.ankr.com/bsc", "https://bsc-rpc.publicnode.com"],
            "tron": [self.RPC_TRON],
            "solana": [self.RPC_SOLANA, "https://rpc.ankr.com/solana"],
            "ton": [self.RPC_TON],
            "bitcoin": [self.RPC_BITCOIN, "https://mempool.space/api"],
            "litecoin": [self.RPC_LITECOIN, "https://api.blockchair.com/litecoin"],
        }

    @property
    def rpc_pools(self) -> Dict[str, List[str]]:
        """
        Expanded RPC endpoint pools for round-robin load distribution.
        Used by the verification worker pool.
        """
        return {
            "ethereum": [
                self.RPC_ETHEREUM,
                "https://rpc.ankr.com/eth",
                "https://cloudflare-eth.com",
                "https://ethereum.publicnode.com",
                "https://eth.drpc.org",
                "https://rpc.mevblocker.io",
            ],
            "bsc": [
                self.RPC_BSC,
                "https://bsc-dataseed1.defibit.io",
                "https://bsc-dataseed2.defibit.io",
                "https://bsc-dataseed3.defibit.io",
                "https://bsc-rpc.publicnode.com",
                "https://bsc.drpc.org",
            ],
            "tron": [self.RPC_TRON],
            "solana": [
                self.RPC_SOLANA,
                "https://rpc.ankr.com/solana",
            ],
            "ton": [self.RPC_TON],
            "bitcoin": [
                self.RPC_BITCOIN,
                "https://mempool.space/api",
            ],
            "litecoin": [
                self.RPC_LITECOIN,
            ],
        }

    @property
    def worker_pool_config(self) -> Dict[str, int]:
        """Number of concurrent verification workers per chain family."""
        return {
            "evm": 10,
            "tron": 5,
            "solana": 5,
            "bitcoin": 3,
            "ton": 3,
            "litecoin": 2,
        }

    @property
    def deposit_addresses(self) -> Dict[str, str]:
        return {
            "ethereum": self.DEPOSIT_ADDRESS_ETHEREUM,
            "bsc": self.DEPOSIT_ADDRESS_BSC,
            "tron": self.DEPOSIT_ADDRESS_TRON,
            "solana": self.DEPOSIT_ADDRESS_SOLANA,
            "ton": self.DEPOSIT_ADDRESS_TON,
            "bitcoin": self.DEPOSIT_ADDRESS_BITCOIN,
            "litecoin": self.DEPOSIT_ADDRESS_LITECOIN,
        }

    @property
    def confirmation_thresholds(self) -> Dict[str, int]:
        return {
            "ethereum": 12,
            "bsc": 15,
            "tron": 19,
            "solana": 1,
            "ton": 1,
            "bitcoin": 2,
            "litecoin": 3,
        }

    @property
    def chain_families(self) -> Dict[str, str]:
        """Maps chain name to verifier module family."""
        return {
            "ethereum": "evm",
            "bsc": "evm",
            "tron": "tron",
            "solana": "solana",
            "ton": "ton",
            "bitcoin": "bitcoin",
            "litecoin": "litecoin",
        }

    @property
    def supported_assets(self) -> Dict[str, List[str]]:
        """Maps chain to list of supported tokens."""
        return {
            "ethereum": ["ETH", "USDT", "USDC"],
            "bsc": ["BNB", "USDT", "USDC"],
            "tron": ["TRX", "USDT"],
            "solana": ["SOL", "USDT", "USDC"],
            "ton": ["TON", "USDT"],
            "bitcoin": ["BTC"],
            "litecoin": ["LTC"],
        }

    @property
    def explorer_base_urls(self) -> Dict[str, str]:
        return {
            "ethereum": "https://etherscan.io/tx/",
            "bsc": "https://bscscan.com/tx/",
            "tron": "https://tronscan.org/#/transaction/",
            "solana": "https://solscan.io/tx/",
            "ton": "https://tonscan.org/tx/",
            "bitcoin": "https://blockstream.info/tx/",
            "litecoin": "https://blockchair.com/litecoin/transaction/",
        }


settings = Settings()
