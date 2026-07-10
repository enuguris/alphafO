"""Options API endpoints — regime, IV rank, chain, max pain, events, expiry, risk."""
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

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
    """
    OHLCV for regime detection.
    Prefers real bhav data (FUTIDX closing prices from 253 cached files).
    Falls back to date-seeded synthetic random walk if bhav data insufficient.
    """
    import numpy as np
    from datetime import datetime
    try:
        from app.core.backtest.market_data import build_ohlcv_from_bhav
        real_df = build_ohlcv_from_bhav(underlying, rows=rows)
        if real_df is not None and len(real_df) >= 20:
            return real_df
    except Exception:
        pass
    # Fallback: date-seeded synthetic data
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


@router.get("/oi-walls")
async def get_oi_walls():
    """
    Latest NIFTY OI-wall snapshot (real support/resistance from OI concentration)
    across the next 6 expiries. Refreshed twice daily by the snapshot_oi_walls
    task (am 09:20 / pm 15:25 IST). Returns null if no snapshot has run yet.
    """
    import json as _json
    import redis as _redis
    from app.config import settings as _cfg
    try:
        r = _redis.from_url(_cfg.redis_url, decode_responses=True)
        raw = r.get("oi_walls:last")
        return _json.loads(raw) if raw else {"status": "no_snapshot_yet"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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
    """Current risk gate status: halt flag, daily P&L, portfolio heat, active params."""
    from app.core.risk.gate import halt_status, get_daily_pnl, get_risk_params
    import redis as _redis
    from app.config import settings

    r = _redis.from_url(settings.redis_url, decode_responses=True)
    deployed = float(r.get("daily_deployed") or 0)
    rp = get_risk_params()

    return {
        **halt_status(),
        "daily_pnl":           round(get_daily_pnl(), 2),
        "capital_deployed":    round(deployed, 2),
        "capital":             rp["paper_capital"],
        "max_heat_limit":      round(rp["paper_capital"] * rp["max_portfolio_heat"] / 100, 2),
        "max_daily_loss_limit": round(rp["paper_capital"] * rp["max_daily_loss_pct"] / 100, 2),
        "params":              rp,
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


class RiskParamsUpdate(BaseModel):
    max_portfolio_heat: float | None = None    # % of capital max deployed (e.g. 10.0 = 10%)
    max_daily_loss_pct: float | None = None    # % daily loss before halt (e.g. 3.0 = 3%)
    max_risk_per_trade: float | None = None    # % capital risked per trade (e.g. 2.0 = 2%)
    paper_capital: float | None = None         # Total paper capital in ₹
    max_concurrent_trades: int | None = None   # Max open trades at once


@router.get("/risk/params")
async def get_risk_params_endpoint():
    """Return current active risk parameters (Redis overrides + config defaults)."""
    from app.core.risk.gate import get_risk_params
    return get_risk_params()


@router.put("/risk/params")
async def update_risk_params(body: RiskParamsUpdate):
    """
    Update risk parameters dynamically — stored in Redis, take effect immediately.
    Pass only the fields you want to change.
    """
    from app.core.risk.gate import set_risk_params
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No parameters provided")
    result = set_risk_params(updates)
    return {"message": "Risk parameters updated", "params": result}


@router.delete("/risk/params")
async def reset_risk_params():
    """Reset risk parameters to config defaults (removes Redis overrides)."""
    import redis as _redis
    from app.config import settings as _s
    from app.core.risk.gate import RISK_PARAMS_KEY
    _redis.from_url(_s.redis_url, decode_responses=True).delete(RISK_PARAMS_KEY)
    from app.core.risk.gate import get_risk_params
    return {"message": "Risk parameters reset to defaults", "params": get_risk_params()}


# ── Progressive risk tiers + Go-Live readiness ────────────────────────────────

RISK_TIERS = [
    # (min corpus ₹, name, strategies allowed, max risk/trade %, max heat %)
    (0,          "T1 Defined-Risk Only", ["credit_spreads", "iron_condor", "calendar", "diagonal"], 2.0, 10.0),
    (2_500_000,  "T2 Add Debit Spreads", ["T1", "debit_spreads"], 2.5, 12.0),
    (5_000_000,  "T3 Add Ratio/Broken-Wing", ["T2", "ratio_spreads", "broken_wing"], 3.0, 15.0),
    (10_000_000, "T4 Full Book", ["T3", "naked_short_with_hedge_mandate"], 3.0, 20.0),
]

GO_LIVE_MIN_TRADES   = 100
GO_LIVE_MIN_WIN_RATE = 80.0   # %
GO_LIVE_MIN_PF       = 1.5
GO_LIVE_FLAG_KEY     = "go_live_requested"


@router.get("/risk/tier")
async def risk_tier():
    """Current progressive risk tier based on paper corpus size."""
    from app.core.risk.gate import get_risk_params
    rp = get_risk_params()
    corpus = float(rp.get("paper_capital") or 0)
    tier_idx = max(i for i, t in enumerate(RISK_TIERS) if corpus >= t[0])
    cur = RISK_TIERS[tier_idx]
    nxt = RISK_TIERS[tier_idx + 1] if tier_idx + 1 < len(RISK_TIERS) else None
    return {
        "corpus": corpus,
        "tier": tier_idx + 1,
        "tier_name": cur[1],
        "allowed_strategies": cur[2],
        "max_risk_per_trade_pct": cur[3],
        "max_heat_pct": cur[4],
        "next_tier_at": nxt[0] if nxt else None,
        "next_tier_name": nxt[1] if nxt else None,
        "ladder": [
            {"tier": i + 1, "min_corpus": t[0], "name": t[1],
             "max_risk_pct": t[3], "max_heat_pct": t[4], "active": i == tier_idx}
            for i, t in enumerate(RISK_TIERS)
        ],
    }


@router.get("/risk/go-live-status")
async def go_live_status(db: AsyncSession = Depends(get_db)):
    """
    Go-Live readiness: win rate, profit factor, and sample size across all
    CLOSED paper trades. The toggle stays locked until every criterion passes.
    Even when unlocked, live orders remain blocked by PAPER_ONLY_LOCK in
    tasks.py — removing that requires explicit written approval.
    """
    from sqlalchemy import text as _text
    import redis as _redis
    from app.config import settings as _s

    row = (await db.execute(_text("""
        SELECT count(*)                              AS total,
               count(*) FILTER (WHERE pnl > 0)       AS wins,
               COALESCE(sum(pnl) FILTER (WHERE pnl > 0), 0)      AS gross_win,
               COALESCE(abs(sum(pnl) FILTER (WHERE pnl < 0)), 0) AS gross_loss,
               count(DISTINCT date(exit_time))       AS trading_days,
               count(*) FILTER (WHERE entry_price_source IN ('kite','upstox')) AS real_priced
        FROM trades
        WHERE mode = 'PAPER' AND status IN ('CLOSED', 'EXPIRED') AND pnl IS NOT NULL
          AND COALESCE(leg_role,'') != 'manual'
    """))).mappings().first()

    total = int(row["total"] or 0)
    wins  = int(row["wins"] or 0)
    real_priced = int(row["real_priced"] or 0)
    win_rate = round(wins / total * 100, 1) if total else 0.0
    gl = float(row["gross_loss"] or 0)
    pf = round(float(row["gross_win"] or 0) / gl, 2) if gl > 0 else (99.0 if wins else 0.0)

    criteria = {
        "min_trades":   {"required": GO_LIVE_MIN_TRADES,   "actual": total,    "pass": total >= GO_LIVE_MIN_TRADES},
        "real_priced_trades": {"required": GO_LIVE_MIN_TRADES, "actual": real_priced,
                               "pass": real_priced >= GO_LIVE_MIN_TRADES},
        "win_rate_pct": {"required": GO_LIVE_MIN_WIN_RATE, "actual": win_rate, "pass": win_rate >= GO_LIVE_MIN_WIN_RATE},
        "profit_factor": {"required": GO_LIVE_MIN_PF,      "actual": pf,       "pass": pf >= GO_LIVE_MIN_PF},
    }
    all_pass = all(c["pass"] for c in criteria.values())

    r = _redis.from_url(_s.redis_url, decode_responses=True)
    requested = r.get(GO_LIVE_FLAG_KEY) == "1"

    return {
        "eligible": all_pass,
        "go_live_requested": requested,
        "live_trading_active": False,   # PAPER_ONLY_LOCK is permanent until manually removed
        "criteria": criteria,
        "trading_days": int(row["trading_days"] or 0),
        "note": ("Even when all criteria pass, real orders stay blocked by PAPER_ONLY_LOCK. "
                 "Enabling live trading requires code change + explicit written approval."),
    }


class GoLiveRequest(BaseModel):
    enable: bool


@router.post("/risk/go-live")
async def request_go_live(body: GoLiveRequest, db: AsyncSession = Depends(get_db)):
    """Set/clear the go-live request flag. Does NOT enable real orders."""
    import redis as _redis
    from app.config import settings as _s
    if body.enable:
        status = await go_live_status(db)
        if not status["eligible"]:
            raise HTTPException(400, "Go-Live criteria not met yet — see /risk/go-live-status")
    r = _redis.from_url(_s.redis_url, decode_responses=True)
    r.set(GO_LIVE_FLAG_KEY, "1" if body.enable else "0")
    return {"go_live_requested": body.enable,
            "note": "Real orders remain blocked by PAPER_ONLY_LOCK regardless of this flag."}
