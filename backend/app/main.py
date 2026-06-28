"""
AlphaFO — FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.database import init_db
from app.api.v1 import signals, trades, backtest, portfolio, data, settings as settings_router, chat
from app.api.websocket import router as ws_router


async def _load_kite_credentials_from_db() -> None:
    """On startup, restore Kite credentials from DB into in-memory settings."""
    from datetime import date
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.core.encryption import decrypt

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(KiteConfig).where(KiteConfig.id == 1))
            cfg = result.scalar_one_or_none()
            if cfg and cfg.api_key:
                settings.kite_api_key = cfg.api_key
                if cfg.api_secret_enc:
                    settings.kite_api_secret = decrypt(cfg.api_secret_enc)
                if cfg.access_token_enc and cfg.token_date == date.today():
                    settings.kite_access_token = decrypt(cfg.access_token_enc)
                    logger.info("Kite access token loaded from DB (valid today)")
                else:
                    logger.info("Kite credentials loaded; access token missing or expired")
    except Exception as exc:
        logger.warning(f"Could not load Kite credentials from DB: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting AlphaFO v{settings.app_version} — mode: {settings.app_mode}")
    await init_db()
    await _load_kite_credentials_from_db()
    yield
    logger.info("AlphaFO shutting down")


app = FastAPI(
    title="AlphaFO",
    description="NSE F&O Pattern Signal Engine",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(signals.router, prefix="/api/v1/signals", tags=["Signals"])
app.include_router(trades.router, prefix="/api/v1/trades", tags=["Trades"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["Backtest"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["Portfolio"])
app.include_router(data.router, prefix="/api/v1/data", tags=["Market Data"])
app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["Settings"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "mode": settings.app_mode, "version": settings.app_version}
