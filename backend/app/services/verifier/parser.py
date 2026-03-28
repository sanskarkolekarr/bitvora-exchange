"""
ERC20 Transfer event log decoder.
Parses raw EVM transaction receipt logs to extract token transfer details.
Supports multiple logs in a single TX — returns only the correct transfer.

TOKEN REGISTRY IS CONFIG-DRIVEN: Uses settings.token_contracts, NOT hardcoded.
"""

from __future__ import annotations

from typing import Optional

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("verifier.parser")

# ── ERC20 Transfer(address,address,uint256) topic0 ──────────────────────────
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def decode_transfer_log(log: dict) -> Optional[dict]:
    """
    Decode a single EVM log entry as an ERC20 Transfer event.

    ERC20 Transfer layout:
      topics[0] = event signature
      topics[1] = from (address padded to 32 bytes)
      topics[2] = to   (address padded to 32 bytes)
      data       = amount (uint256)

    Returns dict with {contract, from_addr, to_addr, raw_amount} or None.
    """
    topics = log.get("topics", [])

    if len(topics) < 3:
        return None

    if topics[0].lower() != TRANSFER_TOPIC:
        return None

    try:
        from_addr = "0x" + topics[1][-40:]
        to_addr = "0x" + topics[2][-40:]

        data = log.get("data", "0x0")
        raw_amount = int(data, 16)

        contract = log.get("address", "").lower()

        return {
            "contract": contract,
            "from_addr": from_addr.lower(),
            "to_addr": to_addr.lower(),
            "raw_amount": raw_amount,
        }
    except (ValueError, IndexError, TypeError) as exc:
        logger.warning("Failed to decode Transfer log: %s", exc)
        return None


def find_matching_transfer(
    logs: list[dict],
    receiver: str,
    chain: str,
) -> Optional[dict]:
    """
    Scan all logs in a TX receipt to find the Transfer event
    that sends tokens to the expected receiver (deposit) address.

    Uses settings.token_contracts for the accepted contract registry
    instead of hardcoded values — fully config-driven.

    Handles:
    - Multiple Transfer events in one TX (e.g. swaps, multi-hops)
    - Unknown / unlisted token contracts (skipped)
    - Picks the largest matching transfer if duplicates exist

    Returns dict with {token, amount, sender, receiver, contract} or None.
    """
    receiver_lower = receiver.lower()

    # CONFIG-DRIVEN: get accepted token contracts from settings
    chain_tokens = settings.token_contracts.get(chain, {})

    if not chain_tokens:
        logger.warning("No token contracts configured for chain=%s in settings", chain)
        return None

    matching: list[dict] = []

    for log_entry in logs:
        decoded = decode_transfer_log(log_entry)
        if decoded is None:
            continue

        # Must match our deposit wallet
        if decoded["to_addr"] != receiver_lower:
            continue

        # Must be a known / accepted token contract (from config)
        token_info = chain_tokens.get(decoded["contract"])
        if token_info is None:
            logger.debug(
                "Skipping unknown token contract %s on %s",
                decoded["contract"], chain,
            )
            continue

        human_amount = decoded["raw_amount"] / (10 ** token_info["decimals"])

        matching.append({
            "token": token_info["symbol"],
            "amount": human_amount,
            "sender": decoded["from_addr"],
            "receiver": decoded["to_addr"],
            "contract": decoded["contract"],
        })

    if not matching:
        return None

    # If multiple valid transfers to our wallet, take the largest
    if len(matching) > 1:
        logger.warning(
            "Multiple matching transfers (%d) — using largest amount", len(matching),
        )
        matching.sort(key=lambda t: t["amount"], reverse=True)

    best = matching[0]
    logger.info(
        "Matched transfer: token=%s amount=%f from=%s contract=%s",
        best["token"], best["amount"], best["sender"], best["contract"],
    )
    return best
