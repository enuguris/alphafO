"""Signal API endpoints."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.signals import Signal
from app.core.signals.generator import SignalGenerator
from app.core.data.kite_adapter import KiteAdapter
import pandas as pd

router = APIRouter()
_kite = KiteAdapter()


@router.get("/")
async def list_signals(
    pattern: str | None = None,
    underlying: str | None = None,
    status: str = "active",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Signal).where(Signal.status == status)
    if pattern:
        q = q.where(Signal.pattern_name == pattern)
    if underlying:
        q = q.where(Signal.underlying == underlying)
    q = q.order_by(Signal.created_at.desc()).limit(limit)
    result = await db.execute(q)
    signals = result.scalars().all()
    return {"signals": [s.__dict__ for s in signals], "count": len(signals)}


@router.get("/{signal_id}")
async def get_signal(signal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(404, "Signal not found")
    return signal.__dict__


@router.post("/run")
async def run_signals(
    underlying: str = "NIFTY",
    patterns: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Fetch live data from Kite, run all patterns, and persist new signals."""
    if not _kite.is_configured():
        raise HTTPException(400, "Kite Connect not configured. Add credentials to .env")

    try:
        # Use nearest futures contract — has real volume and OI vs index which has none
        nfo = _kite.get_instruments("NFO")
        fut = nfo[(nfo["name"] == underlying.upper()) & (nfo["instrument_type"] == "FUT")].copy()
        if fut.empty:
            raise HTTPException(404, f"No futures found for {underlying}")
        fut["expiry"] = pd.to_datetime(fut["expiry"])
        nearest = fut.sort_values("expiry").iloc[0]
        token = int(nearest["instrument_token"])
        to_date = datetime.utcnow().date()
        from_date = to_date - timedelta(days=90)
        ohlcv = _kite.get_historical(token, from_date, to_date, "day")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Kite data fetch failed: {e}")

    # Fetch options chain for patterns that need it
    options_chain = None
    try:
        options_chain = _kite.get_options_chain(underlying)
    except Exception as e:
        pass  # proceed without options chain; OHLCV-only patterns will still run

    generator = SignalGenerator()
    raw_signals = generator.run(ohlcv, options_chain=options_chain, underlying=underlying, pattern_filter=patterns)

    saved = []
    for s in raw_signals:
        db_signal = Signal(
            pattern_name=s.pattern_name,
            pattern_version=s.pattern_version,
            symbol=s.symbol or underlying,
            underlying=s.underlying or underlying,
            instrument=s.instrument or underlying,
            direction=s.direction,
            entry_price=s.entry_price,
            target_price=s.target_price,
            stop_loss=s.stop_loss,
            expected_return_pct=s.expected_return_pct,
            confidence_score=s.confidence_score,
            explanation=s.explanation,
            trading_style=s.trading_style,
            expiry_date=s.expiry_date,
            valid_until=datetime.utcnow() + timedelta(hours=24),
        )
        db.add(db_signal)
        saved.append(s.pattern_name)

    await db.commit()
    return {"message": f"Signal run complete for {underlying}", "signals_found": len(saved), "patterns": saved}
