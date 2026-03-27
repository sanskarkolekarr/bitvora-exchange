from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VerificationResult:
    """
    Result of a single blockchain transaction verification attempt.

    Fields:
        valid:                  True only if the TX is confirmed, correct address,
                                correct amount, within time window, and not reverted.
        confirmations:          Number of block confirmations observed.
        required_confirmations: Minimum required for this chain.
        amount_detected:        Sum of all on-chain transfers to deposit wallet (in coin units).
        recipient_address:      The wallet address found on-chain (normalised lowercase).
        explorer_url:           Direct link to the block explorer for this TX.
        tx_timestamp:           Unix timestamp of the block containing this TX (0 if unknown).
        error:                  Human-readable failure reason (None on success).
                                Error strings are categorised:
                                  - HARD: "reverted", "mismatch", "older than", "contract creation"
                                  - SOFT: "not found", "pending", "insufficient confirmation"
    """
    valid: bool
    confirmations: int = 0
    required_confirmations: int = 0
    amount_detected: float = 0.0
    recipient_address: str = ""
    explorer_url: str = ""
    tx_timestamp: int = 0          # Unix epoch of TX block (0 = unknown)
    error: Optional[str] = None

    @property
    def is_hard_failure(self) -> bool:
        """True if this failure should NOT be retried."""
        if self.valid or not self.error:
            return False
        err = self.error.lower()
        return any(kw in err for kw in [
            "reverted", "mismatch", "wrong address", "older than",
            "contract creation", "double-spend", "insufficient deposit",
            "not a valid payment",
        ])

    @property
    def is_soft_failure(self) -> bool:
        """True if this failure is transient and should be retried."""
        return not self.valid and not self.is_hard_failure
