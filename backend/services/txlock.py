"""
BITVORA EXCHANGE — TXID Lock Service
Prevents reuse of a transaction hash across orders.

Mirrors the Telegram bot's services/txlock.py design:
  - Permanent lock via local JSON file (no TTL-based expiry)
  - Atomic write via temp file + rename to prevent corruption
  - Used AFTER blockchain verification to mark TXIDs as consumed

This is different from utils/txid_ledger.py which handles
pre-verification (2-hour window) TXID deduplication at the
API submission layer.

This module handles post-verification permanent locks to ensure
a confirmed TXID can never be reused for a different order.
"""

import json
import logging
import tempfile
import os
from pathlib import Path

logger = logging.getLogger("bitvora.txlock")

DB_FILE = Path(__file__).resolve().parent.parent / "data" / "locked_txids.json"


def _load() -> set:
    """Load the locked TXID set from disk."""
    if not DB_FILE.exists():
        return set()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except Exception as e:
        logger.error("Failed to load txid lock file: %s", e)
        return set()


def _save(txids: set) -> None:
    """Atomically save the locked TXID set to disk."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=DB_FILE.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(sorted(txids), f)
            os.replace(tmp_path, DB_FILE)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.error("Failed to save txid lock file: %s", e)


def is_txid_used(txid: str) -> bool:
    """Return True if this TXID has already been used for a confirmed order."""
    return txid.strip().lower() in _load()


def lock_txid(txid: str) -> None:
    """Mark a TXID as permanently used. Call only after successful verification."""
    normalized = txid.strip().lower()
    txids = _load()
    if normalized in txids:
        logger.warning("Attempted to lock already-locked txid=%s", txid[:16])
        return
    txids.add(normalized)
    _save(txids)
    logger.info("TXID permanently locked: %s", txid[:16])


def unlock_txid(txid: str) -> None:
    """Remove a TXID from the lock set (e.g., on order cancellation)."""
    normalized = txid.strip().lower()
    txids = _load()
    if normalized not in txids:
        return
    txids.discard(normalized)
    _save(txids)
    logger.info("TXID unlocked: %s", txid[:16])
