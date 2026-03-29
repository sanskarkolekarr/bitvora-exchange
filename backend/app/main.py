"""
FastAPI application entry point.
Wires up database, Redis, workers, price engine, and Telegram lifecycle.
No business logic — just infrastructure.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logger import get_logger
from app.core.redis import close_redis, get_redis
from app.services.price.service import start_price_updater, stop_price_updater
from app.services.settings import seed_defaults as seed_settings
from app.services.worker import start_workers, stop_workers
from app.services.telegram import start_polling as start_telegram, stop_polling as stop_telegram

# ── API routers ────────────────────────────────────────────────
from app.api import (
    transaction_router,
    status_router,
    auth_router,
    user_router,
    assets_router,
    support_router
)

logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    logger.info("Starting LMAO Exchange API [env=%s]", settings.ENVIRONMENT)

    # ── Startup ──────────────────────────────────────────────────
    await init_db()
    await seed_settings()  # seed INR_RATE etc. into settings table
    await get_redis()  # warm the pool
    await start_price_updater()  # background price cache refresh
    logger.info("Infrastructure ready (DB + Redis + Price Engine + Settings)")

    # ── Worker pool ─────────────────────────────────────────────
    await start_workers()
    logger.info("Worker pool started")

    # ── Telegram bot ───────────────────────────────────────────
    try:
        await start_telegram()
        logger.info("Telegram bot polling started")
    except RuntimeError as exc:
        logger.warning("Telegram bot not started: %s", exc)

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    await stop_telegram()
    await stop_workers()
    await stop_price_updater()
    await close_redis()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="LMAO Exchange API",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS (allow frontend origin) ───────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Guaranteed CORS fix for any domain (bitvora.in, www.bitvora.in)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ───────────────────────────────────────────
# Nginx proxies /api/* → backend root, so NO prefix needed here.
# Frontend calls: apiFetch('/verify-tx'), apiFetch('/status/{txid}')
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(transaction_router)
app.include_router(status_router)
app.include_router(assets_router)
app.include_router(support_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
