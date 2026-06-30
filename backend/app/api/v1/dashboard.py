"""
Dashboard API — pre-market briefing, pattern performance summary, daily stats.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_

from app.database import get_db

router = APIRouter()


@router.get("/pre-market")
async def pre_market_briefing(db: AsyncSession = Depends(get_db)):
    """
    Pre-market briefing: VIX regime, PCR, FII positioning, today's bias,
    which patterns have edge and are aligned with current conditions.
    """
    import math
    import numpy as np

    briefing: dict = {
        "as_of": datetime.utcnow().isoformat(),
        "date": date.today().isoformat(),
    }

    # ── 1. India VIX ─────────────────────────────────────────────────────────
    vix_level = None
    vix_regime = "unknown"
    try:
        from app.core.data.kite_ticker import ticker_service
        snap = ticker_service.get_snapshot() or {}
        vix_level = snap.get("INDIAVIX", {}).get("ltp") or snap.get("VIX", {}).get("ltp")
    except Exception:
        pass

    if vix_level is None:
        try:
            from app.core.backtest.market_data import fetch_india_vix
            import asyncio
            vix_df = await asyncio.get_event_loop().run_in_executor(None, fetch_india_vix)
            if vix_df is not None and not vix_df.empty:
                vix_level = float(vix_df["close"].iloc[-1])
        except Exception:
            pass

    if vix_level:
        if vix_level < 13:
            vix_regime = "very_low"
            vix_signal = "Options cheap — good for directional buys"
        elif vix_level < 16:
            vix_regime = "low"
            vix_signal = "Options relatively cheap — favour buying"
        elif vix_level < 20:
            vix_regime = "normal"
            vix_signal = "Balanced — both buy and sell strategies viable"
        elif vix_level < 25:
            vix_regime = "elevated"
            vix_signal = "Options expensive — consider selling spreads"
        else:
            vix_regime = "high"
            vix_signal = "Fear spike — sell premium or wait for VIX to cool"
    else:
        vix_signal = "VIX data unavailable"

    briefing["vix"] = {
        "level": round(vix_level, 2) if vix_level else None,
        "regime": vix_regime,
        "signal": vix_signal,
    }

    # ── 2. NIFTY / BANKNIFTY spot & regime ───────────────────────────────────
    spot_data = {}
    for sym in ["NIFTY", "BANKNIFTY"]:
        try:
            from app.core.backtest.historical_data import fetch_historical_best
            df, _ = await fetch_historical_best(sym, "daily")
            if df is not None and len(df) >= 50:
                close = df["close"]
                ema20 = close.ewm(span=20).mean().iloc[-1]
                ema50 = close.ewm(span=50).mean().iloc[-1]
                last  = float(close.iloc[-1])
                prev  = float(close.iloc[-2])
                chg_pct = (last - prev) / prev * 100

                # RSI
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain.iloc[-1] / (loss.iloc[-1] + 1e-9)
                rsi = round(100 - 100 / (1 + rs), 1)

                # HV20
                log_ret = np.log(close / close.shift(1)).dropna()
                hv20 = round(float(log_ret.tail(20).std() * math.sqrt(252) * 100), 1)

                trend = "bullish" if ema20 > ema50 else ("bearish" if ema20 < ema50 else "ranging")
                spot_data[sym] = {
                    "last": round(last, 2),
                    "chg_pct": round(chg_pct, 2),
                    "ema20": round(ema20, 2),
                    "ema50": round(ema50, 2),
                    "trend": trend,
                    "rsi": rsi,
                    "hv20": hv20,
                }
        except Exception:
            spot_data[sym] = None

    briefing["market"] = spot_data

    # ── 3. PCR from latest market data cache ─────────────────────────────────
    pcr_data = {}
    try:
        from app.core.backtest.market_data import fetch_pcr_maxpain
        import asyncio
        for sym in ["NIFTY", "BANKNIFTY"]:
            pcr_df = await asyncio.get_event_loop().run_in_executor(
                None, fetch_pcr_maxpain, sym
            )
            if pcr_df is not None and not pcr_df.empty:
                latest = pcr_df.iloc[-1]
                pcr = float(latest.get("pcr", 0))
                max_pain = float(latest.get("max_pain", 0))
                if pcr > 0:
                    if pcr > 1.3:
                        pcr_signal = "Put heavy — market expects support, bullish bias"
                    elif pcr > 1.0:
                        pcr_signal = "Slightly put heavy — mild bullish bias"
                    elif pcr > 0.7:
                        pcr_signal = "Balanced / neutral"
                    else:
                        pcr_signal = "Call heavy — market expects resistance, bearish bias"
                    pcr_data[sym] = {
                        "pcr": round(pcr, 3),
                        "max_pain": round(max_pain, 0) if max_pain else None,
                        "signal": pcr_signal,
                    }
    except Exception:
        pass

    briefing["pcr"] = pcr_data

    # ── 4. FII net positioning ────────────────────────────────────────────────
    fii_data = None
    try:
        from app.core.backtest.market_data import fetch_fii_fo_data
        import asyncio
        fii_df = await asyncio.get_event_loop().run_in_executor(None, fetch_fii_fo_data)
        if fii_df is not None and not fii_df.empty:
            latest = fii_df.iloc[-1]
            net = float(latest.get("fii_net_idx", 0))
            if net > 2000:
                fii_signal = "FII strong buyers — bullish"
            elif net > 500:
                fii_signal = "FII net long — mild bullish"
            elif net > -500:
                fii_signal = "FII neutral"
            elif net > -2000:
                fii_signal = "FII net short — mild bearish"
            else:
                fii_signal = "FII strong sellers — bearish"
            fii_data = {
                "net_cr": round(net, 0),
                "signal": fii_signal,
                "date": str(latest.name)[:10] if hasattr(latest, "name") else None,
            }
    except Exception:
        pass

    briefing["fii"] = fii_data

    # ── 5. Today's best patterns based on conditions ──────────────────────────
    try:
        from app.models.discovered_pattern import DiscoveredPattern
        from app.models.pattern_backtest import PatternBacktest, BacktestStatus

        # Get patterns with proven edge (has_edge=True from backtests, or top by effect_size)
        dp_q = await db.execute(
            select(DiscoveredPattern).where(
                DiscoveredPattern.active == True,
                DiscoveredPattern.effect_size > 0,
            ).order_by(desc(DiscoveredPattern.has_edge), desc(DiscoveredPattern.effect_size)).limit(20)
        )
        patterns_with_edge = dp_q.scalars().all()

        recommended = []
        for dp in patterns_with_edge:
            # Score alignment with current conditions
            score = float(dp.effect_size or 0)
            features = dp.features or []

            # VIX alignment
            if vix_level:
                if any(f in features for f in ["vix_low", "iv_hv_spread_buy"]) and vix_level < 16:
                    score += 0.3
                if any(f in features for f in ["vix_crush", "vix_high"]) and vix_level > 20:
                    score += 0.2

            # Trend alignment
            nifty = spot_data.get("NIFTY", {}) or {}
            if nifty.get("trend") == "bullish" and dp.direction == "long":
                score += 0.2
            elif nifty.get("trend") == "bearish" and dp.direction == "short":
                score += 0.2

            # RSI alignment
            rsi = (spot_data.get(dp.underlying, {}) or {}).get("rsi", 50)
            if any(f in features for f in ["rsi_oversold"]) and rsi < 35:
                score += 0.25
            if any(f in features for f in ["rsi_overbought"]) and rsi > 65:
                score += 0.25

            from app.core.patterns.composite import generate_display_name
            recommended.append({
                "pattern_slug":   dp.pattern_slug,
                "display_name":   generate_display_name(features, dp.direction, dp.underlying),
                "underlying":     dp.underlying,
                "timeframe":      dp.timeframe,
                "direction":      dp.direction,
                "win_rate":       round(dp.win_rate or 0, 3),
                "effect_size":    round(dp.effect_size or 0, 3),
                "alignment_score": round(score, 3),
                "features":       features[:4],
            })

        recommended.sort(key=lambda x: x["alignment_score"], reverse=True)
        briefing["recommended_patterns"] = recommended[:6]
    except Exception as e:
        briefing["recommended_patterns"] = []

    # ── 6. Today's paper trade summary ───────────────────────────────────────
    try:
        from app.models.trades import Trade, TradeStatus, TradeMode
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)

        open_q = await db.execute(
            select(func.count(), func.sum(Trade.unrealized_pnl)).where(
                Trade.status == TradeStatus.OPEN,
                Trade.mode   == TradeMode.PAPER,
            )
        )
        open_count, open_pnl = open_q.one()

        closed_today_q = await db.execute(
            select(func.count(), func.sum(Trade.realized_pnl)).where(
                Trade.status  == TradeStatus.CLOSED,
                Trade.mode    == TradeMode.PAPER,
                Trade.exit_time >= today_start,
            )
        )
        closed_count, realized_today = closed_today_q.one()

        briefing["paper_summary"] = {
            "open_trades": open_count or 0,
            "unrealized_pnl": round(float(open_pnl or 0), 2),
            "closed_today": closed_count or 0,
            "realized_today": round(float(realized_today or 0), 2),
        }
    except Exception:
        briefing["paper_summary"] = None

    # ── 7. Key levels for the day ─────────────────────────────────────────────
    key_levels = {}
    for sym in ["NIFTY", "BANKNIFTY"]:
        sd = spot_data.get(sym)
        if not sd:
            continue
        spot = sd["last"]
        step = 50 if sym == "NIFTY" else 100
        atm  = round(spot / step) * step
        key_levels[sym] = {
            "spot":         spot,
            "atm_strike":   atm,
            "support_1":    atm - step,
            "support_2":    atm - 2 * step,
            "resistance_1": atm + step,
            "resistance_2": atm + 2 * step,
            "pivot":        round(sd["ema20"], 0),  # EMA20 acts as dynamic pivot
        }

    briefing["key_levels"] = key_levels

    # ── 8. Market session context ─────────────────────────────────────────────
    from datetime import timezone, timedelta as _td
    IST = timezone(_td(hours=5, minutes=30))
    now_ist = datetime.now(IST)
    t = now_ist.time()
    from datetime import time as _time
    if t < _time(9, 0):
        session = "pre_market"
        session_label = "Pre-market"
    elif t < _time(9, 15):
        session = "opening_auction"
        session_label = "Opening Auction"
    elif t < _time(11, 30):
        session = "morning"
        session_label = "Morning Session"
    elif t < _time(14, 0):
        session = "midday"
        session_label = "Midday"
    elif t < _time(15, 30):
        session = "afternoon"
        session_label = "Afternoon / Pre-expiry"
    else:
        session = "post_market"
        session_label = "Post-market"

    briefing["session"] = {
        "name": session,
        "label": session_label,
        "time_ist": now_ist.strftime("%H:%M IST"),
        "is_market_hours": _time(9, 15) <= t <= _time(15, 30) and now_ist.weekday() < 5,
    }

    # ── AI briefing from Redis (generated at 08:45 IST by generate_briefing task)
    try:
        import json, redis as redis_lib
        from app.config import settings
        _r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        raw = _r.get("premarket_briefing")
        if raw:
            cached = json.loads(raw)
            briefing["ai_briefing"] = cached.get("briefing")
            briefing["ai_briefing_date"] = cached.get("date")
        else:
            briefing["ai_briefing"] = None
    except Exception:
        briefing["ai_briefing"] = None

    return briefing


@router.get("/pattern-performance")
async def pattern_performance(db: AsyncSession = Depends(get_db)):
    """Pattern win-rate leaderboard from paper trades."""
    from app.models.trades import Trade, TradeStatus, TradeMode
    from sqlalchemy import case

    q = await db.execute(
        select(
            Trade.underlying,
            func.count().label("total"),
            func.sum(
                case((Trade.realized_pnl > 0, 1), else_=0)
            ).label("wins"),
            func.sum(Trade.realized_pnl).label("total_pnl"),
            func.avg(Trade.pnl_pct).label("avg_pnl_pct"),
            func.avg(Trade.realized_pnl).label("avg_pnl"),
        ).where(
            Trade.status == TradeStatus.CLOSED,
            Trade.mode   == TradeMode.PAPER,
        ).group_by(Trade.underlying)
        .order_by(desc("total_pnl"))
        .limit(20)
    )
    rows = q.all()

    return {
        "patterns": [
            {
                "underlying":  r.underlying,
                "total":       r.total,
                "wins":        int(r.wins or 0),
                "losses":      r.total - int(r.wins or 0),
                "win_rate":    round((r.wins or 0) / r.total, 3) if r.total else 0,
                "total_pnl":   round(float(r.total_pnl or 0), 2),
                "avg_pnl":     round(float(r.avg_pnl or 0), 2),
                "avg_pnl_pct": round(float(r.avg_pnl_pct or 0), 2),
            }
            for r in rows
        ]
    }


@router.get("/report")
async def trading_report(db: AsyncSession = Depends(get_db)):
    """
    Full paper trading report for the testing period:
    - Overall summary (total trades, win rate, P&L, avg per trade)
    - Per-underlying breakdown (NIFTY vs BANKNIFTY)
    - Per-pattern breakdown
    - Per-timeframe breakdown
    - Best and worst trades
    - Equity curve (daily cumulative P&L)
    - Discovered patterns with edge status
    """
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.models.portfolio import Portfolio
    from app.models.discovered_pattern import DiscoveredPattern
    from app.models.pattern_backtest import PatternBacktest, BacktestStatus
    from app.core.instruments import TESTING_FOCUS
    from sqlalchemy import case, text

    focus = TESTING_FOCUS or ["NIFTY", "BANKNIFTY"]

    # ── Closed paper trades for focus instruments only ─────────────────────────
    all_q = await db.execute(
        select(Trade).where(
            Trade.status == TradeStatus.CLOSED,
            Trade.mode   == TradeMode.PAPER,
            Trade.underlying.in_(focus),
            Trade.entry_price > 10,    # exclude ₹0.05 garbage from synthetic/expiry
        ).order_by(Trade.exit_time)
    )
    trades = all_q.scalars().all()

    def _trade_dict(t: Trade) -> dict:
        return {
            "id":           t.id,
            "symbol":       t.symbol,
            "underlying":   t.underlying,
            "option_type":  t.option_type,
            "strike":       t.strike,
            "action":       t.action,
            "direction":    t.direction,
            "entry_price":  t.entry_price,
            "exit_price":   t.exit_price,
            "quantity":     t.quantity,
            "lot_size":     t.lot_size,
            "realized_pnl": round(float(t.realized_pnl or 0), 2),
            "pnl_pct":      round(float(t.pnl_pct or 0), 2),
            "charges_total": round(float(t.charges_total or 0), 2),
            "exit_reason":  t.exit_reason,
            "entry_time":   t.entry_time.isoformat() if t.entry_time else None,
            "exit_time":    t.exit_time.isoformat() if t.exit_time else None,
            "expiry_display": t.expiry_display,
            "expiry_dte":   None,
        }

    # ── Overall summary ────────────────────────────────────────────────────────
    total = len(trades)
    winners = [t for t in trades if (t.realized_pnl or 0) > 0]
    losers  = [t for t in trades if (t.realized_pnl or 0) <= 0]
    total_pnl    = sum(float(t.realized_pnl or 0) for t in trades)
    total_charges = sum(float(t.charges_total or 0) for t in trades)
    gross_pnl    = sum(float(t.gross_pnl or 0) for t in trades)

    win_pnl  = sum(float(t.realized_pnl or 0) for t in winners)
    loss_pnl = abs(sum(float(t.realized_pnl or 0) for t in losers))

    summary = {
        "total_trades":   total,
        "winners":        len(winners),
        "losers":         len(losers),
        "win_rate":       round(len(winners) / total, 3) if total else 0,
        "total_pnl":      round(total_pnl, 2),
        "gross_pnl":      round(gross_pnl, 2),
        "total_charges":  round(total_charges, 2),
        "avg_pnl":        round(total_pnl / total, 2) if total else 0,
        "avg_winner":     round(win_pnl / len(winners), 2) if winners else 0,
        "avg_loser":      round(-loss_pnl / len(losers), 2) if losers else 0,
        "profit_factor":  round(win_pnl / loss_pnl, 2) if loss_pnl > 0 else (99.0 if win_pnl > 0 else 0),
        "largest_winner": round(max((float(t.realized_pnl or 0) for t in trades), default=0), 2),
        "largest_loser":  round(min((float(t.realized_pnl or 0) for t in trades), default=0), 2),
    }

    # ── Advanced metrics ──────────────────────────────────────────────────────
    import math

    # Sharpe ratio (annualised, using daily P&L returns)
    daily_pnl_pre: dict[str, float] = {}
    for t in trades:
        if not t.exit_time:
            continue
        day = t.exit_time.strftime("%Y-%m-%d")
        daily_pnl_pre[day] = daily_pnl_pre.get(day, 0) + float(t.realized_pnl or 0)
    daily_returns = list(daily_pnl_pre.values())

    sharpe = 0.0
    if len(daily_returns) >= 2:
        avg_r = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0
        if std_r > 0:
            sharpe = round((avg_r / std_r) * math.sqrt(252), 2)

    # Max consecutive losses
    sorted_by_exit = sorted(trades, key=lambda t: t.exit_time or datetime.min)
    max_consec_losses = 0
    cur_losses = 0
    for t in sorted_by_exit:
        if (t.realized_pnl or 0) < 0:
            cur_losses += 1
            max_consec_losses = max(max_consec_losses, cur_losses)
        else:
            cur_losses = 0

    # Avg hold time in hours
    hold_times = []
    for t in trades:
        if t.entry_time and t.exit_time:
            hold_times.append((t.exit_time - t.entry_time).total_seconds() / 3600)
    avg_hold_hours = round(sum(hold_times) / len(hold_times), 1) if hold_times else 0

    # Max drawdown from portfolio
    portfolio_q = await db.execute(select(Portfolio).where(Portfolio.mode == "paper"))
    pf_row = portfolio_q.scalar_one_or_none()
    max_drawdown_pct = round(pf_row.max_drawdown_pct or 0, 2) if pf_row else 0

    summary["sharpe_ratio"]       = sharpe
    summary["max_consec_losses"]  = max_consec_losses
    summary["avg_hold_hours"]     = avg_hold_hours
    summary["max_drawdown_pct"]   = max_drawdown_pct

    # ── Per-underlying breakdown ───────────────────────────────────────────────
    by_underlying: dict = {}
    for sym in ["NIFTY", "BANKNIFTY"]:
        sub = [t for t in trades if t.underlying == sym]
        if not sub:
            continue
        sub_w = [t for t in sub if (t.realized_pnl or 0) > 0]
        sub_pnl = sum(float(t.realized_pnl or 0) for t in sub)
        by_underlying[sym] = {
            "trades":    len(sub),
            "winners":   len(sub_w),
            "win_rate":  round(len(sub_w) / len(sub), 3),
            "total_pnl": round(sub_pnl, 2),
            "avg_pnl":   round(sub_pnl / len(sub), 2),
        }

    # ── Per-pattern breakdown ──────────────────────────────────────────────────
    from collections import defaultdict
    pat_groups: dict = defaultdict(list)
    for t in trades:
        # Pattern name comes from signal; fall back to symbol prefix extraction
        key = t.symbol.split("2")[0] if t.symbol else t.underlying  # crude fallback
        pat_groups[t.underlying].append(t)  # group by underlying for now

    # Better: join with signals to get pattern_name
    from app.models.signals import Signal
    sig_q = await db.execute(
        select(Signal.id, Signal.pattern_name, Signal.timeframe).where(
            Signal.id.in_([t.signal_id for t in trades if t.signal_id])
        )
    )
    sig_map = {row.id: row for row in sig_q.all()}

    by_pattern: dict = defaultdict(lambda: {"trades": 0, "winners": 0, "total_pnl": 0.0, "underlying": set()})
    by_timeframe: dict = defaultdict(lambda: {"trades": 0, "winners": 0, "total_pnl": 0.0})

    for t in trades:
        sig = sig_map.get(t.signal_id)
        pat = sig.pattern_name if sig else "unknown"
        tf  = sig.timeframe if sig else "unknown"
        pnl = float(t.realized_pnl or 0)

        by_pattern[pat]["trades"]    += 1
        by_pattern[pat]["total_pnl"] += pnl
        by_pattern[pat]["underlying"].add(t.underlying)
        if pnl > 0:
            by_pattern[pat]["winners"] += 1

        by_timeframe[tf]["trades"]    += 1
        by_timeframe[tf]["total_pnl"] += pnl
        if pnl > 0:
            by_timeframe[tf]["winners"] += 1

    patterns_out = []
    for pat, d in sorted(by_pattern.items(), key=lambda x: -x[1]["total_pnl"]):
        n = d["trades"]
        patterns_out.append({
            "pattern":    pat,
            "underlying": sorted(d["underlying"]),
            "trades":     n,
            "winners":    d["winners"],
            "win_rate":   round(d["winners"] / n, 3) if n else 0,
            "total_pnl":  round(d["total_pnl"], 2),
            "avg_pnl":    round(d["total_pnl"] / n, 2) if n else 0,
        })

    timeframes_out = []
    for tf, d in sorted(by_timeframe.items(), key=lambda x: -x[1]["total_pnl"]):
        n = d["trades"]
        timeframes_out.append({
            "timeframe": tf,
            "trades":    n,
            "winners":   d["winners"],
            "win_rate":  round(d["winners"] / n, 3) if n else 0,
            "total_pnl": round(d["total_pnl"], 2),
            "avg_pnl":   round(d["total_pnl"] / n, 2) if n else 0,
        })

    # ── Equity curve (daily cumulative P&L) ───────────────────────────────────
    daily_pnl: dict[str, float] = {}
    for t in trades:
        if not t.exit_time:
            continue
        day = t.exit_time.strftime("%Y-%m-%d")
        daily_pnl[day] = daily_pnl.get(day, 0) + float(t.realized_pnl or 0)

    cumulative = 0.0
    equity_curve = []
    for day in sorted(daily_pnl):
        cumulative += daily_pnl[day]
        equity_curve.append({
            "date":       day,
            "daily_pnl":  round(daily_pnl[day], 2),
            "cumulative": round(cumulative, 2),
        })

    # ── Best / worst trades ────────────────────────────────────────────────────
    sorted_trades = sorted(trades, key=lambda t: float(t.realized_pnl or 0), reverse=True)
    best_trades  = [_trade_dict(t) for t in sorted_trades[:5]]
    worst_trades = [_trade_dict(t) for t in sorted_trades[-5:] if (t.realized_pnl or 0) < 0]

    # ── Open trades ────────────────────────────────────────────────────────────
    open_q = await db.execute(
        select(Trade).where(
            Trade.status == TradeStatus.OPEN,
            Trade.mode   == TradeMode.PAPER,
            Trade.underlying.in_(focus),
        ).order_by(Trade.entry_time.desc())
    )
    open_trades = open_q.scalars().all()

    open_out = []
    for t in open_trades:
        pnl = float(t.unrealized_pnl or 0)
        days_held = (datetime.utcnow() - t.entry_time).days if t.entry_time else 0
        open_out.append({
            "id":            t.id,
            "symbol":        t.symbol,
            "underlying":    t.underlying,
            "action":        t.action,
            "option_type":   t.option_type,
            "strike":        t.strike,
            "entry_price":   t.entry_price,
            "current_price": t.current_price,
            "target_price":  t.target_price,
            "stop_loss":     t.stop_loss,
            "quantity":      t.quantity,
            "unrealized_pnl": round(pnl, 2),
            "pct_to_target": round((t.target_price - (t.current_price or t.entry_price)) / t.entry_price * 100, 1) if t.entry_price else 0,
            "pct_to_stop":   round(((t.current_price or t.entry_price) - t.stop_loss) / t.entry_price * 100, 1) if t.entry_price else 0,
            "days_held":     days_held,
            "entry_time":    t.entry_time.isoformat() if t.entry_time else None,
            "expiry_display": t.expiry_display,
            "trailing_stop": "trail_stop" in (t.notes or ""),
            "is_spread_leg": "spread_leg" in (t.notes or ""),
            "notes":         t.notes,
        })

    # ── Discovered patterns for NIFTY/BANKNIFTY ───────────────────────────────
    dp_q = await db.execute(
        select(DiscoveredPattern).where(
            DiscoveredPattern.underlying.in_(focus),
            DiscoveredPattern.active == True,
        ).order_by(desc(DiscoveredPattern.has_edge), desc(DiscoveredPattern.effect_size))
    )
    discovered = dp_q.scalars().all()

    discovered_out = []
    for dp in discovered:
        discovered_out.append({
            "id":           dp.id,
            "pattern_slug": dp.pattern_slug,
            "underlying":   dp.underlying,
            "timeframe":    dp.timeframe,
            "direction":    dp.direction,
            "features":     (dp.features or [])[:5],
            "win_rate":     round(dp.win_rate or 0, 3),
            "effect_size":  round(dp.effect_size or 0, 3),
            "has_edge":     dp.has_edge,
            "last_backtest_win_rate": dp.last_backtest_win_rate,
            "created_at":   dp.created_at.isoformat() if dp.created_at else None,
        })

    return {
        "generated_at":   datetime.utcnow().isoformat(),
        "focus_symbols":  ["NIFTY", "BANKNIFTY"],
        "summary":        summary,
        "by_underlying":  by_underlying,
        "by_pattern":     patterns_out,
        "by_timeframe":   timeframes_out,
        "equity_curve":   equity_curve,
        "best_trades":    best_trades,
        "worst_trades":   worst_trades,
        "open_trades":    open_out,
        "discovered_patterns": discovered_out,
    }


@router.get("/focus")
async def get_focus():
    """Return the current testing focus symbols."""
    from app.core.instruments import TESTING_FOCUS, priority_scan_list
    return {
        "focus_symbols": TESTING_FOCUS if TESTING_FOCUS else [],
        "scan_list":     priority_scan_list(),
        "is_restricted": bool(TESTING_FOCUS),
    }


@router.delete("/purge-junk-trades")
async def purge_junk_trades(db: AsyncSession = Depends(get_db)):
    """
    Delete paper trades from non-focus instruments or with negligible premiums (< ₹10).
    Safe to run any time — only removes obvious garbage.
    """
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.core.instruments import TESTING_FOCUS
    from sqlalchemy import delete, or_

    focus = TESTING_FOCUS or ["NIFTY", "BANKNIFTY"]

    stmt = delete(Trade).where(
        Trade.mode == TradeMode.PAPER,
        Trade.status == TradeStatus.CLOSED,
        or_(
            Trade.underlying.notin_(focus),
            Trade.entry_price < 10,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"deleted": result.rowcount, "message": f"Removed {result.rowcount} junk paper trades"}
