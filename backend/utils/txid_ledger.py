"""
BITVORA EXCHANGE — TXID Ledger Utilities (Local VPS Storage)
Prevents double-processing of transaction IDs by keeping a local cache for 2 hours.
"""

import logging
import json
import os
import time

logger = logging.getLogger("bitvora.txid_ledger")

LOCAL_LEDGER_FILE = "txid_ledger_local.json"

def _load_ledger() -> dict:
    if os.path.exists(LOCAL_LEDGER_FILE):
        try:
            with open(LOCAL_LEDGER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_ledger(data: dict):
    try:
        with open(LOCAL_LEDGER_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save local ledger: {e}")

def _cleanup_ledger(ledger: dict):
    """Remove entries older than 2 hours (7200 seconds)"""
    now = time.time()
    for txid in list(ledger.keys()):
        if now - ledger[txid].get("timestamp", 0) > 7200:
            ledger.pop(txid, None)

async def is_txid_processed(txid: str) -> bool:
    """Check if a TXID already exists in the local ledger."""
    from services.txlock import is_txid_used
    
    normalized = txid.strip().lower()
    
    # 1. Check permanent lock first (actually used)
    if is_txid_used(normalized):
        return True
        
    # 2. Check 2-hour volatile ledger (spam prevention)
    ledger = _load_ledger()
    _cleanup_ledger(ledger)
    _save_ledger(ledger)
    return normalized in ledger

async def register_txid(txid: str, chain: str, transaction_id: str) -> None:
    """Insert a TXID into the local ledger with a timestamp."""
    normalized = txid.strip().lower()
    ledger = _load_ledger()
    _cleanup_ledger(ledger)
    
    ledger[normalized] = {
        "chain": chain,
        "transaction_id": transaction_id,
        "timestamp": time.time()
    }
    
    _save_ledger(ledger)
    logger.info("Locally registered TXID %s... on %s", normalized[0:16], chain)

async def remove_txid(txid: str) -> None:
    """Remove a TXID from the local ledger (used on expiry to allow resubmission)."""
    normalized = txid.strip().lower()
    ledger = _load_ledger()
    if normalized in ledger:
        ledger.pop(normalized, None)
        _save_ledger(ledger)
        logger.info("Removed TXID %s... from local ledger", normalized[0:16])
