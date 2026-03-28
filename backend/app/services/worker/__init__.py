"""
Redis-based distributed worker system for TXID verification.

Modules:
    queue       — Deduped Redis queue with dead-letter tracking
    locks       — Distributed locks with TTL and safe release
    scheduler   — Exponential-backoff retry engine
    worker      — Async worker pool (20–50 concurrent coroutines)
"""

from app.services.worker.worker import start_workers, stop_workers

__all__ = ["start_workers", "stop_workers"]
