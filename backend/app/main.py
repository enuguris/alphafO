"""
AlphaFO — FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.database import init_db
from app.api.v1 import signals, trades, backtest, portfolio, data, settings as settings_router, chat, options as options_router, instruments as instruments_router, pattern_finder as pattern_finder_router, dashboard as dashboard_router, system as system_router
from app.api.websocket import router as ws_router


async def _subscribe_open_trade_tokens() -> None:
    """Subscribe live option tokens for all open paper trades so MTM gets real prices."""
    try:
        from sqlalchemy import select
        from app.database import AsyncSessionLocal
        from app.models.trades import Trade, TradeStatus
        from app.core.data.kite_ticker import ticker_service

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Trade.symbol).where(
                    Trade.status == TradeStatus.OPEN,
                    Trade.mode   == "paper",
                    Trade.symbol != Trade.underlying,
                )
            )
            symbols = [row[0] for row in result.all() if row[0]]

        if symbols:
            ticker_service.subscribe_option_tokens(symbols)
            logger.info(f"Subscribed {len(symbols)} option tokens for open paper trades")
    except Exception as e:
        logger.warning(f"Could not subscribe open trade tokens: {e}")


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


async def _sync_portfolio_heat_from_db() -> None:
    """
    After reset_daily_pnl clears Redis, re-seed DAILY_DEPLOYED_KEY from open
    positions in the DB so the heat circuit breaker stays accurate across restarts.
    """
    try:
        from sqlalchemy import select, func
        from app.database import AsyncSessionLocal
        from app.models.trades import Trade, TradeStatus, TradeMode
        from app.core.risk.gate import record_deployed

        async with AsyncSessionLocal() as db:
            # Margin-style: heat = blocked margin + entry charges per leg.
            # Legacy rows (margin_blocked NULL) fall back to premium value.
            result = await db.execute(
                select(func.sum(func.coalesce(
                    Trade.margin_blocked + func.coalesce(Trade.charges_entry, 0.0),
                    Trade.entry_price * Trade.quantity,
                ))).where(
                    Trade.status == TradeStatus.OPEN,
                    Trade.mode   == TradeMode.PAPER,
                )
            )
            deployed = result.scalar() or 0.0
        if deployed > 0:
            record_deployed(float(deployed))
            logger.info(f"Portfolio heat synced from DB: ₹{deployed:,.0f} deployed across open trades")
    except Exception as exc:
        logger.warning(f"Could not sync portfolio heat from DB: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting AlphaFO v{settings.app_version} — mode: {settings.app_mode}")
    from app.models.anomaly import Anomaly  # noqa: F401 — register table for create_all
    await init_db()
    await _load_kite_credentials_from_db()

    # Restore persisted app_mode from Redis (survives restarts)
    try:
        import redis as redis_lib
        _r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        _saved_mode = _r.get("alphafO:app_mode")
        if _saved_mode:
            from app.config import AppMode
            settings.app_mode = AppMode(_saved_mode)
            logger.info(f"App mode restored from Redis: {settings.app_mode}")
    except Exception as exc:
        logger.warning(f"Could not restore app_mode from Redis: {exc}")

    # Start tick data service (real via Kite Ticker, or simulated fallback)
    from app.core.data.kite_ticker import ticker_service, ensure_stream_groups
    ensure_stream_groups()
    ticker_service.start()

    # Reset daily risk counters, then re-sync heat from open DB positions
    from app.core.risk.gate import reset_daily_pnl
    reset_daily_pnl()
    await _sync_portfolio_heat_from_db()

    # Subscribe option tokens for any already-open paper trades
    await _subscribe_open_trade_tokens()

    yield
    ticker_service.stop()
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
app.include_router(chat.router,           prefix="/api/v1/chat",    tags=["Chat"])
app.include_router(options_router.router,     prefix="/api/v1/options",     tags=["Options"])
app.include_router(instruments_router.router,   prefix="/api/v1/instruments",     tags=["Instruments"])
app.include_router(pattern_finder_router.router, prefix="/api/v1/pattern-finder", tags=["PatternFinder"])
app.include_router(dashboard_router.router,      prefix="/api/v1/dashboard",      tags=["Dashboard"])
app.include_router(system_router.router,         prefix="/api/v1/system",         tags=["System"])
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "mode": settings.app_mode, "version": settings.app_version}
