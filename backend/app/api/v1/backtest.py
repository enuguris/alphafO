"""Backtest API endpoints — replay pattern engine on Kite historical data."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import date
from loguru import logger

from app.database import get_db
from app.models.backtest import BacktestRun

router = APIRouter()


class BacktestRequest(BaseModel):
    underlying: str
    start_date: date
    end_date: date
    patterns: list[str] | None = None
    initial_capital: float = 500000.0
    name: str = "Backtest Run"


@router.post("/run")
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """Replay the pattern engine on Kite historical OHLCV for the given range."""
    from app.core.data.kite_adapter import KiteAdapter
    from app.core.patterns.registry import PatternRegistry
    from app.core.scanner import _resolve_nse_token, synthetic_ohlcv
    import pandas as pd

    adapter = KiteAdapter()

    # Resolve token without calling instruments() (rate-limited)
    token = _resolve_nse_token(req.underlying)
    df: pd.DataFrame | None = None

    if adapter.is_configured() and token:
        try:
            df = adapter.get_historical(token, req.start_date, req.end_date, "day")
        except Exception as e:
            logger.warning(f"Backtest Kite fetch failed: {e}")

    if df is None or df.empty:
        # Fall back to synthetic — at least validates the engine
        df = synthetic_ohlcv(req.underlying, "daily")
        source = "synthetic"
    else:
        source = "kite"

    if "iv" not in df.columns:
        import numpy as np
        rng = __import__("numpy").random.default_rng(42)
        df["iv"] = rng.uniform(12, 28, len(df))
    if "oi" not in df.columns:
        df["oi"] = 0.0

    registry = PatternRegistry.get()
    window = min(120, len(df) // 2)
    results = []

    for i in range(window, len(df)):
        window_df = df.iloc[i - window:i].copy()
        for pattern in registry.all():
            if req.patterns and pattern.name not in req.patterns:
                continue
            try:
                sigs = pattern.detect(window_df, underlying=req.underlying)
                for sig in sigs:
                    if sig.confidence_score < 0.65:
                        continue
                    fwd = min(5, len(df) - i - 1)
                    entry = float(df["close"].iloc[i])
                    exit_ = float(df["close"].iloc[i + fwd]) if fwd > 0 else entry
                    ret_pct = (exit_ - entry) / entry * 100
                    if sig.direction == "short":
                        ret_pct = -ret_pct
                    results.append({
                        "date":        str(df["timestamp"].iloc[i])[:10],
                        "pattern":     pattern.name,
                        "direction":   sig.direction,
                        "confidence":  round(sig.confidence_score, 3),
                        "entry_price": round(entry, 2),
                        "exit_price":  round(exit_, 2),
                        "return_pct":  round(ret_pct, 2),
                    })
            except Exception:
                pass
        await asyncio.sleep(0)  # yield to event loop between bars

    wins = sum(1 for r in results if r["return_pct"] > 0)
    total_return = sum(r["return_pct"] for r in results)

    # Sharpe ratio: mean return / std dev of returns (annualised)
    import math as _math
    sharpe = None
    if len(results) >= 5:
        rets = [r["return_pct"] for r in results]
        mean_r = sum(rets) / len(rets)
        std_r = (_math.sqrt(sum((x - mean_r) ** 2 for x in rets) / len(rets))) if len(rets) > 1 else 0
        sharpe = round(mean_r / std_r * _math.sqrt(252), 2) if std_r > 0 else 0.0

    import json
    run = BacktestRun(
        name=req.name,
        pattern_names=",".join(req.patterns) if req.patterns else "all",
        underlying=req.underlying,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        final_capital=req.initial_capital * (1 + total_return / 100),
        total_return_pct=round(total_return, 2),
        max_drawdown_pct=0.0,
        sharpe_ratio=sharpe,
        total_trades=len(results),
        win_rate=round(wins / len(results) * 100, 1) if results else 0,
        report_json=json.dumps({"data_source": source, "trades": results[:200]}),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "run_id":          run.id,
        "underlying":      req.underlying,
        "start_date":      str(req.start_date),
        "end_date":        str(req.end_date),
        "data_source":     source,
        "bars_analysed":   len(df) - window,
        "signals_found":   len(results),
        "win_rate":        run.win_rate,
        "total_return_pct": run.total_return_pct,
        "trades":          results,
    }


def _redis_conn():
    import redis as _r
    from app.config import settings as _st
    return _r.from_url(_st.redis_url, decode_responses=True)

SAVED_LIST_KEY = "bt_saved:list"
SAVED_TTL      = 86400 * 30   # 30 days


@router.get("/credit-spreads/saved")
async def list_saved_backtests():
    """Return the list of saved backtest runs (metadata only, no full data)."""
    import json as _json
    try:
        r = _redis_conn()
        raw = r.lrange(SAVED_LIST_KEY, 0, 49)
        return {"saved": [_json.loads(x) for x in raw]}
    except Exception:
        return {"saved": []}


@router.get("/credit-spreads/saved/{run_id}")
async def load_saved_backtest(run_id: str):
    """Load the full result for a saved backtest run."""
    import json as _json
    try:
        r = _redis_conn()
        raw = r.get(f"bt_saved:data:{run_id}")
        if not raw:
            raise HTTPException(404, "Saved run not found")
        return _json.loads(raw)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/credit-spreads/saved/{run_id}")
async def delete_saved_backtest(run_id: str):
    """Delete a saved backtest run."""
    import json as _json
    try:
        r = _redis_conn()
        r.delete(f"bt_saved:data:{run_id}")
        # Remove from list
        raw_list = r.lrange(SAVED_LIST_KEY, 0, 199)
        r.delete(SAVED_LIST_KEY)
        for item in raw_list:
            meta = _json.loads(item)
            if meta.get("id") != run_id:
                r.rpush(SAVED_LIST_KEY, item)
        return {"deleted": run_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/credit-spreads/save")
async def save_backtest_result(name: str, from_date: str | None = None, to_date: str | None = None):
    """Save the most recent cached result for a date range under a user-defined name."""
    import json as _json, uuid as _uuid, time as _time
    CACHE_KEY = f"credit_spread_backtest:v2:{from_date or 'all'}:{to_date or 'all'}"
    try:
        r = _redis_conn()
        cached = r.get(CACHE_KEY)
        if not cached:
            raise HTTPException(400, "No cached result for this date range — run the backtest first")
        run_id  = str(_uuid.uuid4())[:8]
        meta    = {
            "id":         run_id,
            "name":       name,
            "from_date":  from_date,
            "to_date":    to_date,
            "saved_at":   _time.strftime("%Y-%m-%d %H:%M IST", _time.gmtime(_time.time() + 19800)),
        }
        r.set(f"bt_saved:data:{run_id}", cached, ex=SAVED_TTL)
        r.lpush(SAVED_LIST_KEY, _json.dumps(meta))   # newest first
        r.ltrim(SAVED_LIST_KEY, 0, 49)               # keep last 50
        r.expire(SAVED_LIST_KEY, SAVED_TTL)
        return {"saved": True, "id": run_id, "name": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/credit-spreads/data-range")
async def credit_spread_data_range():
    """Return the available bhav data date range without running any backtest."""
    try:
        from app.core.backtest.market_data import build_ohlcv_from_bhav
        import pandas as _pd
        df = build_ohlcv_from_bhav("NIFTY", rows=800)
        if df is not None and "timestamp" in df.columns:
            dates = _pd.to_datetime(df["timestamp"]).dt.date
            return {"data_start": str(dates.min()), "data_end": str(dates.max()), "bars": len(df)}
    except Exception:
        pass
    return {"data_start": None, "data_end": None, "bars": 0}


@router.post("/credit-spreads/run")
async def run_credit_spread_backtest(
    from_date: str | None = None,
    to_date:   str | None = None,
    exit_regime: str = "classic",
    strike_mode: str = "atm",
    entry_mode: str = "trend",
):
    """
    Explicitly run the credit spread backtest. Always executes fresh (no cache read).
    Stores result in cache for 24h so it survives page reloads.
    exit_regime: "classic" (TP 70% credit, SL 50% max risk, hold to expiry)
                 "managed" (TP 50% credit, SL 2x credit, time-exit at 50% DTE)
    strike_mode: "atm" (sell at/near the money — max premium, ~50% POP)
                 "otm" (sell the ~30-delta strike — less premium, higher POP)
    """
    import json as _json
    CACHE_KEY = (f"credit_spread_backtest:v2:{from_date or 'all'}:{to_date or 'all'}"
                 f":{exit_regime}:{strike_mode}:{entry_mode}")
    CACHE_TTL = 86400   # 24 hours — survive page reloads

    import asyncio
    result = await asyncio.get_running_loop().run_in_executor(
        None, _run_credit_spread_backtest, from_date, to_date, exit_regime, strike_mode,
        entry_mode,
    )

    try:
        r = _redis_conn()
        r.setex(CACHE_KEY, CACHE_TTL, _json.dumps(result))
    except Exception:
        pass

    return result


@router.get("/credit-spreads")
async def credit_spread_backtest(
    from_date: str | None = None,
    to_date:   str | None = None,
):
    """
    Return cached backtest results for this date range. Does NOT run a new backtest.
    Returns 204 (no content) if no cached result exists — client should call /run.
    """
    import json as _json
    CACHE_KEY = f"credit_spread_backtest:v2:{from_date or 'all'}:{to_date or 'all'}"
    try:
        r = _redis_conn()
        cached = r.get(CACHE_KEY)
        if cached:
            return _json.loads(cached)
    except Exception:
        pass
    from fastapi.responses import Response
    return Response(status_code=204)


@router.post("/credit-spreads/refresh")
async def refresh_credit_spread_backtest(
    from_date: str | None = None,
    to_date:   str | None = None,
):
    """Alias for /run — kept for backward compatibility."""
    import json as _json
    CACHE_KEY = f"credit_spread_backtest:v2:{from_date or 'all'}:{to_date or 'all'}"
    try:
        r = _redis_conn()
        r.delete(CACHE_KEY)
        r.delete("credit_spread_backtest:v1")
    except Exception:
        r = None

    import asyncio
    result = await asyncio.get_running_loop().run_in_executor(
        None, _run_credit_spread_backtest, from_date, to_date
    )

    try:
        if r:
            r.setex(CACHE_KEY, 3600, _json.dumps(result))
    except Exception:
        pass

    return result


def _run_credit_spread_backtest(from_date: str | None = None, to_date: str | None = None,
                                exit_regime: str = "classic",
                                strike_mode: str = "atm",
                                entry_mode: str = "trend") -> dict:
    """CPU-bound backtest logic — runs in executor thread."""
    import math
    from datetime import date, timedelta, datetime

    RF = 0.065
    # NSE lot sizes
    LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}

    # ── Black-Scholes ──────────────────────────────────────────────────────────
    def _norm_cdf(x):
        t = 1.0 / (1.0 + 0.2316419 * abs(x))
        poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
        cdf = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly
        return cdf if x >= 0 else 1.0 - cdf

    def bs(S, K, T, r, sigma, opt):
        if T <= 0 or sigma <= 0:
            return max(0.05, (S - K) if opt == "CE" else (K - S))
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        p = (S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)) if opt == "CE" \
            else (K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1))
        return max(0.05, p)

    def rnd_k(price, step):
        return int(round(price / step) * step)

    # ── Expiry helpers ─────────────────────────────────────────────────────────
    def next_tuesdays(from_dt, count=12):
        tues, d = [], from_dt
        while d.weekday() != 1:
            d += timedelta(days=1)
        for _ in range(count):
            tues.append(d)
            d += timedelta(days=7)
        return tues

    def select_expiry(entry_date, min_dte=7):
        for t in next_tuesdays(entry_date + timedelta(days=1)):
            if (t - entry_date).days >= min_dte:
                return t
        return None

    # ── Leg builders ──────────────────────────────────────────────────────────
    def _delta(S, K, T, r, sigma, opt):
        if T <= 0 or sigma <= 0:
            return 1.0 if (opt == "CE" and S > K) or (opt == "PE" and S < K) else 0.0
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        nd1 = _norm_cdf(d1)
        return nd1 if opt == "CE" else abs(nd1 - 1.0)

    def _delta_strike(spot, T, iv, opt, step, target=0.30):
        """Walk OTM from ATM until |delta| <= target (~30-delta short strike)."""
        atm = rnd_k(spot, step)
        k = atm
        for _ in range(20):
            k_next = k + step if opt == "CE" else k - step
            if _delta(spot, k_next, T, RF, iv, opt) < target:
                return k_next
            k = k_next
        return k

    def build_legs(strategy, spot, iv, ivr, dte, step, strike_mode="atm"):
        T = max(dte, 1) / 365.0
        offset = step if ivr > 0.55 else 0
        atm = rnd_k(spot, step)
        # "wide" variant: 4-step wings (200 pts NIFTY) — 2026 regime has median
        # daily move 155 pts, larger than the classic 2-step width
        wing_steps = 4 if strike_mode == "wide" else 2
        if strategy == "BullPut":
            if strike_mode == "otm":
                sk = _delta_strike(spot, T, iv, "PE", step)
                wk = sk - 2 * step
            else:
                sk, wk = atm - offset, atm - offset - wing_steps * step
            sp, wp = bs(spot, sk, T, RF, iv, "PE"), bs(spot, wk, T, RF, iv, "PE")
            wp = min(wp, sp * 0.70)
            return [("PE","SELL",sk,round(sp,2)),("PE","BUY",wk,round(wp,2))]
        elif strategy == "BearCall":
            if strike_mode == "otm":
                sk = _delta_strike(spot, T, iv, "CE", step)
                wk = sk + 2 * step
            else:
                sk, wk = atm + offset, atm + offset + wing_steps * step
            sp, wp = bs(spot, sk, T, RF, iv, "CE"), bs(spot, wk, T, RF, iv, "CE")
            wp = min(wp, sp * 0.70)
            return [("CE","SELL",sk,round(sp,2)),("CE","BUY",wk,round(wp,2))]
        elif strategy == "OvernightStrangle":
            # User's live strategy (Jul 2026): sell ~2.8%-OTM strangle on the
            # monthly (21-35 DTE), harvest one day of decay, exit next close.
            # Far wings (12 steps) approximate the naked position for the engine.
            pk = rnd_k(spot * 0.972, step)   # ~2.8% OTM put
            ck = rnd_k(spot * 1.024, step)   # ~2.4% OTM call (mirrors user's strikes)
            pw2, cw2 = pk - 12 * step, ck + 12 * step
            sp_s = bs(spot, pk, T, RF, iv, "PE"); wp_s = min(bs(spot, pw2, T, RF, iv, "PE"), sp_s * 0.30)
            sc_s = bs(spot, ck, T, RF, iv, "CE"); wc_s = min(bs(spot, cw2, T, RF, iv, "CE"), sc_s * 0.30)
            return [("PE","SELL",pk,round(sp_s,2)),("PE","BUY",pw2,round(wp_s,2)),
                    ("CE","SELL",ck,round(sc_s,2)),("CE","BUY",cw2,round(wc_s,2))]
        elif strategy == "BullCondor":
            # Skewed condor, bullish: main credit from near-ATM put spread +
            # extra credit from an OTM call spread. Wins on up AND sideways;
            # capped loss both directions.
            ps, pw = atm - offset, atm - offset - 2 * step        # put side (main)
            cs2, cw2 = atm + 2 * step, atm + 4 * step             # call side (kicker)
            sp_p = bs(spot, ps, T, RF, iv, "PE"); wp_p = min(bs(spot, pw, T, RF, iv, "PE"), sp_p * 0.70)
            sc_c = bs(spot, cs2, T, RF, iv, "CE"); wc_c = min(bs(spot, cw2, T, RF, iv, "CE"), sc_c * 0.70)
            return [("PE","SELL",ps,round(sp_p,2)),("PE","BUY",pw,round(wp_p,2)),
                    ("CE","SELL",cs2,round(sc_c,2)),("CE","BUY",cw2,round(wc_c,2))]
        elif strategy == "BearCondor":
            # Mirror: main credit from near-ATM call spread + OTM put spread kicker
            cs2, cw2 = atm + offset, atm + offset + 2 * step
            ps, pw = atm - 2 * step, atm - 4 * step
            sc_c = bs(spot, cs2, T, RF, iv, "CE"); wc_c = min(bs(spot, cw2, T, RF, iv, "CE"), sc_c * 0.70)
            sp_p = bs(spot, ps, T, RF, iv, "PE"); wp_p = min(bs(spot, pw, T, RF, iv, "PE"), sp_p * 0.70)
            return [("CE","SELL",cs2,round(sc_c,2)),("CE","BUY",cw2,round(wc_c,2)),
                    ("PE","SELL",ps,round(sp_p,2)),("PE","BUY",pw,round(wp_p,2))]
        elif strategy == "BullCallDebit":
            # Buy ATM CE, sell OTM CE 2 steps up — bullish, works when IV cheap
            bk, sk = atm, atm + 2 * step
            bp = bs(spot, bk, T, RF, iv, "CE")
            sp = min(bs(spot, sk, T, RF, iv, "CE"), bp * 0.60)
            return [("CE","BUY",bk,round(bp,2)),("CE","SELL",sk,round(sp,2))]
        elif strategy == "BearPutDebit":
            # Buy ATM PE, sell OTM PE 2 steps down — bearish, works when IV cheap
            bk, sk = atm, atm - 2 * step
            bp = bs(spot, bk, T, RF, iv, "PE")
            sp = min(bs(spot, sk, T, RF, iv, "PE"), bp * 0.60)
            return [("PE","BUY",bk,round(bp,2)),("PE","SELL",sk,round(sp,2))]
        elif strategy == "IronButterfly":
            # Sell ATM straddle + wings ADAPTIVELY placed just beyond the
            # straddle credit (the breakeven span), so max risk stays real
            # and the credit/width ratio lands inside the 20-80% gate.
            sc = bs(spot, atm, T, RF, iv, "CE")
            sp2 = bs(spot, atm, T, RF, iv, "PE")
            straddle = sc + sp2
            wing_steps = max(4, int(math.ceil(straddle * 1.15 / step)))
            wc_k, wp_k = atm + wing_steps*step, atm - wing_steps*step
            wc  = min(bs(spot, wc_k, T, RF, iv, "CE"), sc * 0.25)
            wp2 = min(bs(spot, wp_k, T, RF, iv, "PE"), sp2 * 0.25)
            return [("CE","SELL",atm,round(sc,2)),("PE","SELL",atm,round(sp2,2)),
                    ("CE","BUY",wc_k,round(wc,2)),("PE","BUY",wp_k,round(wp2,2))]
        else:  # IronCondor
            w = 3 if ivr > 0.65 else 2
            sc_k, sp_k = atm + w*step, atm - w*step
            wc_k, wp_k = sc_k + 2*step, sp_k - 2*step
            sc  = bs(spot, sc_k, T, RF, iv, "CE")
            sp2 = bs(spot, sp_k, T, RF, iv, "PE")
            wc  = min(bs(spot, wc_k, T, RF, iv, "CE"), sc * 0.55)
            wp2 = min(bs(spot, wp_k, T, RF, iv, "PE"), sp2 * 0.55)
            return [("CE","SELL",sc_k,round(sc,2)),("PE","SELL",sp_k,round(sp2,2)),
                    ("CE","BUY",wc_k,round(wc,2)),("PE","BUY",wp_k,round(wp2,2))]

    def net_credit(legs):
        return sum(p if a == "SELL" else -p for _,a,_,p in legs)

    def spread_width(legs, step):
        sells = [k for _,a,k,_ in legs if a == "SELL"]
        buys  = [k for _,a,k,_ in legs if a == "BUY"]
        return abs(sells[0] - buys[0]) if sells and buys else step * 2

    def reprice_legs(legs, spot, dte, iv):
        """Return per-leg current prices and net group P&L."""
        T = max(dte, 0.5) / 365.0
        total, leg_prices = 0.0, []
        for opt, action, strike, entry_p in legs:
            curr = bs(spot, strike, T, RF, iv, opt)
            leg_prices.append(round(curr, 2))
            total += (entry_p - curr) if action == "SELL" else (curr - entry_p)
        return total, leg_prices

    def intrinsic_legs(legs, spot):
        total, leg_prices = 0.0, []
        for opt, action, strike, entry_p in legs:
            intr = max(0.0, spot - strike) if opt == "CE" else max(0.0, strike - spot)
            leg_prices.append(round(intr, 2))
            total += (entry_p - intr) if action == "SELL" else (intr - entry_p)
        return total, leg_prices

    # ── NSE charges (Zerodha, Jul 2026) ───────────────────────────────────────
    def compute_charges(legs, exit_leg_prices, lot_size):
        """
        Compute all NSE F&O charges for one round-trip composite trade.
        Returns dict with per-component breakdown and total.
        """
        entry_buy_to  = sum(p * lot_size for _,a,_,p in legs if a == "BUY")
        entry_sell_to = sum(p * lot_size for _,a,_,p in legs if a == "SELL")
        exit_buy_to   = sum(ep * lot_size for ((_,a,_,_), ep) in zip(legs, exit_leg_prices) if a == "SELL")  # buying back shorts
        exit_sell_to  = sum(ep * lot_size for ((_,a,_,_), ep) in zip(legs, exit_leg_prices) if a == "BUY")   # selling longs

        total_turnover = entry_buy_to + entry_sell_to + exit_buy_to + exit_sell_to
        num_orders = len(legs) * 2  # entry + exit per leg

        brokerage      = min(20.0 * num_orders, total_turnover * 0.0003)  # ₹20/order, capped at 0.03%
        stt            = (entry_sell_to + exit_buy_to) * 0.001             # 0.1% on sell-side premium
        exchange_fee   = total_turnover * 0.00053                          # NSE 0.053%
        sebi_fee       = total_turnover * 0.000001                         # ₹1/lakh
        gst            = (brokerage + exchange_fee + sebi_fee) * 0.18
        stamp_duty     = (entry_buy_to + exit_sell_to) * 0.00003           # 0.003% on buy side
        total_charges  = brokerage + stt + exchange_fee + sebi_fee + gst + stamp_duty

        return {
            "brokerage":    round(brokerage, 2),
            "stt":          round(stt, 2),
            "exchange_fee": round(exchange_fee, 2),
            "sebi_fee":     round(sebi_fee, 2),
            "gst":          round(gst, 2),
            "stamp_duty":   round(stamp_duty, 2),
            "total":        round(total_charges, 2),
        }

    # ── Trade reason builder ───────────────────────────────────────────────────
    def build_reason(strategy, spot, sma, ivr, iv, dte, step):
        iv_pct = round(iv * 100, 1)
        ivr_pct = round(ivr * 100, 0)
        atm = rnd_k(spot, step)
        if strategy == "BullPut":
            return (f"Price ₹{spot:,.0f} above 10-SMA ₹{sma:,.0f} → bullish bias. "
                    f"IV rank {ivr_pct:.0f}% → selling OTM PE credit spread. "
                    f"IV {iv_pct}%, {dte}d to expiry. ATM={atm}.")
        elif strategy == "BearCall":
            return (f"Price ₹{spot:,.0f} below 10-SMA ₹{sma:,.0f} → bearish bias. "
                    f"IV rank {ivr_pct:.0f}% → selling OTM CE credit spread. "
                    f"IV {iv_pct}%, {dte}d to expiry. ATM={atm}.")
        elif strategy == "BullCallDebit":
            return (f"Price ₹{spot:,.0f} above 10-SMA ₹{sma:,.0f} + IV rank {ivr_pct:.0f}% (cheap) "
                    f"→ buying ATM CE / selling +2-step CE debit spread. Long direction with "
                    f"defined risk = debit paid. IV {iv_pct}%, {dte}d to expiry. ATM={atm}.")
        elif strategy == "BearPutDebit":
            return (f"Price ₹{spot:,.0f} below 10-SMA ₹{sma:,.0f} + IV rank {ivr_pct:.0f}% (cheap) "
                    f"→ buying ATM PE / selling −2-step PE debit spread. Short direction with "
                    f"defined risk = debit paid. IV {iv_pct}%, {dte}d to expiry. ATM={atm}.")
        elif strategy == "IronButterfly":
            return (f"IV rank {ivr_pct:.0f}% > 55% → very rich ATM premium, Iron Butterfly. "
                    f"Selling ATM straddle + buying ±3-step wings. Max profit if spot pins "
                    f"near {atm} at expiry. IV {iv_pct}%, {dte}d to expiry.")
        else:
            return (f"IV rank {ivr_pct:.0f}% > 40% threshold → elevated premium, Iron Condor. "
                    f"Selling OTM strangles both sides to collect theta. "
                    f"IV {iv_pct}%, {dte}d to expiry. ATM={atm}. "
                    f"Wide strikes ({'3-step' if ivr > 0.65 else '2-step'}) for safety margin.")

    # ── Main per-underlying runner ─────────────────────────────────────────────
    def run_one(underlying, step):
        lot_size = LOT_SIZES.get(underlying, 50)

        try:
            from app.core.backtest.market_data import build_ohlcv_from_bhav
            df = build_ohlcv_from_bhav(underlying, rows=800)
        except Exception as e:
            return {"underlying": underlying, "error": str(e), "strategies": []}

        if df is None or len(df) < 30:
            return {"underlying": underlying, "error": "insufficient data", "strategies": []}

        # Use the timestamp column for real dates (index is always integer)
        if "timestamp" in df.columns:
            import pandas as _pd
            df["_date"] = _pd.to_datetime(df["timestamp"]).dt.date
        else:
            # fallback: reconstruct dates from index position
            _n = len(df)
            df["_date"] = [date.today() - timedelta(days=_n - i) for i in range(_n)]

        # Apply date range filter on real dates
        if from_date or to_date:
            fd = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else None
            td = datetime.strptime(to_date,   "%Y-%m-%d").date() if to_date   else None
            mask = df["_date"].apply(lambda d: (fd is None or d >= fd) and (td is None or d <= td))
            n_keep = mask.sum()
            if n_keep < 20:
                actual_start = str(df["_date"].iloc[0])
                actual_end   = str(df["_date"].iloc[-1])
                return {"underlying": underlying,
                        "error": (f"Only {n_keep} bars in selected range. "
                                  f"Available data: {actual_start} → {actual_end}"),
                        "strategies": []}
            df = df[mask].reset_index(drop=True)

        closes = df["close"].values
        ivs    = df["iv"].values if "iv" in df.columns else [0.18] * len(df)

        def get_date(i):
            return df["_date"].iloc[i]

        def sma10(i):
            return float(sum(closes[max(0,i-10):i]) / min(10, i)) if i > 0 else float(closes[0])

        def ivrank(i):
            win = [float(ivs[j]) for j in range(max(0,i-252),i) if float(ivs[j]) > 0.01]
            if len(win) < 10: return 0.3
            lo, hi = min(win), max(win)
            return 0.3 if hi == lo else (float(ivs[i]) - lo) / (hi - lo)

        strategies = ["BullPut", "BearCall", "IronCondor",
                      "BullCallDebit", "BearPutDebit", "IronButterfly",
                      "BullCondor", "BearCondor", "OvernightStrangle"]
        last_entry = {s: -10 for s in strategies}
        all_trades: dict[str, list] = {s: [] for s in strategies}

        for i in range(20, len(df)):
            entry_date = get_date(i)
            spot = float(closes[i])
            iv   = float(ivs[i]) if float(ivs[i]) > 0.01 else 0.18
            if iv > 2.0: iv /= 100.0
            iv   = max(0.08, min(iv, 0.80))
            ivr  = ivrank(i)
            sma  = sma10(i)
            trend_up = spot > sma

            for strategy in strategies:
                _is_ons = strategy == "OvernightStrangle"
                # OvernightStrangle enters EVERY day (user's daily-harvest thesis)
                if i - last_entry[strategy] < (1 if _is_ons else 7):
                    continue

                expiry = select_expiry(entry_date, min_dte=(21 if _is_ons else 7))
                if not expiry:
                    continue
                dte = (expiry - entry_date).days

                # Vol-clustering filter (entry_mode suffix "_calm"): 10y data
                # shows the day after a >1.5% move is 71% more volatile than
                # average — skip new entries in the storm.
                if entry_mode.endswith("_calm"):
                    if i >= 1 and abs(closes[i] / closes[i-1] - 1) > 0.015:
                        continue

                # Entry filters. entry_mode:
                #  "trend" — sell puts above SMA, calls below (textbook momentum)
                #  "fade"  — sell puts BELOW SMA (dip = better forward returns in
                #            5y NIFTY data: +0.54%/wk vs +0.42% above SMA), calls above
                is_ranging = abs(spot / sma - 1) < 0.005 if sma > 0 else False
                _base_mode = entry_mode.replace("_calm", "")
                if strategy == "BullPut":
                    want_up = trend_up if _base_mode == "trend" else not trend_up
                    if not want_up:
                        continue
                if strategy == "BearCall":
                    want_dn = (not trend_up) if _base_mode == "trend" else trend_up
                    if not want_dn:
                        continue
                if strategy == "IronCondor" and ivr <= 0.40:
                    continue
                if strategy == "BullCondor" and not (trend_up if entry_mode == "trend" else not trend_up):
                    continue
                if strategy == "BearCondor" and (trend_up if entry_mode == "trend" else not trend_up):
                    continue
                if strategy == "BullCallDebit" and (not trend_up or ivr > 0.45):
                    continue
                if strategy == "BearPutDebit" and (trend_up or ivr > 0.45):
                    continue
                # Butterfly: enter the ~14% of days when price sits ON the SMA
                # (no directional signal at all) — the zone nothing else trades
                if strategy == "IronButterfly" and not is_ranging:
                    continue

                legs = build_legs(strategy, spot, iv, ivr, dte, step, strike_mode)
                nc   = net_credit(legs)
                sw   = spread_width(legs, step)
                is_debit = nc < 0

                if is_debit:
                    debit = -nc
                    # Debit must be < 60% of width or the reward isn't there
                    if debit > sw * 0.60 or debit < sw * 0.10:
                        continue
                    # Capital at risk = the debit paid
                    max_risk_per_unit = debit
                    capital_used = round(debit * lot_size, 2)
                    max_reward = sw - debit
                    take_profit = max_reward * 0.60          # 60% of max profit
                    stop_loss   = -(debit * 0.50)            # lose half the debit
                else:
                    # Credit must be 20-80% of width. Below 20% isn't worth the
                    # risk; above 80% is a BS pricing artifact (near-zero max
                    # risk → absurd % returns) — no real market fills there.
                    # (OvernightStrangle is exempt: far wings make credit/width
                    # tiny by construction — that IS the naked-risk profile.)
                    if not _is_ons and (nc < sw * 0.20 or nc > sw * 0.80):
                        continue
                    max_risk_per_unit = sw - nc
                    capital_used = round(max_risk_per_unit * lot_size, 2)
                    if exit_regime == "managed":
                        # High-win-rate regime: take profits early, cut losers at
                        # a multiple of credit (not of max risk), never hold late
                        take_profit = nc * 0.50
                        stop_loss   = -(nc * 2.0)
                    else:
                        target_pnl_pct = 0.06  # 6% target on capital
                        take_profit = max(nc * 0.70, capital_used * target_pnl_pct / lot_size)
                        stop_loss   = -(max_risk_per_unit * 0.50)

                exit_date = expiry
                exit_reason = "expiry"
                pnl = 0.0
                exit_leg_prices = [p for _,_,_,p in legs]  # default = entry prices

                for j in range(i+1, min(i+60, len(df))):
                    sim_date  = get_date(j)
                    sim_spot  = float(closes[j])
                    sim_iv    = float(ivs[j]) if float(ivs[j]) > 0.01 else iv
                    if sim_iv > 2.0: sim_iv /= 100.0
                    sim_iv    = max(0.08, min(sim_iv, 0.80))
                    sim_dte   = (expiry - sim_date).days

                    # OvernightStrangle: unconditional exit at the NEXT close —
                    # models the user's book-profit-next-day discipline
                    if _is_ons:
                        pnl, exit_leg_prices = reprice_legs(legs, sim_spot, sim_dte, sim_iv)
                        exit_date, exit_reason = sim_date, "time_exit"
                        break

                    if sim_date >= expiry or sim_dte <= 0:
                        pnl, exit_leg_prices = intrinsic_legs(legs, sim_spot)
                        exit_date, exit_reason = sim_date, "expiry"
                        break

                    unreal, curr_prices = reprice_legs(legs, sim_spot, sim_dte, sim_iv)
                    if unreal >= take_profit:
                        pnl, exit_leg_prices = unreal, curr_prices
                        exit_date, exit_reason = sim_date, "take_profit"
                        break
                    elif unreal <= stop_loss:
                        pnl, exit_leg_prices = unreal, curr_prices
                        exit_date, exit_reason = sim_date, "stop_loss"
                        break
                    elif exit_regime == "managed" and not is_debit and sim_dte <= dte * 0.5:
                        # Time exit: half the DTE burned without hitting either
                        # threshold — take whatever is on the table, avoid gamma
                        pnl, exit_leg_prices = unreal, curr_prices
                        exit_date, exit_reason = sim_date, "time_exit"
                        break
                else:
                    pnl, exit_leg_prices = intrinsic_legs(legs, float(closes[min(i+60, len(df)-1)]))

                charges = compute_charges(legs, exit_leg_prices, lot_size)
                pnl_after_charges = round(pnl - charges["total"] / lot_size, 2)
                pnl_on_capital_pct = round(pnl_after_charges * lot_size / max(capital_used, 1) * 100, 2)

                hold = (exit_date - entry_date).days

                # Build per-leg display: entry and exit prices
                leg_details = []
                for (opt,action,strike,entry_p), exit_p in zip(legs, exit_leg_prices):
                    prefix = "S" if action == "SELL" else "B"
                    leg_details.append({
                        "label":       f"{prefix}{int(strike)}{opt}",
                        "action":      action,
                        "opt_type":    opt,
                        "strike":      int(strike),
                        "entry_price": entry_p,
                        "exit_price":  round(exit_p, 2),
                        "pnl_per_unit": round((entry_p - exit_p) if action == "SELL" else (exit_p - entry_p), 2),
                    })

                all_trades[strategy].append({
                    "entry_date":          str(entry_date),
                    "exit_date":           str(exit_date),
                    "exit_reason":         exit_reason,
                    "spot":                round(spot, 0),
                    "net_credit":          round(nc, 2),
                    "spread_width":        round(sw, 2),
                    "capital_used":        capital_used,
                    "pnl":                 round(pnl, 2),
                    "pnl_after_charges":   pnl_after_charges,
                    "pnl_on_capital_pct":  pnl_on_capital_pct,
                    "charges":             charges,
                    "hold_days":           hold,
                    "iv_rank":             round(ivr, 3),
                    "iv_pct":              round(iv * 100, 1),
                    "reason":              build_reason(strategy, spot, sma, ivr, iv, dte, step),
                    "leg_details":         leg_details,
                    # legacy compact string for summary display
                    "legs": [f"{'S' if a=='SELL' else 'B'}{int(k)}{o}@{ep:.0f}→{xp:.0f}"
                             for (o,a,k,ep),xp in zip(legs, exit_leg_prices)],
                })
                last_entry[strategy] = i

        # ── Aggregate per strategy ─────────────────────────────────────────────
        strategies_out = []
        for strategy in strategies:
            trades = all_trades[strategy]
            if not trades:
                strategies_out.append({"strategy": strategy, "trades": 0})
                continue

            wins   = [t for t in trades if t["pnl_after_charges"] > 0]
            losses = [t for t in trades if t["pnl_after_charges"] <= 0]
            total_pnl = sum(t["pnl_after_charges"] * lot_size for t in trades)
            win_rate  = round(len(wins) / len(trades) * 100, 1)
            avg_win   = round(sum(t["pnl_after_charges"] for t in wins)   / len(wins),   2) if wins   else 0
            avg_loss  = round(sum(t["pnl_after_charges"] for t in losses) / len(losses), 2) if losses else 0
            pf = round((avg_win * len(wins)) / max(abs(avg_loss * len(losses)), 0.01), 2)
            avg_hold  = round(sum(t["hold_days"] for t in trades) / len(trades), 1)
            avg_credit= round(sum(t["net_credit"] for t in trades) / len(trades), 1)
            avg_capital = round(sum(t["capital_used"] for t in trades) / len(trades), 0)
            avg_pnl_pct = round(sum(t["pnl_on_capital_pct"] for t in trades) / len(trades), 2)
            total_charges = round(sum(t["charges"]["total"] for t in trades), 2)

            equity, peak, max_dd = 0.0, 0.0, 0.0
            equity_pts = []
            for t in sorted(trades, key=lambda x: x["exit_date"]):
                equity += t["pnl_after_charges"] * lot_size
                if equity > peak: peak = equity
                dd = peak - equity
                if dd > max_dd: max_dd = dd
                equity_pts.append({"date": t["exit_date"], "equity": round(equity, 2)})

            exit_counts = {
                "take_profit": sum(1 for t in trades if t["exit_reason"] in ("take_profit", "time_exit")),
                "stop_loss":   sum(1 for t in trades if t["exit_reason"] == "stop_loss"),
                "expiry":      sum(1 for t in trades if t["exit_reason"] == "expiry"),
            }

            strategies_out.append({
                "strategy":         strategy,
                "lot_size":         lot_size,
                "trades":           len(trades),
                "win_rate":         win_rate,
                "profit_factor":    pf,
                "total_pnl":        round(total_pnl, 2),
                "avg_credit":       avg_credit,
                "avg_win":          avg_win,
                "avg_loss":         avg_loss,
                "avg_hold_days":    avg_hold,
                "avg_capital_used": avg_capital,
                "avg_pnl_pct":      avg_pnl_pct,
                "total_charges":    total_charges,
                "max_drawdown":     round(max_dd, 2),
                "exit_counts":      exit_counts,
                "equity_curve":     equity_pts,
                "recent_trades":    sorted(trades, key=lambda x: x["entry_date"])[-20:],
            })

        return {
            "underlying":  underlying,
            "bars":        len(df),
            "step":        step,
            "lot_size":    lot_size,
            "strategies":  strategies_out,
        }

    from datetime import datetime as _dt
    # Detect the actual available date range from bhav files
    try:
        from app.core.backtest.market_data import build_ohlcv_from_bhav as _b
        _probe = _b("NIFTY")
        if _probe is not None and "timestamp" in _probe.columns:
            import pandas as _pd
            _dates = _pd.to_datetime(_probe["timestamp"]).dt.date
            _data_start = str(_dates.min())
            _data_end   = str(_dates.max())
        else:
            _data_start = _data_end = None
    except Exception:
        _data_start = _data_end = None

    results = [run_one("NIFTY", 50), run_one("BANKNIFTY", 100)]
    return {
        "results":     results,
        "run_at_ist":  (_dt.utcnow().strftime("%d %b %Y %H:%M") + " IST"),
        "from_date":   from_date,
        "to_date":     to_date,
        "data_start":  _data_start,
        "data_end":    _data_end,
        "version":     "v2",
    }


@router.get("/results")
async def list_backtests(limit: int = 20, db: AsyncSession = Depends(get_db)):
    q = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
    result = await db.execute(q)
    runs = result.scalars().all()
    return {"results": [r.__dict__ for r in runs], "count": len(runs)}


@router.get("/{run_id}")
async def get_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    q = select(BacktestRun).where(BacktestRun.id == run_id)
    result = await db.execute(q)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Backtest run not found")
    return run.__dict__
