"""Options API endpoints — regime, IV rank, chain, max pain, events, expiry, risk."""
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.options.regime import RegimeDetector
from app.core.options.chain_service import ChainService
from app.core.options.iv_rank import IVRankService
from app.core.options.max_pain import compute_max_pain
from app.core.options.event_calendar import EventCalendar
from app.core.options.greeks import compute_greeks, RISK_FREE_RATE
from app.core.options.expiry import available_expiries, select_expiry
from app.core.instruments import BASE_PRICES
from app.core import risk

router = APIRouter()


def _spot(underlying: str) -> float:
    """Use current live price snapshot, fall back to base_price."""
    try:
        from app.core.data.kite_ticker import ticker_service
        snap = ticker_service.get_snapshot()
        if underlying.upper() in snap:
            return snap[underlying.upper()]["ltp"]
    except Exception:
        pass
    return float(BASE_PRICES.get(underlying.upper(), 1500))


def _synthetic_ohlcv(underlying: str, rows: int = 120) -> pd.DataFrame:
    """Minimal OHLCV for regime detection — seed includes today's date so regime varies day-to-day."""
    import numpy as np
    from datetime import datetime
    today_ord = datetime.today().toordinal()
    seed = abs(hash(f"{underlying}_{today_ord}")) % (2**31)
    rng = np.random.default_rng(seed)
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
    # Pass real VIX if available so volatility regime reflects actual market fear
    vix_level = 0.0
    try:
        from app.core.backtest.market_data import fetch_india_vix
        vix_df = fetch_india_vix(days=5)
        if vix_df is not None and not vix_df.empty:
            vix_level = float(vix_df.iloc[-1]["vix"])
    except Exception:
        pass
    regime = RegimeDetector().detect(ohlcv, india_vix=vix_level)
    return {"underlying": underlying, "regime": regime}


@router.get("/iv-rank/{underlying}")
async def get_iv_rank(underlying: str):
    """Get IV rank, percentile, and strategy bias."""
    chain_svc = ChainService()
    iv_history = chain_svc.get_iv_history(underlying)

    # Derive current IV from ATM chain rather than random synthetic value
    spot = _spot(underlying)
    chain_df = chain_svc.get_chain(underlying)
    try:
        atm_strike = min(chain_df["strike"].unique(), key=lambda s: abs(s - spot))
        atm_row = chain_df[chain_df["strike"] == atm_strike].iloc[0]
        ce_iv = float(atm_row.get("ce_iv") or 0)
        pe_iv = float(atm_row.get("pe_iv") or 0)
        raw_iv = (ce_iv + pe_iv) / 2 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv)
        current_iv = raw_iv * 100 if raw_iv < 2.0 else raw_iv
        if current_iv <= 0:
            current_iv = float(_synthetic_ohlcv(underlying)["iv"].iloc[-1])
    except Exception:
        current_iv = float(_synthetic_ohlcv(underlying)["iv"].iloc[-1])

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
    """Get options chain with Greeks, IV rank, max pain, and regime in one call."""
    chain_svc = ChainService()
    chain_df = chain_svc.get_chain(underlying)
    spot = _spot(underlying)

    # IV rank — use ATM chain IV rather than random synthetic value
    iv_history = chain_svc.get_iv_history(underlying)
    try:
        atm_strike = min(chain_df["strike"].unique(), key=lambda s: abs(s - spot))
        atm_row = chain_df[chain_df["strike"] == atm_strike].iloc[0]
        ce_iv = float(atm_row.get("ce_iv") or 0)
        pe_iv = float(atm_row.get("pe_iv") or 0)
        raw_iv = (ce_iv + pe_iv) / 2 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv)
        # Chain stores IV as fraction (0.18); IVRankService expects percentage (18.0)
        current_iv = raw_iv * 100 if raw_iv < 2.0 else raw_iv
        if current_iv <= 0:
            current_iv = float(_synthetic_ohlcv(underlying)["iv"].iloc[-1])
    except Exception:
        current_iv = float(_synthetic_ohlcv(underlying)["iv"].iloc[-1])
    iv_rank   = IVRankService.iv_rank(current_iv, iv_history)
    iv_regime = IVRankService.iv_regime(iv_rank)

    # Max pain
    from app.core.options.max_pain import compute_max_pain
    try:
        mp_result   = compute_max_pain(chain_df[["strike", "ce_oi", "pe_oi"]])
        max_pain    = mp_result.get("max_pain_strike")
    except Exception:
        max_pain = None

    # Regime
    ohlcv = _synthetic_ohlcv(underlying)
    regime = RegimeDetector().detect(ohlcv)

    # Convert to list of dicts, handle NaN
    records = chain_df.where(pd.notnull(chain_df), None).to_dict(orient="records")

    return {
        "underlying": underlying,
        "spot": spot,
        "chain": records,
        "total_strikes": len(records),
        "iv_rank": round(iv_rank, 4),
        "iv_regime": iv_regime,
        "max_pain": max_pain,
        "regime": regime,
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


# ── Expiry endpoints ──────────────────────────────────────────────────────────

@router.get("/expiry/{underlying}")
async def get_expiries(underlying: str):
    """Return all available expiry dates for an underlying with DTE."""
    expiries = available_expiries(underlying.upper())
    if not expiries:
        raise HTTPException(404, f"Unknown underlying: {underlying}")
    return {
        "underlying": underlying.upper(),
        "expiries": expiries,
        "next": expiries[0],
    }


@router.get("/expiry/{underlying}/select")
async def select_best_expiry(underlying: str, dte: int = 7):
    """Pick the most appropriate expiry given a DTE preference."""
    expiry = select_expiry(underlying.upper(), dte_preference=dte)
    return {"underlying": underlying.upper(), "dte_preference": dte, "selected": expiry}


# ── Risk / Kill-switch endpoints ──────────────────────────────────────────────

@router.get("/risk/status")
async def risk_status():
    """Current risk gate status: halt flag, daily P&L, portfolio heat."""
    from app.core.risk.gate import halt_status, get_daily_pnl
    import redis as _redis
    from app.config import settings

    r = _redis.from_url(settings.redis_url, decode_responses=True)
    deployed = float(r.get("daily_deployed") or 0)

    return {
        **halt_status(),
        "daily_pnl":       round(get_daily_pnl(), 2),
        "capital_deployed": round(deployed, 2),
        "capital":         settings.paper_capital,
    }


class HaltRequest(BaseModel):
    reason: str = "manual halt"


@router.post("/risk/halt")
async def trigger_halt(body: HaltRequest):
    """Immediately halt all automated trading."""
    from app.core.risk.gate import halt_trading
    halt_trading(body.reason)
    return {"halted": True, "reason": body.reason}


@router.post("/risk/resume")
async def trigger_resume():
    """Resume trading after a halt."""
    from app.core.risk.gate import resume_trading
    resume_trading()
    return {"halted": False}
