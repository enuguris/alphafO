"""Signal API endpoints."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, AppMode
from app.database import get_db
from app.models.signals import Signal, SignalStatus
from app.core.signals.generator import SignalGenerator

router = APIRouter()


# ── Synthetic data for testing mode ──────────────────────────────────────────

def _synthetic_ohlcv(underlying: str, rows: int = 120) -> pd.DataFrame:
    """
    Generate realistic OHLCV that reliably triggers several patterns:
    - Last candle has a 1.0–1.5% gap up (gap_fill)
    - Last 10 rows have tight range (BB squeeze → mean_reversion)
    - OI and price trend consistently for the last 5 rows (oi_buildup, vwap_oi)
    """
    rng = np.random.default_rng(abs(hash(underlying)) % (2**31))
    base = {"NIFTY": 24300, "BANKNIFTY": 52700, "FINNIFTY": 23400,
            "MIDCPNIFTY": 12640, "HDFCBANK": 1840, "ICICIBANK": 1375,
            "RELIANCE": 2970, "TATAMOTORS": 978, "INFY": 1920}.get(underlying, 1500)

    # Body: normal random walk for first (rows-10) candles
    body_len = rows - 10
    close_body = base + np.cumsum(rng.normal(0, base * 0.006, body_len))

    # Squeeze zone: last 10 candles with very tight range (triggers BB squeeze)
    squeeze_base = close_body[-1]
    squeeze_drift = np.linspace(0, squeeze_base * 0.005, 10)  # tiny upward drift
    close_squeeze = squeeze_base + squeeze_drift + rng.normal(0, squeeze_base * 0.0005, 10)

    close_arr = np.concatenate([close_body, close_squeeze])

    # Build open/high/low for full series
    open_arr  = close_arr * (1 + rng.normal(0, 0.003, rows))
    high_arr  = np.maximum(open_arr, close_arr) * (1 + rng.uniform(0.001, 0.008, rows))
    low_arr   = np.minimum(open_arr, close_arr) * (1 - rng.uniform(0.001, 0.008, rows))

    # Inject 1.2% gap UP on last candle (triggers gap_fill)
    open_arr[-1] = close_arr[-2] * 1.012

    # OI: rising in last 5 rows with rising price (triggers oi_buildup)
    oi_base = rng.integers(5_000_000, 15_000_000)
    oi_arr  = np.full(rows, float(oi_base))
    for i in range(rows - 5, rows):
        oi_arr[i] = oi_arr[i-1] * rng.uniform(1.02, 1.06)

    dates = pd.date_range(end=datetime.today(), periods=rows, freq="D")
    return pd.DataFrame({
        "timestamp": dates,
        "open":      np.round(open_arr, 2),
        "high":      np.round(high_arr, 2),
        "low":       np.round(low_arr, 2),
        "close":     np.round(close_arr, 2),
        "volume":    rng.integers(500_000, 5_000_000, rows).astype(float),
        "oi":        np.round(oi_arr, 0),
        "iv":        np.round(rng.uniform(12, 28, rows), 2),
    })


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
    underlying: str,
    patterns: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Run pattern detection and persist new signals to DB."""

    # ── 1. Fetch OHLCV ────────────────────────────────────────────────────────
    ohlcv: pd.DataFrame
    data_source: str

    use_kite = (
        settings.app_mode != AppMode.TESTING
        and settings.kite_api_key
        and settings.kite_access_token
    )

    if use_kite:
        try:
            from app.core.data.kite_adapter import KiteAdapter
            adapter = KiteAdapter()
            # Map underlying name → Kite NFO instrument token
            instruments_df = adapter.get_instruments("NFO")
            fut = instruments_df[
                instruments_df["name"].str.upper() == underlying.upper()
            ].sort_values("expiry").head(1)
            if fut.empty:
                raise ValueError(f"No NFO instrument found for {underlying}")
            token = int(fut.iloc[0]["instrument_token"])
            from datetime import date, timedelta as td
            ohlcv = adapter.get_historical(token, date.today() - td(days=180), date.today())
            data_source = "kite"
        except Exception as exc:
            # fall back to synthetic if Kite fails
            ohlcv = _synthetic_ohlcv(underlying)
            data_source = f"synthetic (kite error: {exc})"
    else:
        ohlcv = _synthetic_ohlcv(underlying)
        data_source = "synthetic (testing mode)"

    if ohlcv.empty or len(ohlcv) < 30:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient OHLCV data for {underlying} (source: {data_source})"
        )

    # ── 2. Run pattern engine ─────────────────────────────────────────────────
    generator = SignalGenerator()
    raw_signals = generator.run(ohlcv, underlying=underlying, pattern_filter=patterns or None)

    if not raw_signals:
        return {
            "message": f"No patterns detected for {underlying}",
            "underlying": underlying,
            "data_source": data_source,
            "signals_created": 0,
        }

    # ── 3. Expire old active signals for this underlying ─────────────────────
    old_q = select(Signal).where(
        Signal.underlying == underlying,
        Signal.status == SignalStatus.ACTIVE,
    )
    old_result = await db.execute(old_q)
    for old_sig in old_result.scalars().all():
        old_sig.status = SignalStatus.EXPIRED

    # ── 4. Persist new signals ────────────────────────────────────────────────
    created = []
    valid_until = datetime.utcnow() + timedelta(hours=24)
    for s in raw_signals:
        sig = Signal(
            pattern_name       = s.pattern_name,
            pattern_version    = s.pattern_version,
            symbol             = s.symbol or underlying,
            underlying         = underlying,
            instrument         = s.instrument or underlying,
            direction          = s.direction,
            entry_price        = round(s.entry_price, 2),
            target_price       = round(s.target_price, 2),
            stop_loss          = round(s.stop_loss, 2),
            expected_return_pct = round(s.expected_return_pct, 2),
            confidence_score   = round(s.confidence_score, 4),
            explanation        = s.explanation,
            trading_style      = s.trading_style,
            status             = SignalStatus.ACTIVE,
            created_at         = datetime.utcnow(),
            valid_until        = valid_until,
        )
        db.add(sig)
        created.append(sig)

    await db.commit()
    for sig in created:
        await db.refresh(sig)

    return {
        "message": f"Scan complete — {len(created)} signal(s) generated for {underlying}",
        "underlying": underlying,
        "data_source": data_source,
        "signals_created": len(created),
        "signals": [s.__dict__ for s in created],
    }
