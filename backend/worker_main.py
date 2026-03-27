"""
BITVORA EXCHANGE — Worker Entry Point (No HTTP Server)
Standalone process that runs background verification workers, confirmation tracker,
lock recovery, expiry checker, cleanup, and chain watchdog.

This is the entry point for the `worker-verifier` Docker service.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

# ═══════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-35s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bitvora.worker_main")


# ═══════════════════════════════════════════════
# Sentry (optional — initialise before anything else)
# ═══════════════════════════════════════════════


def _init_sentry():
    """Initialise Sentry for error tracking in the worker process."""
    try:
        from config import settings

        if settings.SENTRY_DSN:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                traces_sample_rate=0.05,
                profiles_sample_rate=0.01,
                environment=settings.ENVIRONMENT,
                server_name="bitvora-worker-verifier",
            )
            logger.info("Sentry initialised for worker process")
        else:
            logger.info("Sentry DSN not set — error tracking disabled")
    except ImportError:
        logger.warning("sentry-sdk not installed — error tracking disabled")
    except Exception as e:
        logger.warning(f"Sentry init failed: {e}")


# ═══════════════════════════════════════════════
# Worker Tasks
# ═══════════════════════════════════════════════

_tasks: list[asyncio.Task] = []
_shutdown_event = asyncio.Event()


async def _run_workers():
    """Start all background worker tasks."""
    from services.tx_verifier.verification_queue import start_worker_pool, pending_tracker_worker
    from services.tx_verifier.confirmation_tracker import confirmation_tracker_worker
    from services.tx_verifier.lock_recovery import lock_recovery_worker
    from services.expiry import expiry_worker
    from services.cleanup_worker import cleanup_worker
    from services.chain_watchdog import chain_recovery_watchdog
    from services.watcher import pending_tx_watcher
    from services.sweeper import late_sweeper_worker
    from services.telegram_bot import telegram_worker

    start_time = datetime.now(timezone.utc)
    logger.info("=" * 60)
    logger.info("  BITVORA EXCHANGE WORKER — Starting Up")
    logger.info(f"  Start time: {start_time.isoformat()}")
    logger.info("=" * 60)

    _tasks.extend(
        [
            asyncio.create_task(start_worker_pool(), name="verification_pool"),
            asyncio.create_task(pending_tracker_worker(), name="pending_tracker"),
            asyncio.create_task(
                confirmation_tracker_worker(), name="confirmation_tracker"
            ),
            asyncio.create_task(lock_recovery_worker(), name="lock_recovery"),
            asyncio.create_task(expiry_worker(), name="expiry"),
            asyncio.create_task(cleanup_worker(), name="cleanup"),
            asyncio.create_task(chain_recovery_watchdog(), name="chain_watchdog"),
            asyncio.create_task(pending_tx_watcher(), name="pending_tx_watcher"),
            asyncio.create_task(late_sweeper_worker(), name="late_sweeper_worker"),
            asyncio.create_task(telegram_worker(), name="telegram_bot"),
        ]
    )

    logger.info(f"Started {len(_tasks)} worker tasks at {start_time.isoformat()}")

    # Wait until shutdown signal
    await _shutdown_event.wait()


async def _shutdown():
    """Gracefully stop all workers."""
    shutdown_time = datetime.now(timezone.utc)
    logger.info(f"Shutdown initiated at {shutdown_time.isoformat()}")
    logger.info(f"Cancelling {len(_tasks)} worker tasks...")

    for task in _tasks:
        task.cancel()
        logger.info(f"  Cancelling: {task.get_name()}")

    await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()

    # Close Redis connection
    try:
        from services.redis_client import close_redis

        await close_redis()
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")

    logger.info("All workers stopped. Goodbye.")


def _signal_handler(sig, frame):
    """Handle SIGTERM/SIGINT for clean Docker shutdown."""
    logger.info(f"Received signal {sig}")
    _shutdown_event.set()


async def main():
    """Main entry point for the worker process."""
    _init_sentry()

    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown_event.set())
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, _signal_handler)

    try:
        await _run_workers()
    finally:
        await _shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted via KeyboardInterrupt")
    except Exception as e:
        logger.critical(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)
