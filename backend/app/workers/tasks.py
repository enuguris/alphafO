"""Background tasks — scan engine + paper trade auto-execution."""
import asyncio
from datetime import datetime, timedelta
from loguru import logger

from app.workers.celery_app import celery_app


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _persist_and_broadcast(signals: list[dict], db, broadcast_fn):
    """Save signals to DB and fire WebSocket broadcast."""
    from app.models.signals import Signal, SignalStatus

    created = []
    valid_until = datetime.utcnow() + timedelta(hours=24)

    for s in signals:
        # Skip duplicates: same underlying + pattern + direction in last hour
        from sqlalchemy import select, and_
        from datetime import timedelta as td
        cutoff = datetime.utcnow() - td(hours=1)
        q = select(Signal).where(
            and_(
                Signal.underlying == s["underlying"],
                Signal.pattern_name == s["pattern_name"],
                Signal.direction == s["direction"],
                Signal.created_at >= cutoff,
            )
        )
        result = await db.execute(q)
        if result.scalar_one_or_none():
            continue

        sig = Signal(
            pattern_name=s["pattern_name"],
            pattern_version=s.get("pattern_version", "1.0"),
            symbol=s.get("symbol", s["underlying"]),
            underlying=s["underlying"],
            instrument=s.get("instrument", s["underlying"]),
            direction=s["direction"],
            entry_price=s["entry_price"],
            target_price=s["target_price"],
            stop_loss=s["stop_loss"],
            expected_return_pct=s["expected_return_pct"],
            confidence_score=s["confidence_score"],
            explanation=s.get("explanation", ""),
            trading_style=s.get("trading_style", "intraday"),
            status=SignalStatus.ACTIVE,
            created_at=datetime.utcnow(),
            valid_until=valid_until,
            option_type=s.get("option_type"),
            strike=s.get("strike"),
            expiry_date_str=s.get("expiry_date_str"),
            option_strategy=s.get("option_strategy"),
            lot_size=s.get("lot_size"),
            delta=s.get("delta"),
            gamma=s.get("gamma"),
            theta=s.get("theta"),
            vega=s.get("vega"),
            iv_at_signal=s.get("iv_at_signal"),
            iv_rank=s.get("iv_rank"),
            regime_trend=s.get("regime_trend"),
            regime_volatility=s.get("regime_volatility"),
            estimated_premium=s.get("estimated_premium"),
            max_loss=s.get("max_loss"),
        )
        db.add(sig)
        created.append(sig)

    if created:
        await db.commit()
        for sig in created:
            await db.refresh(sig)
        logger.info(f"Persisted {len(created)} new signals")

        # Auto paper-trade high-confidence signals
        await _auto_paper_trade(created, db)

    # Broadcast all (including non-persisted for live display)
    if broadcast_fn and signals:
        for s in signals:
            await broadcast_fn({"type": "new_signal", "signal": s})

    return created


async def _auto_paper_trade(signals, db):
    """Auto-execute paper trades for signals with confidence > 0.72."""
    from app.models.trades import Trade, TradeStatus
    from app.models.portfolio import Portfolio
    from sqlalchemy import select

    HIGH_CONF = 0.72

    for sig in signals:
        if sig.confidence_score < HIGH_CONF:
            continue
        if not sig.estimated_premium or not sig.lot_size:
            continue

        premium = sig.estimated_premium
        lots = 1  # always 1 lot for paper trading
        cost = premium * sig.lot_size * lots

        # Check paper portfolio has capital
        result = await db.execute(select(Portfolio).where(Portfolio.mode == "paper"))
        portfolio = result.scalar_one_or_none()
        if not portfolio or portfolio.capital_current < cost * 1.2:
            continue

        trade = Trade(
            signal_id=sig.id,
            underlying=sig.underlying,
            instrument=sig.instrument or sig.underlying,
            direction=sig.direction,
            entry_price=premium,
            quantity=sig.lot_size * lots,
            mode="paper",
            status=TradeStatus.OPEN,
            entry_time=datetime.utcnow(),
            target_price=sig.target_price,
            stop_loss=sig.stop_loss,
        )
        db.add(trade)

        # Deduct from portfolio
        portfolio.capital_deployed += cost
        portfolio.capital_current -= cost

        logger.info(f"Auto paper trade: {sig.underlying} {sig.instrument} @ ₹{premium:.2f} × {sig.lot_size}")

    await db.commit()


async def _do_scan(symbols: list[str], timeframes: list[str]):
    """Core scan logic — used by all scheduled tasks."""
    from app.core.scanner import run_full_scan
    from app.database import AsyncSessionLocal
    from app.api.websocket import manager

    async with AsyncSessionLocal() as db:
        result = await run_full_scan(
            symbols=symbols,
            timeframes=timeframes,
            broadcast_fn=manager.broadcast,
            db=db,
        )
        await _persist_and_broadcast(result["signals"], db, manager.broadcast)
    return result


@celery_app.task(name="workers.scan_priority_instruments", bind=True, max_retries=2)
def scan_priority_instruments(self, timeframes: list[str] | None = None):
    """Scan high-liquidity instruments on short timeframes."""
    from app.core.instruments import priority_scan_list
    symbols = priority_scan_list()
    tfs = timeframes or ["15m", "1h"]
    logger.info(f"Priority scan: {len(symbols)} symbols × {tfs}")
    try:
        return _run_async(_do_scan(symbols, tfs))
    except Exception as exc:
        logger.error(f"Priority scan failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="workers.scan_all_instruments", bind=True, max_retries=2)
def scan_all_instruments(self, timeframes: list[str] | None = None):
    """Scan full F&O universe across longer timeframes."""
    from app.core.instruments import all_symbols
    symbols = all_symbols()
    tfs = timeframes or ["1h", "4h", "daily"]
    logger.info(f"Full scan: {len(symbols)} symbols × {tfs}")
    try:
        return _run_async(_do_scan(symbols, tfs))
    except Exception as exc:
        logger.error(f"Full scan failed: {exc}")
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(name="workers.run_signal_scan")
def run_signal_scan(underlying: str = "NIFTY"):
    """Ad-hoc single-symbol scan (called from API)."""
    return _run_async(_do_scan([underlying], ["15m", "1h", "daily"]))


@celery_app.task(name="workers.sync_market_data")
def sync_market_data(underlying: str = "NIFTY"):
    """Sync latest market data (stub — real impl uses KiteAdapter)."""
    return {"status": "ok", "underlying": underlying, "timestamp": datetime.utcnow().isoformat()}
