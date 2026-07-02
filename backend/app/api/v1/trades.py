"""Trade API endpoints."""
from loguru import logger
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.trades import Trade

router = APIRouter()


def _trade_dict(t: Trade) -> dict:
    return {
        "id": t.id, "signal_id": t.signal_id, "mode": t.mode,
        "symbol": t.symbol, "underlying": t.underlying,
        "option_type": t.option_type, "strike": t.strike,
        "lot_size": t.lot_size, "expiry_date": t.expiry_date,
        "expiry_display": t.expiry_display,
        "action": t.action, "direction": t.direction, "quantity": t.quantity,
        "entry_price": t.entry_price, "exit_price": t.exit_price,
        "current_price": t.current_price, "target_price": t.target_price,
        "stop_loss": t.stop_loss,
        "gross_pnl": t.gross_pnl, "unrealized_pnl": t.unrealized_pnl,
        "realized_pnl": t.realized_pnl, "pnl": t.pnl, "pnl_pct": t.pnl_pct,
        "charges_total": t.charges_total, "charges_entry": t.charges_entry,
        "charges_brokerage": t.charges_brokerage, "charges_stt": t.charges_stt,
        "charges_gst": t.charges_gst, "charges_txn": t.charges_txn,
        "charges_sebi": t.charges_sebi, "charges_stamp": t.charges_stamp,
        "entry_time": (t.entry_time.isoformat() + 'Z') if t.entry_time else None,
        "exit_time": (t.exit_time.isoformat() + 'Z') if t.exit_time else None,
        "last_mtm_at": (t.last_mtm_at.isoformat() + 'Z') if t.last_mtm_at else None,
        "status": t.status, "exit_reason": t.exit_reason,
        "capital_at_risk_pct": t.capital_at_risk_pct, "notes": t.notes,
        "is_hedge": bool(t.notes and t.notes.startswith("spread_leg:hedge")),
        "pattern": (t.notes.split("pattern:")[-1].split("|")[0] if t.notes and "pattern:" in t.notes else None),
        "trade_group_id": t.trade_group_id,
        "leg_role": t.leg_role,
        "strategy": (t.notes.split("STRATEGY:")[1].split("|")[0] if t.notes and "STRATEGY:" in t.notes else None),
    }


@router.get("/")
async def list_trades(mode: str = "live", status: str | None = None,
                      limit: int = 50, db: AsyncSession = Depends(get_db)):
    from app.models.trades import TradeMode, TradeStatus
    q = select(Trade).where(Trade.mode == TradeMode(mode.lower()))
    if status:
        q = q.where(Trade.status == TradeStatus(status.lower()))
    q = q.order_by(Trade.entry_time.desc()).limit(limit)
    result = await db.execute(q)
    trades = result.scalars().all()
    return {"trades": [_trade_dict(t) for t in trades], "count": len(trades)}


@router.post("/refresh-mtm")
async def refresh_mtm():
    """Run MTM update inline and return all open trades with fresh prices."""
    from app.workers.tasks import _do_mtm_update
    from app.database import AsyncSessionLocal
    await _do_mtm_update()
    # Use a fresh session so we see the committed MTM values, not a stale snapshot
    from app.models.trades import TradeStatus
    async with AsyncSessionLocal() as fresh_db:
        q = select(Trade).where(
            Trade.status == TradeStatus.OPEN,
        ).order_by(Trade.entry_time.desc())
        trades = (await fresh_db.execute(q)).scalars().all()
        total_unrealized = sum(
            (t.unrealized_pnl or 0) for t in trades
            if not (t.notes or "").startswith("spread_leg:hedge")
        )
        return {
            "trades": [_trade_dict(t) for t in trades],
            "total_unrealized_pnl": round(total_unrealized, 2),
            "count": len(trades),
            "refreshed_at": __import__("datetime").datetime.utcnow().isoformat(),
        }


@router.post("/{signal_id}/execute")
async def execute_trade(signal_id: int, mode: str = "paper", db: AsyncSession = Depends(get_db)):
    """Execute a signal as a paper or live trade."""
    return {"message": f"Trade execution queued for signal {signal_id} in {mode} mode"}


@router.get("/{trade_id}/chart")
async def trade_chart(trade_id: int, db: AsyncSession = Depends(get_db)):
    """
    Return the signal rationale + 5-minute option price chart for a trade.
    Chart data comes from Kite historical API when token is available,
    otherwise computed via Black-Scholes from the underlying 5m candles.
    """
    from app.models.signals import Signal
    from app.core.options.greeks import _bs_price, RISK_FREE_RATE
    from datetime import datetime, timedelta
    import math

    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")

    # Fetch linked signal for rationale
    signal_data: dict = {}
    if trade.signal_id:
        sig_res = await db.execute(select(Signal).where(Signal.id == trade.signal_id))
        sig = sig_res.scalar_one_or_none()
        if sig:
            signal_data = {
                "pattern_name":    sig.pattern_name,
                "explanation":     sig.explanation,
                "confidence":      sig.confidence_score,
                "iv_rank":         sig.iv_rank,
                "direction":       str(sig.direction).replace("SignalDirection.", "") if sig.direction else None,
                "option_strategy": sig.option_strategy,
                "regime_trend":    sig.regime_trend,
                "regime_vol":      sig.regime_volatility,
                "delta":           sig.delta,
                "iv_at_signal":    sig.iv_at_signal,
                "timeframe":       sig.timeframe,
            }

    # Build 5-minute chart: try Kite first, fall back to BS from underlying
    chart: list[dict] = []
    entry_time = trade.entry_time
    if entry_time:
        from_dt = entry_time - timedelta(hours=1, minutes=30)
        to_dt   = (trade.exit_time or datetime.utcnow()) + timedelta(minutes=30)

        # Try Kite historical for the option symbol
        fetched = False
        try:
            from app.core.data.kite_adapter import KiteAdapter
            from app.core.scanner import _resolve_nse_token
            adapter = KiteAdapter()
            if adapter.is_configured():
                # Resolve option token by symbol lookup
                token = None
                try:
                    import redis as _r
                    from app.config import settings as _s
                    r = _r.from_url(_s.redis_url, decode_responses=True)
                    token_map = r.hgetall("kite:option_tokens")
                    token = token_map.get(trade.symbol)
                except Exception:
                    pass

                if token:
                    df = adapter.get_historical(int(token), from_dt.date(), to_dt.date(), "5minute")
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            ts = row["timestamp"]
                            t_iso = ts.isoformat() + "Z" if hasattr(ts, "isoformat") else str(ts)
                            chart.append({"time": t_iso, "open": float(row["open"]),
                                          "high": float(row["high"]), "low": float(row["low"]),
                                          "close": float(row["close"])})
                        fetched = True
        except Exception:
            pass

        # Fallback: compute option price from underlying 5m OHLCV via BS
        if not fetched and trade.strike and trade.option_type and trade.expiry_date:
            try:
                from app.core.scanner import _fetch_ohlcv
                ohlcv, _ = await _fetch_ohlcv(trade.underlying or "NIFTY", "15m")
                iv = 0.18
                try:
                    iv_val = float(trade.notes.split("iv:")[1].split("|")[0]) if trade.notes and "iv:" in trade.notes else 0.18
                    iv = iv_val if 0.05 < iv_val < 2.0 else (iv_val / 100 if iv_val > 2 else 0.18)
                except Exception:
                    pass

                expiry_dt = datetime.strptime(str(trade.expiry_date)[:10], "%Y-%m-%d")
                for _, row in ohlcv.iterrows():
                    ts = row.get("timestamp") or row.name
                    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                        ts_utc = ts
                    else:
                        from datetime import timezone
                        ts_utc = ts.replace(tzinfo=timezone.utc) if hasattr(ts, "replace") else ts
                    dte_days = max(0.25, (expiry_dt - datetime.utcnow()).days + 1)
                    T = dte_days / 365.0
                    for price_key in ("close", "open", "high", "low"):
                        s = float(row.get(price_key, row.get("close", trade.strike)))
                        if math.isnan(s) or s < 1:
                            s = float(trade.strike)
                    c = float(row.get("close", trade.strike))
                    o = float(row.get("open", trade.strike))
                    h = float(row.get("high", trade.strike))
                    l = float(row.get("low", trade.strike))
                    opt_c = _bs_price(c, trade.strike, T, RISK_FREE_RATE, iv, trade.option_type)
                    opt_o = _bs_price(o, trade.strike, T, RISK_FREE_RATE, iv, trade.option_type)
                    opt_h = _bs_price(h, trade.strike, T, RISK_FREE_RATE, iv, trade.option_type)
                    opt_l = _bs_price(l, trade.strike, T, RISK_FREE_RATE, iv, trade.option_type)
                    t_iso = (ts_utc.isoformat().replace("+00:00", "") + "Z") if hasattr(ts_utc, "isoformat") else str(ts)
                    chart.append({"time": t_iso, "open": round(opt_o, 2), "high": round(opt_h, 2),
                                  "low": round(opt_l, 2), "close": round(opt_c, 2)})
            except Exception:
                pass

    # ── Underlying OHLCV — try Kite 5-min first, fall back to bhav daily ────────
    KITE_INDEX_TOKENS: dict[str, int] = {"NIFTY": 256265, "BANKNIFTY": 260105, "FINNIFTY": 257801}
    underlying_bars: list[dict] = []
    underlying_source = "unavailable"

    if entry_time and trade.underlying:
        # 1) Try Kite 5-min historical (requires active Kite session)
        token = KITE_INDEX_TOKENS.get(trade.underlying.upper())
        if token:
            try:
                from app.core.data.kite_adapter import KiteAdapter
                adapter = KiteAdapter()
                if adapter.is_configured():
                    from_dt2 = entry_time - timedelta(hours=2)
                    to_dt2   = (trade.exit_time or datetime.utcnow()) + timedelta(hours=1)
                    df2 = adapter.get_historical(token, from_dt2.date(), to_dt2.date(), "5minute")
                    if df2 is not None and not df2.empty:
                        for _, row in df2.iterrows():
                            ts = row.get("timestamp") or row.name
                            try:
                                # Kite returns IST-aware timestamps — convert to UTC
                                ts_utc = ts.tz_convert("UTC") if hasattr(ts, "tz_convert") else ts
                                t_iso = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                            except Exception:
                                t_iso = str(ts)
                            underlying_bars.append({
                                "time": t_iso,
                                "open": float(row["open"]), "high": float(row["high"]),
                                "low": float(row["low"]),   "close": float(row["close"]),
                            })
                        underlying_source = "kite_5min"
            except Exception:
                pass

        # 2) Fall back to yfinance 5-min (free, no auth, covers recent dates)
        if not underlying_bars:
            try:
                import yfinance as yf
                YF_SYMBOLS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "^CNXFIN"}
                yf_sym = YF_SYMBOLS.get(trade.underlying.upper())
                if yf_sym:
                    from_dt3 = entry_time - timedelta(hours=2)
                    to_dt3   = (trade.exit_time or datetime.utcnow()) + timedelta(hours=1)
                    ticker = yf.Ticker(yf_sym)
                    df3 = ticker.history(
                        start=from_dt3.strftime("%Y-%m-%d"),
                        end=(to_dt3 + timedelta(days=1)).strftime("%Y-%m-%d"),
                        interval="5m"
                    )
                    if df3 is not None and not df3.empty:
                        for ts, row in df3.iterrows():
                            try:
                                ts_utc = ts.tz_convert("UTC")
                                t_iso = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                            except Exception:
                                t_iso = str(ts)
                            o = float(row["Open"]); h = float(row["High"])
                            lo = float(row["Low"]); c = float(row["Close"])
                            if c > 0:
                                underlying_bars.append({"time": t_iso, "open": o, "high": h, "low": lo, "close": c})
                        if underlying_bars:
                            underlying_source = "yfinance_5min"
            except Exception:
                pass

    # ── Option OHLCV — real Kite NFO data first, BS fallback ────────────────────
    option_bars: list[dict] = []
    option_source = "unavailable"

    if entry_time and trade.symbol and trade.strike and trade.option_type:
        # Tier 1: real Kite 5-min for the option instrument itself
        try:
            from app.core.data.kite_adapter import KiteAdapter
            adapter2 = KiteAdapter()
            if adapter2.is_configured():
                # Resolve option instrument token from:
                # 1. trade.instrument_token (stored at trade creation — preferred)
                # 2. in-memory _token_to_sym map (populated when ticker subscribes option)
                # kite.instruments("NFO") and kite.quote() are NOT used here:
                #   — instruments() is rate-limited to ~1/day
                #   — quote() returns empty for weekly option symbols
                from app.core.data.kite_ticker import _token_to_sym
                opt_token = trade.instrument_token or next(
                    (tok for tok, sym in _token_to_sym.items() if sym == trade.symbol), None
                )
                if opt_token:
                    from_opt = entry_time - timedelta(hours=2)
                    to_opt   = (trade.exit_time or datetime.utcnow()) + timedelta(hours=1)
                    df_opt = adapter2.get_historical(opt_token, from_opt.date(), to_opt.date(), "5minute")
                    if df_opt is not None and not df_opt.empty:
                        for _, row in df_opt.iterrows():
                            ts = row.get("timestamp") or row.name
                            try:
                                ts_utc = ts.tz_convert("UTC") if hasattr(ts, "tz_convert") else ts
                                t_iso = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                            except Exception:
                                t_iso = str(ts)
                            option_bars.append({
                                "time":  t_iso,
                                "open":  round(float(row["open"]),  2),
                                "high":  round(float(row["high"]),  2),
                                "low":   round(float(row["low"]),   2),
                                "close": round(float(row["close"]), 2),
                            })
                        if option_bars:
                            option_source = "kite_5min"
        except Exception as _opt_ex:
            logger.warning(f"[chart] Kite option fetch failed: {_opt_ex}")

        # Tier 2: BS estimate from real underlying — approximate, ~₹30-50 overestimate
        # (entry_price itself is a BS estimate so calibration to it is also wrong)
        if not option_bars and underlying_bars and trade.expiry_date:
            try:
                from app.core.options.greeks import _bs_price, RISK_FREE_RATE
                import math as _math
                expiry_dt = datetime.strptime(str(trade.expiry_date)[:10], "%Y-%m-%d")
                K = float(trade.strike)
                opt_type = trade.option_type
                iv = 0.18
                if signal_data.get("iv_at_signal"):
                    raw = float(signal_data["iv_at_signal"])
                    iv = raw / 100 if raw > 2 else raw
                iv = max(0.05, min(iv, 2.0))
                for bar in underlying_bars:
                    try:
                        bar_dt = datetime.strptime(bar["time"][:19], "%Y-%m-%dT%H:%M:%S")
                        dte_days = max(0.25, (expiry_dt - bar_dt).total_seconds() / 86400)
                        T = dte_days / 365.0
                        opt_o = _bs_price(bar["open"],  K, T, RISK_FREE_RATE, iv, opt_type)
                        opt_h = _bs_price(bar["high"],  K, T, RISK_FREE_RATE, iv, opt_type)
                        opt_l = _bs_price(bar["low"],   K, T, RISK_FREE_RATE, iv, opt_type)
                        opt_c = _bs_price(bar["close"], K, T, RISK_FREE_RATE, iv, opt_type)
                        if any(_math.isnan(x) or _math.isinf(x) for x in [opt_o, opt_h, opt_l, opt_c]):
                            continue
                        option_bars.append({
                            "time":  bar["time"],
                            "open":  round(opt_o, 2), "high": round(opt_h, 2),
                            "low":   round(opt_l, 2), "close": round(opt_c, 2),
                        })
                    except Exception:
                        continue
                if option_bars:
                    option_source = "bs_estimated"
            except Exception:
                pass

    return {
        "trade_id":         trade_id,
        "symbol":           trade.symbol,
        "underlying":       trade.underlying,
        "strike":           trade.strike,
        "option_type":      trade.option_type,
        "entry_price":      trade.entry_price,
        "stop_loss":        trade.stop_loss,
        "target_price":     trade.target_price,
        "entry_time":       (trade.entry_time.isoformat() + "Z") if trade.entry_time else None,
        "exit_time":        (trade.exit_time.isoformat() + "Z") if trade.exit_time else None,
        "signal":           signal_data,
        "option_bars":      option_bars,
        "option_source":    option_source,     # "kite_5min" | "bs_estimated" | "unavailable"
        "underlying_bars":  underlying_bars,
        "underlying_source": underlying_source,
    }


@router.post("/{trade_id}/exit")
async def exit_trade(trade_id: int, reason: str = "manual", db: AsyncSession = Depends(get_db)):
    """Manually exit an open trade."""
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    return {"message": f"Exit queued for trade {trade_id}", "reason": reason}


@router.post("/{trade_id}/close")
async def close_trade_manual(trade_id: int, db: AsyncSession = Depends(get_db)):
    """Manually close an open paper trade at current price."""
    from app.models.trades import TradeStatus
    from app.core.charges import calculate_charges
    from app.models.portfolio import Portfolio
    from datetime import datetime

    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    if trade.status != TradeStatus.OPEN:
        raise HTTPException(400, f"Trade is already {trade.status.value}")

    exit_price = trade.current_price or trade.entry_price or 0.0
    charges = calculate_charges(
        entry_premium=trade.entry_price or 0.0,
        exit_premium=exit_price,
        quantity=trade.quantity or 1,
        action=trade.action or "BUY",
    )
    if trade.action == "BUY":
        gross = (exit_price - (trade.entry_price or 0)) * (trade.quantity or 1)
    else:
        gross = ((trade.entry_price or 0) - exit_price) * (trade.quantity or 1)
    net_pnl = gross - charges.total

    trade.exit_price     = exit_price
    trade.exit_time      = datetime.utcnow()
    trade.status         = TradeStatus.CLOSED
    trade.exit_reason    = "manual_close"
    trade.gross_pnl      = round(gross, 2)
    trade.realized_pnl   = round(net_pnl, 2)
    trade.pnl            = round(net_pnl, 2)
    trade.unrealized_pnl = None
    trade.charges_total  = round(charges.total, 2)

    port_q = await db.execute(select(Portfolio).where(Portfolio.mode == trade.mode))
    portfolio = port_q.scalar_one_or_none()
    if portfolio:
        trade_cost = (trade.entry_price or 0) * (trade.quantity or 1)
        portfolio.capital_current  += trade_cost + net_pnl
        portfolio.capital_deployed  = max(0, portfolio.capital_deployed - trade_cost)
        portfolio.daily_pnl         = (portfolio.daily_pnl or 0) + net_pnl
        portfolio.total_pnl         = (portfolio.total_pnl or 0) + net_pnl

    await db.commit()
    return {"message": "Trade closed", "trade_id": trade_id, "exit_price": exit_price, "pnl": round(net_pnl, 2)}


# ── Payoff diagram ────────────────────────────────────────────────────────────

def _spot_from_redis(underlying: str) -> float | None:
    try:
        import redis as _r
        from app.config import settings as _st
        r = _r.from_url(_st.redis_url, decode_responses=True)
        v = r.get(f"spot:{underlying}")
        return float(v) if v else None
    except Exception:
        return None


@router.get("/payoff/{group_id}")
async def payoff_diagram(group_id: str, db: AsyncSession = Depends(get_db)):
    """
    Payoff diagram for a composite trade group (or single trade id).

    Returns expiry P&L curve, T+0 (today, BS-repriced) curve, breakevens,
    max profit/loss within the plotted range, and net Greeks at current spot.
    All P&L values are in rupees for the full position (per-unit × quantity),
    net of nothing — charges are shown separately as `charges_entry_total`.
    """
    from datetime import date as _date
    from app.core.options.greeks import _bs_price, compute_greeks, RISK_FREE_RATE
    from app.core.instruments import BASE_PRICES

    # Fetch legs: try group id first, then single numeric trade id
    result = await db.execute(select(Trade).where(Trade.trade_group_id == group_id))
    legs = result.scalars().all()
    if not legs and group_id.isdigit():
        result = await db.execute(select(Trade).where(Trade.id == int(group_id)))
        t = result.scalar_one_or_none()
        legs = [t] if t else []
    if not legs:
        raise HTTPException(404, "No trades found for this group id")

    underlying = legs[0].underlying
    spot = _spot_from_redis(underlying) or BASE_PRICES.get(underlying, 0.0)
    if spot <= 0:
        raise HTTPException(500, f"No spot price available for {underlying}")

    # Per-leg IV: prefer ATM chain IV, fallback 18%
    chain_iv = 0.18
    try:
        from app.core.options.chain_service import ChainService
        chain = ChainService().get_chain(underlying)
        if chain is not None and len(chain):
            atm_row = chain.iloc[(chain["strike"] - spot).abs().argmin()]
            iv_raw = float(atm_row.get("ce_iv") or atm_row.get("pe_iv") or 18.0)
            iv_frac = iv_raw / 100.0 if iv_raw > 2.0 else iv_raw
            if 0.05 <= iv_frac <= 1.5:
                chain_iv = iv_frac
    except Exception:
        pass

    today = _date.today()
    lot = legs[0].lot_size or 1

    leg_specs = []
    for t in legs:
        if not t.strike or not t.option_type:
            continue
        try:
            exp = _date.fromisoformat(t.expiry_date) if t.expiry_date else today
        except Exception:
            exp = today
        dte = max((exp - today).days, 0)
        leg_specs.append({
            "id": t.id, "role": t.leg_role, "action": t.action,
            "option_type": t.option_type, "strike": float(t.strike),
            "entry_price": float(t.entry_price or 0.0),
            "quantity": int(t.quantity or lot),
            "expiry": t.expiry_date, "dte": dte,
            "sign": 1.0 if t.action == "BUY" else -1.0,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "current_price": t.current_price,
        })
    if not leg_specs:
        raise HTTPException(400, "No option legs with strike/type in this group")

    # Spot range: ±8% around current spot, 121 points
    lo, hi = spot * 0.92, spot * 1.08
    n = 121
    xs = [lo + (hi - lo) * i / (n - 1) for i in range(n)]

    # Nearest expiry among legs = the horizon for the "expiry" curve.
    # Far-expiry legs (calendar/diagonal) are BS-repriced at that horizon.
    min_dte = min(l["dte"] for l in leg_specs)

    def leg_value(l, S: float, days_from_now: int) -> float:
        """Option value of a leg at spot S, `days_from_now` days ahead."""
        T = max(l["dte"] - days_from_now, 0) / 365.0
        if T <= 0:
            if l["option_type"] == "CE":
                return max(S - l["strike"], 0.0)
            return max(l["strike"] - S, 0.0)
        try:
            return _bs_price(S, l["strike"], T, RISK_FREE_RATE, chain_iv, l["option_type"])
        except Exception:
            return 0.0

    def group_pnl(S: float, days_from_now: int) -> float:
        total = 0.0
        for l in leg_specs:
            total += l["sign"] * (leg_value(l, S, days_from_now) - l["entry_price"]) * l["quantity"]
        return total

    expiry_curve = [round(group_pnl(x, min_dte), 2) for x in xs]
    t0_curve     = [round(group_pnl(x, 0), 2) for x in xs]

    # Breakevens on the expiry curve (linear interpolation at sign changes)
    breakevens = []
    for i in range(1, n):
        a, b = expiry_curve[i - 1], expiry_curve[i]
        if a == 0:
            breakevens.append(round(xs[i - 1], 1))
        elif (a < 0 < b) or (a > 0 > b):
            frac = abs(a) / (abs(a) + abs(b))
            breakevens.append(round(xs[i - 1] + (xs[i] - xs[i - 1]) * frac, 1))

    # Net Greeks at current spot (per unit × quantity)
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in leg_specs:
        T = max(l["dte"], 1) / 365.0
        try:
            g = compute_greeks(spot, l["strike"], T, chain_iv, l["option_type"])
            for k in net:
                net[k] += l["sign"] * getattr(g, k) * l["quantity"]
        except Exception:
            pass

    charges_entry_total = sum(float(t.charges_entry or 0.0) for t in legs)
    current_pnl = sum(float(t.unrealized_pnl or t.pnl or 0.0) for t in legs)

    return {
        "underlying": underlying,
        "spot": round(spot, 2),
        "iv_used": round(chain_iv * 100, 2),
        "horizon_days": min_dte,
        "legs": leg_specs,
        "spots": [round(x, 1) for x in xs],
        "expiry_pnl": expiry_curve,
        "t0_pnl": t0_curve,
        "breakevens": breakevens,
        "max_profit": round(max(expiry_curve), 2),
        "max_loss": round(min(expiry_curve), 2),
        "net_greeks": {k: round(v, 4) for k, v in net.items()},
        "charges_entry_total": round(charges_entry_total, 2),
        "current_pnl": round(current_pnl, 2),
        "note": ("Far-expiry legs are BS-repriced at the near-expiry horizon; "
                 "curves use ATM chain IV (fallback 18%) and are approximate."),
    }


@router.get("/export/csv")
async def export_trades_csv(mode: str = "paper", db: AsyncSession = Depends(get_db)):
    """Export all trades as CSV for offline analysis. Timestamps are IST."""
    import csv, io
    from datetime import timedelta as _td
    from fastapi.responses import StreamingResponse
    from app.models.trades import TradeMode

    result = await db.execute(
        select(Trade).where(Trade.mode == TradeMode(mode.lower()))
        .order_by(Trade.entry_time.desc()))
    trades = result.scalars().all()

    def ist(dt):
        return (dt + _td(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S") if dt else ""

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "group_id", "leg_role", "symbol", "underlying", "type", "strike",
                "expiry", "action", "qty", "entry_ist", "exit_ist", "entry_price",
                "exit_price", "gross_pnl", "charges", "net_pnl", "pnl_pct",
                "status", "exit_reason", "strategy"])
    for t in trades:
        strat = (t.notes.split("STRATEGY:")[1].split("|")[0]
                 if t.notes and "STRATEGY:" in t.notes else "")
        w.writerow([t.id, t.trade_group_id or "", t.leg_role or "", t.symbol, t.underlying,
                    t.option_type or "", t.strike or "", t.expiry_date or "",
                    t.action, t.quantity, ist(t.entry_time), ist(t.exit_time),
                    t.entry_price, t.exit_price or "", t.gross_pnl or "",
                    t.charges_total or "", t.pnl or "", t.pnl_pct or "",
                    t.status.value if hasattr(t.status, "value") else t.status,
                    t.exit_reason or "", strat])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=alphafo_trades_{mode}.csv"})
