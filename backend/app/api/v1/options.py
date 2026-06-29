"""Options API endpoints — regime, IV rank, chain, max pain, events."""
from datetime import date

import numpy as np
import pandas as pd
from fastapi import APIRouter

from app.core.options.regime import RegimeDetector
from app.core.options.chain_service import ChainService
from app.core.options.iv_rank import IVRankService
from app.core.options.max_pain import compute_max_pain
from app.core.options.event_calendar import EventCalendar
from app.core.options.greeks import compute_greeks, RISK_FREE_RATE

router = APIRouter()

SPOT_PRICES = {
    "NIFTY": 24300, "BANKNIFTY": 52700, "FINNIFTY": 23400,
    "MIDCPNIFTY": 12640, "HDFCBANK": 1840, "ICICIBANK": 1375,
    "RELIANCE": 2970, "TATAMOTORS": 978, "INFY": 1920,
}


def _spot(underlying: str) -> float:
    return float(SPOT_PRICES.get(underlying.upper(), 1500))


def _synthetic_ohlcv(underlying: str, rows: int = 120) -> pd.DataFrame:
    """Minimal OHLCV for regime detection."""
    import numpy as np
    from datetime import datetime
    rng = np.random.default_rng(abs(hash(underlying)) % (2**31))
    base = _spot(underlying)
    close = base + np.cumsum(rng.normal(0, base * 0.006, rows))
    open_ = close * (1 + rng.normal(0, 0.003, rows))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.008, rows))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.008, rows))
    dates = pd.date_range(end=datetime.today(), periods=rows, freq="D")
    return pd.DataFrame({
        "timestamp": dates,
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "volume": rng.integers(500_000, 5_000_000, rows).astype(float),
        "oi": rng.integers(5_000_000, 15_000_000, rows).astype(float),
        "iv": np.round(rng.uniform(12, 28, rows), 2),
    })


@router.get("/regime/{underlying}")
async def get_regime(underlying: str):
    """Detect current market regime for an underlying."""
    ohlcv = _synthetic_ohlcv(underlying)
    regime = RegimeDetector().detect(ohlcv)
    return {"underlying": underlying, "regime": regime}


@router.get("/iv-rank/{underlying}")
async def get_iv_rank(underlying: str):
    """Get IV rank, percentile, and strategy bias."""
    chain_svc = ChainService()
    iv_history = chain_svc.get_iv_history(underlying)

    ohlcv = _synthetic_ohlcv(underlying)
    current_iv = float(ohlcv["iv"].iloc[-1])

    iv_rank = IVRankService.iv_rank(current_iv, iv_history)
    iv_pct = IVRankService.iv_percentile(current_iv, iv_history)
    iv_regime = IVRankService.iv_regime(iv_rank)
    bias = IVRankService.strategy_bias(iv_rank)

    return {
        "underlying": underlying,
        "current_iv": round(current_iv, 2),
        "iv_rank": round(iv_rank, 4),
        "iv_percentile": round(iv_pct, 4),
        "iv_regime": iv_regime,
        "strategy_bias": bias,
        "iv_history_days": len(iv_history),
    }


@router.get("/chain/{underlying}")
async def get_chain(underlying: str):
    """Get options chain with Greeks for all strikes."""
    chain_svc = ChainService()
    chain_df = chain_svc.get_chain(underlying)

    # Convert to list of dicts, handle NaN
    records = chain_df.where(pd.notnull(chain_df), None).to_dict(orient="records")

    return {
        "underlying": underlying,
        "spot": _spot(underlying),
        "chain": records,
        "total_strikes": len(records),
    }


@router.get("/max-pain/{underlying}")
async def get_max_pain(underlying: str):
    """Calculate max pain strike from options chain."""
    chain_svc = ChainService()
    chain_df = chain_svc.get_chain(underlying)

    result = compute_max_pain(chain_df[["strike", "ce_oi", "pe_oi"]])

    # Trim pain_data for response (only include top-10 closest to max pain)
    mp_strike = result["max_pain_strike"]
    pain_data = sorted(result["pain_data"], key=lambda x: abs(x["strike"] - mp_strike))[:20]

    return {
        "underlying": underlying,
        "spot": _spot(underlying),
        "max_pain_strike": result["max_pain_strike"],
        "pcr": result["pcr"],
        "total_oi": result["total_oi"],
        "ce_oi_total": result["ce_oi_total"],
        "pe_oi_total": result["pe_oi_total"],
        "nearest_pain_data": pain_data,
    }


@router.get("/events")
async def get_events(count: int = 5):
    """Get upcoming NSE and global market events."""
    cal = EventCalendar()
    today = date.today()
    events = cal.next_events(today, count=count)
    days_to_next = cal.days_to_next_event(today)
    event_risk = cal.is_event_risk(today)

    return {
        "today": today.isoformat(),
        "days_to_next_event": days_to_next,
        "event_risk": event_risk,
        "upcoming_events": events,
    }
