"""Trade API endpoints."""
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

    return {
        "trade_id":   trade_id,
        "symbol":     trade.symbol,
        "entry_price": trade.entry_price,
        "stop_loss":  trade.stop_loss,
        "target_price": trade.target_price,
        "entry_time": (trade.entry_time.isoformat() + "Z") if trade.entry_time else None,
        "exit_time":  (trade.exit_time.isoformat() + "Z") if trade.exit_time else None,
        "signal":     signal_data,
        "chart":      chart,
        "chart_source": "kite" if any(c for c in chart) and "fetched" in dir() and fetched else "bs_estimated",
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
