"""
BITVORA EXCHANGE — Chain Recovery Watchdog
Monitors RPC node health per chain. On consecutive failures, switches to next fallback URL.
"""

import asyncio
import logging
import httpx
from config import settings

logger = logging.getLogger("bitvora.chain_recovery")

# Per-chain: tracks consecutive failures and active RPC index
_chain_state: dict[str, dict] = {}


def _init_chain(chain: str):
    if chain not in _chain_state:
        _chain_state[chain] = {
            "rpc_index": 0,
            "failures": 0,
        }


def get_active_rpc(chain: str) -> str:
    """Get the currently active (possibly failover) RPC URL for a chain."""
    _init_chain(chain)
    fallbacks = settings.fallback_rpc_urls.get(chain, [settings.rpc_urls.get(chain, "")])
    idx = _chain_state[chain]["rpc_index"]
    idx = min(idx, len(fallbacks) - 1)
    return fallbacks[idx]


def report_rpc_success(chain: str):
    """Call this after a successful RPC call to reset failure counter."""
    if chain in _chain_state:
        _chain_state[chain]["failures"] = 0


def report_rpc_failure(chain: str):
    """Call this on RPC failure. After 3 consecutive fails, switches to next fallback."""
    _init_chain(chain)
    _chain_state[chain]["failures"] += 1
    failures = _chain_state[chain]["failures"]
    
    if failures >= 3:
        fallbacks = settings.fallback_rpc_urls.get(chain, [])
        current_idx = _chain_state[chain]["rpc_index"]
        
        if current_idx < len(fallbacks) - 1:
            new_idx = current_idx + 1
            _chain_state[chain]["rpc_index"] = new_idx
            _chain_state[chain]["failures"] = 0
            logger.warning(
                f"[{chain.upper()}] RPC failed {failures}x. "
                f"Switching to fallback [{new_idx}]: {fallbacks[new_idx]}"
            )
        else:
            logger.critical(
                f"[{chain.upper()}] All fallback RPCs exhausted. "
                f"Chain verification may be impaired."
            )


async def _probe_rpc(chain: str, url: str) -> bool:
    """Quick health probe — just check HTTP 200 on the RPC endpoint base."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Most EVM nodes accept a simple GET to their base URL
            resp = await client.get(url)
            return resp.status_code < 500
    except Exception:
        return False


async def chain_recovery_watchdog():
    """
    Background worker: Every 60s, probe all chain RPCs.
    If a chain is on a fallback and primary recovers, switch back.
    """
    logger.info("Chain recovery watchdog started.")
    await asyncio.sleep(30)  # Initial delay after startup
    
    while True:
        try:
            for chain, fallbacks in settings.fallback_rpc_urls.items():
                if len(fallbacks) <= 1:
                    continue
                
                _init_chain(chain)
                current_idx = _chain_state[chain]["rpc_index"]
                
                # If on a fallback, check if primary recovered
                if current_idx > 0:
                    primary = fallbacks[0]
                    ok = await _probe_rpc(chain, primary)
                    if ok:
                        _chain_state[chain]["rpc_index"] = 0
                        _chain_state[chain]["failures"] = 0
                        logger.info(f"[{chain.upper()}] Primary RPC recovered. Switched back to: {primary}")
        
        except asyncio.CancelledError:
            logger.info("Chain recovery watchdog cancelled.")
            raise
        except Exception as e:
            logger.error(f"Chain watchdog error: {e}")
        
        await asyncio.sleep(60)
