"""
BITVORA EXCHANGE — EVM Chain Verifier (Exchange-Grade, Bot-Identical)
Handles: Ethereum, BSC (PoA/PoSA)

This implementation EXACTLY mirrors the Telegram bot's verification logic:

Verification Flow:
  1. Fetch TX by hash (multi-RPC parallel fan-out)
  2. Check pending (blockNumber == null → soft fail, retry)
  3. Check reverted status from receipt (hard fail)
  4. Validate block timestamp against ORDER creation time:
       - TX must NOT be earlier than (order_created_at - 5 minutes)
       - TX must be within ORDER_TIMEOUT_MINUTES from order creation
  5. Parse ALL ERC20 Transfer logs → sum transfers to deposit wallet
  6. Handle Account Abstraction (EntryPoint v0.6/v0.7) bundles
  7. Accept total_received >= expected * 0.97
  8. Explorer API (BscScan/Etherscan) as final fallback

Public RPCs are treated as unreliable. Multi-RPC parallel race used throughout.
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings
from ..models import VerificationResult

logger = logging.getLogger("bitvora.verifier.evm")


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
TIMEOUT_EXPLORER = httpx.Timeout(connect=8.0, read=15.0, write=5.0, pool=5.0)

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ERC-4337 EntryPoint contracts — when tx.to is one of these, skip tx.to check
AA_ENTRYPOINTS = frozenset({
    "0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789",  # v0.6
    "0x0000000071727de22e5e9d8baf0edac6f37da032",  # v0.7
    "0x4337000c2828f5f11571bb25f19b927b9adfe51d",  # v0.7 alt
})

TOKEN_REGISTRY: dict[str, dict[str, dict]] = {
    "USDT": {
        "ethereum": {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
        "bsc":      {"address": "0x55d398326f99059ff775485246999027b3197955", "decimals": 18},
    },
    "USDC": {
        "ethereum": {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6},
        "bsc":      {"address": "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", "decimals": 18},
    },
    "DAI": {
        "ethereum": {"address": "0x6b175474e89094c44da98b954eedeac495271d0f", "decimals": 18},
        "bsc":      {"address": "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3", "decimals": 18},
    },
    "BUSD": {
        "bsc":      {"address": "0xe9e7cea3dedca5984780bafc599bd69add087d56", "decimals": 18},
    },
}

RPC_POOLS: dict[str, list[str]] = {
    "ethereum": [
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
        "https://cloudflare-eth.com",
        "https://ethereum.publicnode.com",
        "https://eth-mainnet.public.blastapi.io",
    ],
    "bsc": [
        "https://bsc-dataseed.binance.org",
        "https://bsc-dataseed1.defibit.io",
        "https://bsc-dataseed2.defibit.io",
        "https://bsc-dataseed3.defibit.io",
        "https://bsc-rpc.publicnode.com",
        "https://rpc.ankr.com/bsc",
        "https://bsc-mainnet.public.blastapi.io",
    ],
}

EXPLORER_API: dict[str, str] = {
    "ethereum": "https://api.etherscan.io/api",
    "bsc":      "https://api.bscscan.com/api",
}
EXPLORER_TX_BASE: dict[str, str] = {
    "ethereum": "https://etherscan.io/tx/",
    "bsc":      "https://bscscan.com/tx/",
}

# ── Timing constants (must match bot) ──
ORDER_TIMEOUT_MINUTES = 30           # How long a deposit order is valid
TX_GRACE_BEFORE_ORDER_SECONDS = 300  # Allow TX up to 5 min BEFORE order creation
AMOUNT_FLOOR_RATIO = 0.97            # Accept >= 97% (3% DEX fee tolerance)

# ── Retry constants ──
MAX_RETRY_ATTEMPTS = 8
RETRY_BASE_DELAY = 12.0   # first retry = 12s
RETRY_JITTER_MAX = 5.0


# ═══════════════════════════════════════════════════════════════
# TIMING VALIDATION (mirrors bot exactly)
# ═══════════════════════════════════════════════════════════════

def _validate_tx_timing(
    tx_timestamp: int,
    order_created_at: Optional[str],
) -> Optional[str]:
    """
    Validate that a transaction timestamp is within the valid window
    for the associated order. Mirrors the Telegram bot's timing logic exactly.

    Rules:
      1. TX must NOT be earlier than (order_created_at - 5 minutes)
         → Prevents reusing old/pre-created transactions
      2. TX must NOT be later than (order_created_at + ORDER_TIMEOUT_MINUTES)
         → Order has expired by then

    Returns None if timing is valid, or an error string if invalid.
    """
    if not order_created_at:
        # No order context — fall back to absolute 30-minute window
        age = time.time() - tx_timestamp
        if age > ORDER_TIMEOUT_MINUTES * 60:
            return (
                f"Transaction is {int(age / 60)} minutes old. "
                f"Only transactions from the last {ORDER_TIMEOUT_MINUTES} minutes are accepted."
            )
        return None

    try:
        # Parse ISO8601 from Supabase — handles both with and without timezone
        created_str = order_created_at.replace("Z", "+00:00")
        order_ts = datetime.fromisoformat(created_str).timestamp()
    except (ValueError, TypeError):
        # Fallback if parse fails — use absolute 30-min window
        age = time.time() - tx_timestamp
        if age > ORDER_TIMEOUT_MINUTES * 60:
            return f"Transaction is older than {ORDER_TIMEOUT_MINUTES} minutes."
        return None

    # Rule 1: TX must not be earlier than order_created_at - 5 minutes
    earliest_valid = order_ts - TX_GRACE_BEFORE_ORDER_SECONDS
    if tx_timestamp < earliest_valid:
        tx_dt = datetime.fromtimestamp(tx_timestamp, tz=timezone.utc)
        order_dt = datetime.fromtimestamp(order_ts, tz=timezone.utc)
        diff_min = int((order_ts - tx_timestamp) / 60)
        return (
            f"Transaction predates this order by {diff_min} minutes. "
            f"TX time: {tx_dt.strftime('%H:%M:%S UTC')}, "
            f"Order created: {order_dt.strftime('%H:%M:%S UTC')}. "
            f"Please submit a transaction made AFTER placing this order."
        )

    # Rule 2: TX must not be later than order_created_at + ORDER_TIMEOUT_MINUTES
    latest_valid = order_ts + (ORDER_TIMEOUT_MINUTES * 60)
    if tx_timestamp > latest_valid:
        return (
            f"This order expired {int((tx_timestamp - latest_valid) / 60)} minutes ago. "
            f"Please create a new order."
        )

    return None  # Timing is valid


# ═══════════════════════════════════════════════════════════════
# PARALLEL RPC HELPER — Race all nodes simultaneously
# ═══════════════════════════════════════════════════════════════

async def _rpc_single(client: httpx.AsyncClient, url: str, method: str, params: list):
    """Single RPC call. Raises on any failure."""
    resp = await client.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=5.0
    )
    if resp.status_code == 429:
        raise RuntimeError(f"rate_limited")
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(f"rpc_error: {msg}")
    return data.get("result")


async def _rpc_race(
    client: httpx.AsyncClient,
    endpoints: list[str],
    method: str,
    params: list,
    require_non_null: bool = True,
) -> tuple:
    """
    Fire RPC call to ALL endpoints in parallel. Return first non-null result.
    This is the core BSC reliability mechanism — public nodes have different lag.
    Returns (result, error_string_or_None).
    """
    tasks = {asyncio.create_task(_rpc_single(client, url, method, params)): url
             for url in endpoints}
    pending = set(tasks)
    errors = []

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                result = task.result()
                if require_non_null and result is None:
                    errors.append(f"{tasks[task]}: null")
                    continue
                # Cancel remaining tasks — we got our answer
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                return result, None
            except asyncio.CancelledError:
                pass
            except Exception as e:
                errors.append(f"{tasks[task].split('/')[2]}: {e}")

    return None, " | ".join(errors) if errors else "All RPC endpoints returned null"


# ═══════════════════════════════════════════════════════════════
# TRANSFER LOG DECODER — The heart of ERC20 verification
# ═══════════════════════════════════════════════════════════════

def _decode_transfer_logs(
    logs: list,
    wallet: str,
    contract_addr: Optional[str],
    decimals: int,
) -> tuple[float, list[dict]]:
    """
    Scan ALL ERC20 Transfer(from, to, value) events in a receipt.

    Aggregates every transfer TO `wallet` regardless of routing hops.
    Handles:
      - Direct wallet transfers
      - AA/EntryPoint bundled UserOps (multiple Transfer events per TX)
      - DEX aggregator splits (1inch, ParaSwap internal hops)
      - Multi-sender consolidations

    Returns (total_received, list_of_matched_events)
    """
    if not isinstance(logs, list):
        return 0.0, []

    wallet_norm = wallet.lower()
    contract_norm = contract_addr.lower() if contract_addr else None

    total = 0.0
    matched = []

    for idx, log in enumerate(logs):
        if not isinstance(log, dict):
            continue

        topics = log.get("topics", [])
        if not isinstance(topics, list) or len(topics) < 3:
            continue

        # Must be ERC20 Transfer event
        if topics[0].lower() != TRANSFER_TOPIC:
            continue

        # Strict contract filter (if we know the token)
        log_contract = (log.get("address") or "").lower().strip()
        if contract_norm and log_contract != contract_norm:
            continue

        # Decode recipient from topics[2] (zero-padded 32-byte address → last 40 hex chars)
        try:
            recipient = "0x" + topics[2].lower()[-40:]
        except (IndexError, TypeError, AttributeError):
            continue

        if recipient != wallet_norm:
            continue  # This transfer is to a different address

        # Decode amount from data field (uint256, 32 bytes big-endian)
        data_hex = log.get("data") or "0x"
        try:
            raw_value = int(data_hex, 16)
            amount = raw_value / (10 ** decimals)
        except (ValueError, TypeError):
            continue

        if amount <= 0:
            continue

        # Decode sender
        try:
            sender = "0x" + topics[1].lower()[-40:]
        except (IndexError, TypeError):
            sender = "0x0000000000000000000000000000000000000000"

        total += amount
        matched.append({"from": sender, "to": recipient, "amount": amount,
                        "contract": log_contract, "log_index": idx})

        logger.info(
            "  ✅ Transfer[%d] %s→%s  %.8f  contract=%s",
            idx, sender[:10] + "...", recipient[:10] + "...", amount,
            log_contract[:10] + "...",
        )

    return total, matched


# ═══════════════════════════════════════════════════════════════
# EXPLORER API FALLBACK
# ═══════════════════════════════════════════════════════════════

async def _explorer_fallback(
    client: httpx.AsyncClient,
    chain: str,
    wallet: str,
    txid: str,
    contract_addr: Optional[str],
    decimals: int,
    expected_amount: float,
    required_confs: int,
    explorer_tx_base: str,
    order_created_at: Optional[str],
) -> VerificationResult:
    """
    BscScan/Etherscan token transfer API. Last resort.
    Used when RPC receipts are unavailable or AA logs are missing.
    """
    api_url = EXPLORER_API.get(chain)
    if not api_url:
        return VerificationResult(valid=False, error=f"No explorer API for chain '{chain}'")

    logger.info("🔍 Explorer fallback: chain=%s txid=%s", chain, txid[:18] + "...")

    try:
        params = {
            "module": "account",
            "action": "tokentx",
            "address": wallet,
            "page": 1,
            "offset": 250,
            "sort": "desc",
        }
        if contract_addr:
            params["contractaddress"] = contract_addr

        resp = await client.get(api_url, params=params, timeout=TIMEOUT_EXPLORER)

        if resp.status_code == 429:
            return VerificationResult(
                valid=False,
                error="Explorer API rate limited — will recheck automatically",
            )
        if resp.status_code != 200:
            return VerificationResult(valid=False, error=f"Explorer HTTP {resp.status_code}")

        data = resp.json()
        if data.get("status") == "0":
            msg = str(data.get("result", ""))
            if "No transactions found" in msg:
                return VerificationResult(
                    valid=False,
                    error="Transaction not yet indexed in explorer — automatic recheck scheduled",
                )
            return VerificationResult(valid=False, error=f"Explorer: {msg}")

        entries = data.get("result", [])
        if not isinstance(entries, list):
            return VerificationResult(valid=False, error="Unexpected explorer response format")

        txid_norm = txid.lower().strip()
        total_received = 0.0
        confirmations = 0
        tx_timestamp = 0

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if (entry.get("hash") or "").lower().strip() != txid_norm:
                continue

            to_addr = (entry.get("to") or "").lower().strip()
            if to_addr != wallet:
                continue

            try:
                token_dec = int(entry.get("tokenDecimal", str(decimals)))
                amount = int(entry.get("value", "0")) / (10 ** token_dec)
            except (ValueError, TypeError):
                continue

            if amount <= 0:
                continue

            try:
                tx_timestamp = int(entry.get("timeStamp", "0"))
                confirmations = max(confirmations, int(entry.get("confirmations", "0")))
            except (ValueError, TypeError):
                pass

            total_received += amount
            sender = (entry.get("from") or "?").lower()
            logger.info(
                "  ✅ Explorer: %s→%s  %.8f",
                sender[:10] + "...", to_addr[:10] + "...", amount,
            )

        if total_received <= 0:
            return VerificationResult(
                valid=False,
                error="Token transfer to deposit wallet not found — still indexing, will recheck",
            )

        # Timing validation with order_created_at
        if tx_timestamp:
            timing_err = _validate_tx_timing(tx_timestamp, order_created_at)
            if timing_err:
                return VerificationResult(
                    valid=False,
                    amount_detected=total_received,
                    tx_timestamp=tx_timestamp,
                    error=timing_err,
                )

        floor = expected_amount * AMOUNT_FLOOR_RATIO
        if total_received < floor:
            return VerificationResult(
                valid=False,
                confirmations=confirmations,
                required_confirmations=required_confs,
                amount_detected=total_received,
                tx_timestamp=tx_timestamp,
                error=(
                    f"Insufficient deposit: received {total_received:.8f}, "
                    f"required {expected_amount:.8f}."
                ),
            )

        return VerificationResult(
            valid=True,
            confirmations=confirmations,
            required_confirmations=required_confs,
            amount_detected=total_received,
            recipient_address=wallet,
            explorer_url=f"{explorer_tx_base}{txid}",
            tx_timestamp=tx_timestamp,
        )

    except httpx.TimeoutException:
        return VerificationResult(valid=False, error="Explorer API timed out — will retry via RPC")
    except Exception as e:
        logger.error("Explorer exception for txid=%s: %s", txid[:16], e)
        return VerificationResult(valid=False, error=f"Explorer error: {e}")


# ═══════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def verify_transaction(
    txid: str,
    chain: str,
    expected_address: str,
    expected_amount: float,
    asset: str,
    order_created_at: Optional[str] = None,
) -> VerificationResult:
    """
    Exchange-grade EVM verifier. Mirrors bot behavior exactly.

    Args:
        txid:              Transaction hash (0x...)
        chain:             "bsc" or "ethereum"
        expected_address:  Deposit wallet address
        expected_amount:   Amount in token units (e.g. 10.0 for 10 USDT)
        asset:             Token symbol (e.g. "USDT", "BNB")
        order_created_at:  ISO8601 timestamp of when the order was created (from Supabase)
                           Used for bot-identical timing validation.
    """
    txid_norm = txid.strip().lower()
    chain_norm = chain.lower()
    wallet = expected_address.lower().strip()
    asset_upper = asset.upper()

    endpoints = RPC_POOLS.get(chain_norm, [])
    if not endpoints:
        cfg = settings.rpc_urls.get(chain_norm, "")
        endpoints = [cfg] if cfg else []
    if not endpoints:
        return VerificationResult(
            valid=False,
            error=f"No RPC endpoints configured for chain '{chain}'",
        )

    native_assets = {"ETH", "BNB", "MATIC"}
    is_native = asset_upper in native_assets

    token_info = TOKEN_REGISTRY.get(asset_upper, {}).get(chain_norm)
    contract_addr = token_info["address"].lower() if token_info else None
    decimals = token_info["decimals"] if token_info else 18

    required_confs = settings.confirmation_thresholds.get(chain_norm, 12)
    explorer_tx_base = EXPLORER_TX_BASE.get(chain_norm, "")

    logger.info(
        "━━━ EVM Verification ━━━ chain=%s asset=%s txid=%s wallet=%s expected=%.6f",
        chain_norm, asset_upper, txid_norm[:18] + "...",
        wallet[:12] + "...", expected_amount,
    )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:

        last_soft_error = "Transaction not found after all retry attempts"

        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):

            # Delay: 12s on first attempt (propagation), exponential after
            if attempt == 1:
                await asyncio.sleep(12.0)
            else:
                delay = RETRY_BASE_DELAY * (1.5 ** (attempt - 2))
                jitter = random.uniform(0, RETRY_JITTER_MAX)
                logger.info(
                    "⏳ Attempt %d/%d — waiting %.0fs + %.0fs jitter",
                    attempt, MAX_RETRY_ATTEMPTS, delay, jitter,
                )
                await asyncio.sleep(delay + jitter)

            logger.info(
                "🔄 Attempt %d/%d — racing %d RPC nodes",
                attempt, MAX_RETRY_ATTEMPTS, len(endpoints),
            )

            # Step 1: Fetch TX and receipt in parallel (halves latency)
            tx_task = asyncio.create_task(
                _rpc_race(client, endpoints, "eth_getTransactionByHash", [txid_norm])
            )
            receipt_task = asyncio.create_task(
                _rpc_race(client, endpoints, "eth_getTransactionReceipt", [txid_norm])
            )
            (tx, tx_err), (receipt, receipt_err) = await asyncio.gather(
                tx_task, receipt_task
            )

            # Step 2: TX not found?
            if not tx or not isinstance(tx, dict):
                last_soft_error = (
                    f"TX not found on {chain_norm} (attempt {attempt}/{MAX_RETRY_ATTEMPTS}) — "
                    f"propagating through P2P network ({tx_err})"
                )
                logger.warning(last_soft_error)
                continue

            to_addr = (tx.get("to") or "").lower().strip()
            is_aa = to_addr in AA_ENTRYPOINTS
            is_contract_creation = not to_addr

            logger.info(
                "  TX found: to=%s block=%s type=%s",
                (to_addr[:12] + "...") if to_addr else "null",
                tx.get("blockNumber", "pending"),
                "AA_BUNDLE" if is_aa else ("CONTRACT_CREATION" if is_contract_creation else "DIRECT"),
            )

            # Step 3: Contract creations are invalid payments
            if is_contract_creation:
                return VerificationResult(
                    valid=False,
                    error="Transaction is a contract creation — not a valid payment",
                )

            # Step 4: Pending check
            block_hex = tx.get("blockNumber")
            if not block_hex or block_hex == "0x0":
                last_soft_error = "Transaction is pending — waiting for block inclusion"
                logger.info("  → Pending (mempool), waiting...")
                continue

            try:
                tx_block = int(block_hex, 16)
            except (ValueError, TypeError):
                last_soft_error = "Could not parse block number"
                continue

            # Step 5: Receipt check
            if not receipt or not isinstance(receipt, dict):
                logger.warning(
                    "  TX in block %d but receipt unavailable — RPC indexing lag", tx_block
                )
                last_soft_error = f"Receipt unavailable (block {tx_block} indexing lag)"
                continue

            # Step 6: Reverted check (HARD FAIL)
            try:
                if int(receipt.get("status", "0x1"), 16) == 0:
                    return VerificationResult(
                        valid=False,
                        error="Transaction was REVERTED on-chain — payment did not execute",
                    )
            except (ValueError, TypeError):
                pass

            # Step 7: Block timestamp + timing validation
            tx_timestamp = 0
            block_data, _ = await _rpc_race(
                client, endpoints[:4],
                "eth_getBlockByNumber", [hex(tx_block), False],
            )
            if block_data and isinstance(block_data, dict):
                try:
                    tx_timestamp = int(block_data["timestamp"], 16)
                    age_min = (time.time() - tx_timestamp) / 60
                    logger.info("  Block timestamp: %.1f min ago", age_min)

                    timing_err = _validate_tx_timing(tx_timestamp, order_created_at)
                    if timing_err:
                        return VerificationResult(
                            valid=False,
                            tx_timestamp=tx_timestamp,
                            error=timing_err,
                        )
                except (KeyError, ValueError, TypeError):
                    pass  # Non-fatal

            # Step 8: Confirmations
            confirmations = 0
            latest_hex, _ = await _rpc_race(
                client, endpoints[:3], "eth_blockNumber", [], require_non_null=True
            )
            try:
                if latest_hex and isinstance(latest_hex, str):
                    confirmations = max(0, int(latest_hex, 16) - tx_block)
                    logger.info("  Confirmations: %d", confirmations)
            except (ValueError, TypeError):
                pass

            # ── NATIVE TRANSFER (ETH / BNB) ──
            if is_native:
                if not is_aa and to_addr != wallet:
                    return VerificationResult(
                        valid=False,
                        recipient_address=to_addr,
                        error=f"Recipient mismatch: sent to {to_addr[:12]}..., expected {wallet[:12]}...",
                    )
                try:
                    amount = int(tx.get("value", "0x0"), 16) / 1e18
                except (ValueError, TypeError):
                    return VerificationResult(valid=False, error="Could not decode TX value")

                if amount <= 0:
                    return VerificationResult(valid=False, error="Transaction value is zero")

                if amount < expected_amount * AMOUNT_FLOOR_RATIO:
                    return VerificationResult(
                        valid=False,
                        confirmations=confirmations,
                        required_confirmations=required_confs,
                        amount_detected=amount,
                        tx_timestamp=tx_timestamp,
                        error=f"Underpayment: received {amount:.8f} {asset_upper}, expected {expected_amount:.8f}",
                    )

                return VerificationResult(
                    valid=True,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=amount,
                    recipient_address=wallet,
                    explorer_url=f"{explorer_tx_base}{txid_norm}",
                    tx_timestamp=tx_timestamp,
                )

            # ── ERC20 TOKEN TRANSFER ──
            logs = receipt.get("logs", [])
            if not isinstance(logs, list):
                logs = []

            logger.info(
                "  Decoding %d receipt logs for wallet=%s contract=%s",
                len(logs), wallet[:12] + "...", (contract_addr or "any")[:12] + "...",
            )

            total_received, matched_events = _decode_transfer_logs(
                logs, wallet, contract_addr, decimals
            )

            logger.info(
                "  Decoded: total_received=%.8f in %d log(s)",
                total_received, len(matched_events),
            )

            if total_received <= 0:
                last_soft_error = (
                    f"No Transfer logs found to {wallet[:12]}... in {len(logs)} logs. "
                    f"contract={contract_addr or 'any'} is_aa={is_aa}"
                )
                logger.warning(last_soft_error)

                # AA logs are unreliable on public RPCs — skip to explorer immediately
                if is_aa:
                    logger.info("  AA bundle — going directly to explorer fallback")
                    break
                continue

            # Timing validation (already done above but re-check for safety)
            if tx_timestamp:
                timing_err = _validate_tx_timing(tx_timestamp, order_created_at)
                if timing_err:
                    return VerificationResult(
                        valid=False,
                        amount_detected=total_received,
                        tx_timestamp=tx_timestamp,
                        error=timing_err,
                    )

            # Amount validation
            floor = expected_amount * AMOUNT_FLOOR_RATIO
            logger.info(
                "  Amount check: received=%.8f floor=%.8f expected=%.8f",
                total_received, floor, expected_amount,
            )

            if total_received < floor:
                return VerificationResult(
                    valid=False,
                    confirmations=confirmations,
                    required_confirmations=required_confs,
                    amount_detected=total_received,
                    recipient_address=wallet,
                    tx_timestamp=tx_timestamp,
                    error=(
                        f"Insufficient deposit: received {total_received:.8f} {asset_upper}, "
                        f"required {expected_amount:.8f}. "
                        f"If you paid DEX fees from the deposit amount, contact support."
                    ),
                )

            # ── SUCCESS ──
            logger.info(
                "✅ VERIFIED: txid=%s received=%.8f %s confs=%d",
                txid_norm[:18] + "...", total_received, asset_upper, confirmations,
            )
            return VerificationResult(
                valid=True,
                confirmations=confirmations,
                required_confirmations=required_confs,
                amount_detected=total_received,
                recipient_address=wallet,
                explorer_url=f"{explorer_tx_base}{txid_norm}",
                tx_timestamp=tx_timestamp,
            )

        # All RPC attempts exhausted → Explorer fallback
        logger.warning(
            "🔁 All %d RPC attempts exhausted for %s — trying explorer",
            MAX_RETRY_ATTEMPTS, txid_norm[:18] + "...",
        )

        return await _explorer_fallback(
            client, chain_norm, wallet, txid_norm, contract_addr, decimals,
            expected_amount, required_confs, explorer_tx_base, order_created_at,
        )
