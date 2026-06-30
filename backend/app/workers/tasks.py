"""
Background tasks:
  - Pattern scan engine (priority + full)
  - Paper trade auto-execution (with charges at entry)
  - MTM updater — reprices open positions every minute
  - Expiry settler — closes expired trades at settlement price
"""
import asyncio
from datetime import datetime, timedelta, date
from loguru import logger

from app.workers.celery_app import celery_app


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Signal persistence ────────────────────────────────────────────────────────

async def _persist_and_broadcast(signals: list[dict], db, broadcast_fn):
    from app.models.signals import Signal, SignalStatus
    from sqlalchemy import select, and_

    created = []
    valid_until = datetime.utcnow() + timedelta(hours=24)

    for s in signals:
        # Reject signals that have no contract details — they're unenriched fallbacks
        if not s.get("option_type") or not s.get("expiry_date_iso") or not s.get("strike"):
            logger.debug(f"Skipping unenriched signal: {s.get('pattern_name')} {s.get('underlying')} — no contract")
            continue

        cutoff = datetime.utcnow() - timedelta(hours=1)
        # Dedup by underlying+pattern+direction+option_type within the last hour.
        # Include option_type so a CE and PE on the same pattern are distinct signals.
        q = select(Signal).where(and_(
            Signal.underlying    == s["underlying"],
            Signal.pattern_name  == s["pattern_name"],
            Signal.direction     == s["direction"],
            Signal.option_type   == s.get("option_type"),
            Signal.created_at    >= cutoff,
        ))
        if (await db.execute(q)).scalars().first():
            continue

        sig = Signal(
            pattern_name=s["pattern_name"], pattern_version=s.get("pattern_version", "1.0"),
            symbol=s.get("symbol", s["underlying"]), underlying=s["underlying"],
            instrument=s.get("instrument", s["underlying"]), direction=s["direction"],
            entry_price=s["entry_price"], target_price=s["target_price"], stop_loss=s["stop_loss"],
            expected_return_pct=s["expected_return_pct"], confidence_score=s["confidence_score"],
            explanation=s.get("explanation", ""), trading_style=s.get("trading_style", "intraday"),
            status=SignalStatus.ACTIVE, created_at=datetime.utcnow(), valid_until=valid_until,
            option_type=s.get("option_type"), strike=s.get("strike"),
            expiry_date_str=s.get("expiry_date_str"),
            expiry_date_iso=s.get("expiry_date_iso"),
            expiry_display=s.get("expiry_display"),
            expiry_dte=s.get("expiry_dte"),
            expiry_series=s.get("expiry_series"),
            option_strategy=s.get("option_strategy"),
            lot_size=s.get("lot_size"), delta=s.get("delta"), gamma=s.get("gamma"),
            theta=s.get("theta"), vega=s.get("vega"), iv_at_signal=s.get("iv_at_signal"),
            iv_rank=s.get("iv_rank"), regime_trend=s.get("regime_trend"),
            regime_volatility=s.get("regime_volatility"), estimated_premium=s.get("estimated_premium"),
            max_loss=s.get("max_loss"), timeframe=s.get("timeframe"),
        )
        db.add(sig)
        created.append(sig)

    if created:
        await db.commit()
        for sig in created:
            await db.refresh(sig)
        logger.info(f"Persisted {len(created)} new signals")
        await _auto_paper_trade(created, db)

    if broadcast_fn and signals:
        for s in signals:
            await broadcast_fn({"type": "new_signal", "signal": s})

    return created


# ── Paper trade auto-execution ────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """Return True only during NSE F&O trading hours (9:20 – 15:25 IST, Mon–Fri)."""
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if now.weekday() >= 5:           # Saturday=5, Sunday=6
        return False
    t = now.time()
    from datetime import time as _time
    return _time(9, 20) <= t <= _time(15, 25)


async def _auto_paper_trade(signals, db):
    """
    Auto-execute trades for high-confidence signals.
    - Real-data signals (Kite OHLCV): confidence ≥ 0.72, any market hours
    - Synthetic-data signals: confidence ≥ 0.82, only during market hours
    One trade per (underlying, pattern_name, direction). Entry charges deducted immediately.
    Hedge leg auto-added for all SELL positions.
    """
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.models.portfolio import Portfolio
    from app.core.charges import charges_for_entry_only
    from sqlalchemy import select

    # Confidence thresholds
    HIGH_CONF_REAL      = 0.72   # real Kite OHLCV data
    HIGH_CONF_SYNTHETIC = 0.82   # synthetic data — require very high confidence

    market_open = _is_market_hours()

    # Dedup: pick the nearest-expiry signal per pattern+direction combo
    seen: set[tuple] = set()
    deduped = []
    for sig in sorted(signals, key=lambda s: s.expiry_dte or 999):
        key = (sig.underlying, sig.pattern_name, sig.direction)
        if key not in seen:
            seen.add(key)
            deduped.append(sig)
    signals = deduped

    from app.core.options.chain_service import STRIKE_STEPS as _STEPS
    from app.core.options.greeks import _bs_price, RISK_FREE_RATE as _RF

    def _hedge_premium(underlying: str, spot: float, hedge_strike: float,
                       opt_type: str, expiry_date_iso: str) -> float:
        """Compute hedge leg premium via Black-Scholes."""
        try:
            from datetime import date as _date
            dte = max(1, (_date.fromisoformat(expiry_date_iso) - _date.today()).days)
            T = dte / 365.0
            return round(max(0.05, _bs_price(spot, hedge_strike, T, _RF, 0.18, opt_type)), 2)
        except Exception:
            return 0.0

    def _spot_price(underlying: str) -> float:
        try:
            from app.core.data.kite_ticker import ticker_service
            snap = ticker_service.get_snapshot()
            ltp = snap.get(underlying.upper(), {}).get("ltp", 0)
            if ltp > 0:
                return float(ltp)
        except Exception:
            pass
        from app.core.instruments import BASE_PRICES
        return float(BASE_PRICES.get(underlying.upper(), 1000))

    for sig in signals:
        # Data-source: synthetic signals have "SIM" or "synthetic" in explanation,
        # or no expiry bracket prefix (real signals always have "[Weekly/Monthly expiry ...]")
        explanation = sig.explanation or ""
        is_synthetic = (
            "synthetic" in explanation.lower()
            or "SIM" in explanation
            or not explanation.startswith("[")
        )
        required_conf = HIGH_CONF_SYNTHETIC if is_synthetic else HIGH_CONF_REAL
        if sig.confidence_score < required_conf:
            continue
        # Synthetic signals only during market hours — don't paper-trade fake data overnight
        if is_synthetic and not market_open:
            logger.debug(f"Skipping synthetic signal {sig.pattern_name}/{sig.underlying} outside market hours")
            continue
        # Age gate: don't execute signals older than 2h (stale strikes at market open)
        if sig.created_at:
            age_hours = (datetime.utcnow() - sig.created_at).total_seconds() / 3600
            if age_hours > 2.0:
                logger.debug(
                    f"Skipping stale signal {sig.pattern_name}/{sig.underlying}: "
                    f"{age_hours:.1f}h old (max 2h)"
                )
                continue
        if not sig.estimated_premium or not sig.lot_size:
            continue
        # Minimum premium floor — options below ₹50 are illiquid for F&O trading
        if sig.estimated_premium < 50.0:
            logger.debug(f"Skipping low-premium signal {sig.pattern_name}/{sig.underlying}: ₹{sig.estimated_premium:.2f} < ₹50")
            continue

        # ── Backtest edge gate ────────────────────────────────────────────────
        # If this pattern has been backtested and shows NO edge, skip auto-execution.
        # If untested (None), allow through — will get tagged after nightly run.
        try:
            from app.models.pattern_backtest import PatternBacktest, BacktestStatus
            from sqlalchemy import select as _bsel, desc as _bdesc
            tf = sig.timeframe or "daily"
            bt_q = await db.execute(
                _bsel(PatternBacktest).where(
                    PatternBacktest.underlying   == sig.underlying,
                    PatternBacktest.pattern_name == sig.pattern_name,
                    PatternBacktest.timeframe    == tf,
                    PatternBacktest.status       == BacktestStatus.COMPLETE,
                    PatternBacktest.trades_taken >= 10,
                ).order_by(_bdesc(PatternBacktest.created_at)).limit(1)
            )
            bt = bt_q.scalar_one_or_none()
            if bt:
                from app.core.backtest.engine import has_edge
                if not has_edge(bt.win_rate, bt.profit_factor, trades=bt.trades_taken):
                    logger.info(
                        f"Skipping {sig.pattern_name}/{sig.underlying}: "
                        f"backtested WR={bt.win_rate:.0%} PF={bt.profit_factor:.2f} — no edge"
                    )
                    continue
        except Exception:
            pass  # if DB/import fails, allow trade through (fail-open for new patterns)

        # ── Event risk block ──────────────────────────────────────────────────
        # Don't trade within 1 day of RBI MPC, FOMC, or monthly expiry
        try:
            from app.core.options.event_calendar import EventCalendar
            from datetime import date as _today_dt
            if EventCalendar().is_event_risk(_today_dt.today(), dte=1):
                logger.info(f"Skipping {sig.pattern_name}/{sig.underlying}: event risk window (RBI/FOMC/expiry within 1 day)")
                continue
        except Exception:
            pass

        premium  = sig.estimated_premium
        quantity = sig.lot_size
        action   = "BUY" if sig.direction == "long" else "SELL"

        # ── Hedge leg for SELL positions (cap max loss via spread) ─────────────
        hedge_trade_data = None
        if action == "SELL" and sig.option_type in ("CE", "PE") and sig.strike and sig.expiry_date_iso:
            step = _STEPS.get(sig.underlying.upper(), 50)
            spot = _spot_price(sig.underlying)
            if sig.option_type == "CE":
                hedge_strike = sig.strike + 2 * step   # buy higher CE to cap loss
            else:
                hedge_strike = sig.strike - 2 * step   # buy lower PE to cap loss
            hedge_prem = _hedge_premium(sig.underlying, spot, hedge_strike,
                                        sig.option_type, sig.expiry_date_iso)
            if hedge_prem > 0:
                # Derive hedge symbol (same expiry date string)
                expiry_tag = (sig.instrument or "").replace(sig.underlying, "")
                # Extract expiry portion: e.g. "07JUL26" from "NIFTY07JUL2624800CE"
                import re as _re
                m = _re.search(r'(\d{2}[A-Z]{3}\d{2})', sig.instrument or "")
                expiry_tag = m.group(1) if m else ""
                hedge_sym = f"{sig.underlying}{expiry_tag}{int(hedge_strike)}{sig.option_type}"
                hedge_trade_data = {
                    "symbol": hedge_sym, "strike": hedge_strike,
                    "premium": hedge_prem, "action": "BUY",  # hedge is always a buy
                }

        # Total cost: main leg cost minus hedge premium collected/paid
        entry_charges = charges_for_entry_only(premium, quantity, action)
        cost = premium * quantity + entry_charges
        if hedge_trade_data:
            hedge_entry_charges = charges_for_entry_only(
                hedge_trade_data["premium"], quantity, "BUY")
            hedge_cost = hedge_trade_data["premium"] * quantity + hedge_entry_charges
            cost += hedge_cost   # net debit: sell premium collected, buy hedge paid

        # Skip if there's already an open trade for this same instrument
        from app.models.trades import TradeStatus as _TS
        instrument_sym = sig.instrument or sig.underlying
        existing_q = select(Trade).where(
            Trade.status == _TS.OPEN, Trade.mode == TradeMode.PAPER,
            Trade.symbol == instrument_sym, Trade.direction == sig.direction,
        )
        if (await db.execute(existing_q)).scalars().first():
            logger.debug(f"Skipping duplicate paper trade: {instrument_sym} {sig.direction}")
            continue

        result = await db.execute(select(Portfolio).where(Portfolio.mode == "paper"))
        portfolio = result.scalar_one_or_none()
        if not portfolio or portfolio.capital_current < cost * 1.1:
            logger.warning(f"Insufficient capital for {sig.underlying} paper trade")
            continue

        # ── Risk gate ─────────────────────────────────────────────────────────
        try:
            from app.core.risk.gate import check as _risk_check
            if action == "BUY":
                opt_stop_for_gate = round(premium * 0.60, 2)
            else:
                opt_stop_for_gate = round(premium * 2.00, 2)
            risk = _risk_check(
                underlying   = sig.underlying,
                entry_price  = premium,
                stop_loss    = opt_stop_for_gate,
                lot_size     = sig.lot_size,
                strategy     = "buy" if action == "BUY" else "sell",
                capital      = portfolio.capital_current,
            )
            if not risk.approved:
                logger.warning(f"Risk gate blocked {sig.underlying} {action}: {risk.reason}")
                continue
            quantity = risk.recommended_qty * sig.lot_size if risk.recommended_qty > 0 else sig.lot_size
        except Exception as e:
            logger.warning(f"Risk gate check failed ({e}), using default qty")
            quantity = sig.lot_size

        now = datetime.utcnow()

        # Option-centric target/stop — based on premium movement, not underlying
        # BUY : target = +50% of premium, stop = -40% of premium
        # SELL: target = collect 55% (premium drops to 45%), stop = premium doubles (2×)
        if action == "BUY":
            opt_target = round(premium * 1.50, 2)   # exit when up 50%
            opt_stop   = round(premium * 0.60, 2)   # exit when down 40%
        else:
            opt_target = round(premium * 0.45, 2)   # exit when premium shrinks to 45%
            opt_stop   = round(premium * 2.00, 2)   # exit if premium doubles (2× against)

        # ── Atomic main + hedge leg (both succeed or neither is saved) ──────────
        try:
            trade = Trade(
                signal_id   = sig.id, mode = TradeMode.PAPER,
                symbol      = sig.instrument or sig.underlying,
                underlying  = sig.underlying, option_type = sig.option_type,
                strike      = sig.strike, lot_size = sig.lot_size,
                expiry_date = sig.expiry_date_iso, expiry_display = sig.expiry_display,
                action      = action, direction = sig.direction, quantity = quantity,
                entry_price = premium, current_price = premium,
                target_price = opt_target, stop_loss = opt_stop,
                charges_entry = entry_charges, unrealized_pnl = 0.0,
                status = TradeStatus.OPEN, entry_time = now,
                notes = "spread_leg:main" if hedge_trade_data else None,
                capital_at_risk_pct = round((cost / portfolio.capital_current) * 100, 4),
            )
            db.add(trade)
            portfolio.capital_deployed += premium * quantity + entry_charges
            portfolio.capital_current  -= premium * quantity + entry_charges

            if hedge_trade_data:
                h = hedge_trade_data
                h_charges = charges_for_entry_only(h["premium"], quantity, "BUY")
                hedge = Trade(
                    signal_id   = sig.id, mode = TradeMode.PAPER,
                    symbol      = h["symbol"], underlying = sig.underlying,
                    option_type = sig.option_type, strike = h["strike"],
                    lot_size    = sig.lot_size, expiry_date = sig.expiry_date_iso,
                    expiry_display = sig.expiry_display,
                    action      = "BUY", direction = sig.direction, quantity = quantity,
                    entry_price = h["premium"], current_price = h["premium"],
                    target_price = 0.0, stop_loss = 0.0,
                    charges_entry = h_charges, unrealized_pnl = 0.0,
                    status = TradeStatus.OPEN, entry_time = now,
                    notes = f"spread_leg:hedge|main_sym:{instrument_sym}",
                    capital_at_risk_pct = 0.0,
                )
                db.add(hedge)
                portfolio.capital_deployed += h["premium"] * quantity + h_charges
                portfolio.capital_current  -= h["premium"] * quantity + h_charges
                logger.info(
                    f"Hedge leg: {sig.underlying} {h['symbol']} BUY @ ₹{h['premium']:.2f} × {quantity} "
                    f"(protects {instrument_sym} SELL)"
                )

            logger.info(
                f"Paper trade: {sig.underlying} {sig.instrument} {action} "
                f"@ ₹{premium:.2f} × {quantity} | entry charges ₹{entry_charges:.2f}"
                + (f" | hedged via {hedge_trade_data['symbol']}" if hedge_trade_data else " | unhedged BUY")
            )
            # Update Redis portfolio heat tracker
            try:
                from app.core.risk.gate import record_deployed as _record_deployed
                _record_deployed(premium * quantity + entry_charges)
                if hedge_trade_data:
                    _record_deployed(hedge_trade_data["premium"] * quantity)
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"Trade insert failed for {sig.underlying} {action}, rolling back: {exc}")
            await db.rollback()
            continue

    await db.commit()

    # ── Live order placement ──────────────────────────────────────────────────
    # Place real Kite orders when: Kite credentials present AND market is open
    # AND signal came from real OHLCV data (not synthetic)
    if not market_open:
        logger.info("Live order placement skipped: outside market hours")
    else:
        try:
            from app.config import settings as _cfg
            if _cfg.kite_api_key and _cfg.kite_access_token:
                from kiteconnect import KiteConnect
                from app.models.trades import TradeStatus as _TS2, TradeMode as _TM2
                from sqlalchemy import select as _sel2

                live_result = await db.execute(_sel2(Portfolio).where(Portfolio.mode == "live"))
                live_portfolio = live_result.scalar_one_or_none()

                if live_portfolio:
                    kite_live = KiteConnect(api_key=_cfg.kite_api_key)
                    kite_live.set_access_token(_cfg.kite_access_token)

                    for sig in signals:
                        # Same gates as paper — confidence + premium floor
                        _exp_live = sig.explanation or ""
                        is_syn = (
                            "synthetic" in _exp_live.lower()
                            or "SIM" in _exp_live
                            or not _exp_live.startswith("[")
                        )
                        req_conf = HIGH_CONF_SYNTHETIC if is_syn else HIGH_CONF_REAL
                        if sig.confidence_score < req_conf:
                            continue
                        if not sig.estimated_premium or sig.estimated_premium < 50.0:
                            continue
                        if not sig.lot_size or not sig.instrument:
                            continue

                        live_action = "BUY" if sig.direction == "long" else "SELL"
                        prem = sig.estimated_premium

                        # Option-centric target/stop (same rules as paper)
                        if live_action == "BUY":
                            l_target = round(prem * 1.50, 2)
                            l_stop   = round(prem * 0.60, 2)
                        else:
                            l_target = round(prem * 0.45, 2)
                            l_stop   = round(prem * 2.00, 2)

                        # Skip if already an open live trade for this contract
                        dup_q = _sel2(Trade).where(
                            Trade.status == _TS2.OPEN, Trade.mode == _TM2.LIVE,
                            Trade.symbol == sig.instrument,
                        )
                        if (await db.execute(dup_q)).scalars().first():
                            continue

                        # Also apply risk gate for live orders
                        try:
                            from app.core.risk.gate import check as _live_risk
                            _l_stop_gate = round(prem * 0.60, 2) if live_action == "BUY" else round(prem * 2.00, 2)
                            live_risk = _live_risk(sig.underlying, prem, _l_stop_gate,
                                                   sig.lot_size, "buy" if live_action == "BUY" else "sell",
                                                   live_portfolio.capital_current)
                            if not live_risk.approved:
                                logger.warning(f"Risk gate blocked LIVE {sig.underlying}: {live_risk.reason}")
                                continue
                        except Exception as rge:
                            logger.warning(f"Live risk gate error: {rge}")

                        # Event risk block (same as paper)
                        try:
                            from app.core.options.event_calendar import EventCalendar
                            from datetime import date as _d2
                            if EventCalendar().is_event_risk(_d2.today(), dte=1):
                                logger.info(f"Skipping LIVE {sig.instrument}: event risk window")
                                continue
                        except Exception:
                            pass

                        product = "MIS" if (sig.trading_style or "intraday") == "intraday" else "NRML"
                        # Limit order at live LTP (not market order — avoids slippage on wide spreads)
                        try:
                            from app.core.data.kite_ticker import ticker_service as _ts
                            snap = _ts.get_snapshot()
                            ltp_now = snap.get(sig.underlying.upper(), {}).get("ltp", 0)
                            # Use signal's estimated_premium; if live LTP differs >10%, skip
                            limit_price = round(prem, 1)
                            if ltp_now > 0:
                                from app.core.options.greeks import _bs_price, RISK_FREE_RATE as _rfr
                                from datetime import date as _d3
                                _dte = max(1, ((_d3.fromisoformat(sig.expiry_date_iso) - _d3.today()).days))
                                _T = _dte / 365.0
                                live_bs = _bs_price(ltp_now, sig.strike, _T, _rfr, 0.18, sig.option_type)
                                if abs(live_bs - prem) / prem > 0.15:
                                    logger.warning(f"Stale premium for {sig.instrument}: BS={live_bs:.1f} vs signal={prem:.1f}, skipping")
                                    continue
                                limit_price = round(live_bs, 1)
                        except Exception:
                            limit_price = round(prem, 1)

                        try:
                            order_id = kite_live.place_order(
                                variety   = kite_live.VARIETY_REGULAR,
                                exchange  = kite_live.EXCHANGE_NFO,
                                tradingsymbol = sig.instrument,
                                transaction_type = (
                                    kite_live.TRANSACTION_TYPE_BUY
                                    if live_action == "BUY"
                                    else kite_live.TRANSACTION_TYPE_SELL
                                ),
                                quantity   = sig.lot_size,
                                product    = product,
                                order_type = kite_live.ORDER_TYPE_LIMIT,
                                price      = limit_price,
                            )
                            from app.core.charges import charges_for_entry_only as _cfe
                            live_trade = Trade(
                                signal_id = sig.id, mode = _TM2.LIVE,
                                symbol    = sig.instrument, underlying = sig.underlying,
                                option_type = sig.option_type, strike = sig.strike,
                                lot_size  = sig.lot_size, expiry_date = sig.expiry_date_iso,
                                expiry_display = sig.expiry_display,
                                action    = live_action, direction = sig.direction,
                                quantity  = sig.lot_size,
                                entry_price   = limit_price, current_price = limit_price,
                                target_price  = l_target, stop_loss = l_stop,
                                charges_entry = _cfe(limit_price, sig.lot_size, live_action),
                                # status PENDING until fill is confirmed by confirm_order_fills task
                                status    = _TS2.PENDING,
                                entry_time = datetime.utcnow(),
                                notes     = f"kite_order_id:{order_id}|limit:{limit_price}",
                            )
                            db.add(live_trade)
                            logger.info(
                                f"LIVE limit order placed: {sig.instrument} {live_action} "
                                f"@ ₹{limit_price:.1f} | order_id={order_id} | "
                                f"target ₹{l_target} stop ₹{l_stop}"
                            )
                        except Exception as e:
                            logger.error(f"Live order failed for {sig.instrument}: {e}")
                    await db.commit()
        except Exception as e:
            logger.warning(f"Live order placement skipped: {e}")

    # Subscribe option contracts to live ticker so MTM uses real premiums
    option_symbols = [
        sig.instrument for sig in signals
        if sig.instrument and sig.instrument != sig.underlying
        and sig.confidence_score >= HIGH_CONF_REAL
        and sig.estimated_premium and sig.lot_size
    ]
    if option_symbols:
        try:
            from app.core.data.kite_ticker import ticker_service
            ticker_service.subscribe_option_tokens(option_symbols)
        except Exception as e:
            logger.warning(f"Option token subscription failed: {e}")


# ── MTM updater ───────────────────────────────────────────────────────────────

async def _do_mtm_update():
    """
    Reprice all open paper trades with current option premiums.
    Updates unrealized_pnl net of total charges (entry already deducted, exit estimated).
    """
    from app.models.trades import Trade, TradeStatus
    from app.core.charges import calculate_charges
    from app.database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        q = select(Trade).where(
            Trade.status == TradeStatus.OPEN,
        )
        trades = (await db.execute(q)).scalars().all()

        if not trades:
            return

        symbols_needed: set[str] = {t.symbol for t in trades}
        prices: dict[str, float] = {}

        # 1. Read from live KiteTicker snapshot (zero-latency, WebSocket)
        try:
            from app.core.data.kite_ticker import ticker_service
            snapshot = ticker_service.get_snapshot()
            for sym in symbols_needed:
                data = snapshot.get(sym)
                if data and data.get("ltp", 0) > 0:
                    prices[sym] = data["ltp"]
        except Exception as e:
            logger.warning(f"MTM snapshot read failed: {e}")

        # 2. For any symbols not yet in snapshot, subscribe them and poll once via REST
        missing = symbols_needed - set(prices.keys())
        if missing:
            try:
                from app.core.data.kite_ticker import ticker_service
                ticker_service.subscribe_option_tokens(list(missing))
            except Exception:
                pass

            try:
                from kiteconnect import KiteConnect
                from app.config import settings
                if settings.kite_access_token and settings.kite_api_key:
                    kite = KiteConnect(api_key=settings.kite_api_key)
                    kite.set_access_token(settings.kite_access_token)
                    kite_syms = [f"NFO:{s}" for s in missing]
                    for i in range(0, len(kite_syms), 500):
                        batch = kite_syms[i:i+500]
                        try:
                            quotes = kite.quote(batch)
                            for ks, data in quotes.items():
                                sym = ks.replace("NFO:", "")
                                prices[sym] = data.get("last_price", 0)
                        except Exception as e:
                            logger.warning(f"MTM REST quote batch failed: {e}")
            except Exception as e:
                logger.warning(f"MTM Kite quote unavailable: {e}")

        # Build spot price lookup for BS fallback
        spot_prices: dict[str, float] = {}
        try:
            from app.core.data.kite_ticker import ticker_service
            snap = ticker_service.get_snapshot()
            for sym, data in snap.items():
                if data.get("ltp", 0) > 0:
                    spot_prices[sym] = data["ltp"]
        except Exception:
            pass

        now = datetime.utcnow()
        for trade in trades:
            current = prices.get(trade.symbol)

            # Fallback: reprice via Black-Scholes using live spot
            if not current and trade.strike and trade.option_type and trade.underlying:
                try:
                    from app.core.options.greeks import _bs_price, RISK_FREE_RATE
                    from app.core.options.chain_service import ChainService
                    from app.core.instruments import BASE_PRICES

                    spot = spot_prices.get(trade.underlying.upper()) or \
                           BASE_PRICES.get(trade.underlying.upper(), 0)
                    if spot > 0:
                        # DTE: days remaining to expiry (floor at 0.01 to avoid div-zero)
                        if trade.expiry_date:
                            from datetime import date as _date
                            exp_d = _date.fromisoformat(str(trade.expiry_date)[:10])
                            dte = max(0.5, (exp_d - _date.today()).days)
                        else:
                            dte = 7.0
                        T = dte / 365.0
                        # Use a reasonable IV estimate (18% base, no history available here)
                        iv = 0.18
                        current = round(_bs_price(spot, float(trade.strike), T,
                                                   RISK_FREE_RATE, iv, trade.option_type), 2)
                        current = max(0.05, current)
                except Exception as e:
                    logger.debug(f"BS fallback failed for {trade.symbol}: {e}")

            if not current:
                current = trade.current_price or trade.entry_price
            if not current:
                continue

            trade.current_price = current
            trade.last_mtm_at   = now

            # Gross P&L
            if trade.action == "BUY":
                gross = (current - trade.entry_price) * trade.quantity
            else:
                gross = (trade.entry_price - current) * trade.quantity

            # Estimate exit charges at current price (will be recalculated exactly at close)
            charges = calculate_charges(
                entry_premium=trade.entry_price,
                exit_premium=current,
                quantity=trade.quantity,
                action=trade.action,
            )
            trade.unrealized_pnl = round(gross - charges.total, 2)

            # ── Trailing stop: activate once up 30%, lock in 50% of gain ────────
            if trade.action == "BUY" and trade.entry_price > 0:
                gain_pct = (current - trade.entry_price) / trade.entry_price
                if gain_pct >= 0.30:
                    # Trail stop to entry + 50% of current gain
                    trail_stop = round(trade.entry_price + (current - trade.entry_price) * 0.50, 2)
                    if trail_stop > trade.stop_loss:
                        if not getattr(trade, '_trail_logged', False):
                            logger.info(
                                f"Trailing stop activated: {trade.symbol} "
                                f"entry={trade.entry_price} current={current:.2f} "
                                f"old_stop={trade.stop_loss:.2f} new_stop={trail_stop:.2f}"
                            )
                        trade.stop_loss = trail_stop
                        if trade.notes:
                            if "trail_stop" not in trade.notes:
                                trade.notes = (trade.notes or "") + f"|trail_stop:{trail_stop}"
                        else:
                            trade.notes = f"trail_stop:{trail_stop}"
            elif trade.action == "SELL" and trade.entry_price > 0:
                # For short options: close when premium has decayed 50%+
                # trail target down to lock in 50% of current profit
                decay_pct = (trade.entry_price - current) / trade.entry_price
                if decay_pct >= 0.30:
                    trail_target = round(trade.entry_price - (trade.entry_price - current) * 0.50, 2)
                    if trail_target < trade.target_price or trade.target_price <= 0:
                        trade.target_price = max(0.05, trail_target)

            # Stop loss / target hit check
            if trade.action == "BUY":
                if current >= trade.target_price:
                    await _close_trade(trade, current, "target_hit", db)
                    continue
                elif current <= trade.stop_loss:
                    await _close_trade(trade, current, "stop_hit", db)
                    continue
            else:
                if current <= trade.target_price:
                    await _close_trade(trade, current, "target_hit", db)
                    continue
                elif current >= trade.stop_loss:
                    await _close_trade(trade, current, "stop_hit", db)
                    continue

        await db.commit()
        logger.info(f"MTM update: {len(trades)} open trades repriced")


async def _close_trade(trade, exit_price: float, reason: str, db):
    """Book a trade as closed, compute final charges and net P&L."""
    from app.models.trades import TradeStatus
    from app.models.portfolio import Portfolio
    from app.core.charges import calculate_charges
    from sqlalchemy import select

    charges = calculate_charges(
        entry_premium=trade.entry_price,
        exit_premium=exit_price,
        quantity=trade.quantity,
        action=trade.action,
    )

    if trade.action == "BUY":
        gross = (exit_price - trade.entry_price) * trade.quantity
    else:
        gross = (trade.entry_price - exit_price) * trade.quantity

    net_pnl = gross - charges.total

    trade.exit_price      = exit_price
    trade.exit_time       = datetime.utcnow()
    trade.status          = TradeStatus.CLOSED
    trade.exit_reason     = reason
    trade.gross_pnl       = round(gross, 2)
    trade.realized_pnl    = round(net_pnl, 2)
    trade.pnl             = round(net_pnl, 2)
    trade.unrealized_pnl  = None
    trade.charges_total   = round(charges.total, 2)
    trade.charges_brokerage = round(charges.brokerage, 2)
    trade.charges_stt     = round(charges.stt, 2)
    trade.charges_txn     = round(charges.exchange_txn, 2)
    trade.charges_gst     = round(charges.gst, 2)
    trade.charges_sebi    = round(charges.sebi, 2)
    trade.charges_stamp   = round(charges.stamp_duty, 2)

    trade_cost = trade.entry_price * trade.quantity
    entry_charges_paid = trade.charges_entry or 0.0
    if trade.quantity > 0 and trade.entry_price > 0:
        trade.pnl_pct = round(net_pnl / trade_cost * 100, 2)

    # Return capital to portfolio (works for both paper and live modes)
    result = await db.execute(select(Portfolio).where(Portfolio.mode == trade.mode))
    portfolio = result.scalar_one_or_none()
    if portfolio:
        # capital was originally deducted as: trade_cost + entry_charges
        # On close: return that full amount, then add net_pnl (which already nets exit charges)
        recovered = trade_cost + entry_charges_paid + net_pnl
        portfolio.capital_current  += recovered
        portfolio.capital_deployed  = max(0, portfolio.capital_deployed - trade_cost)
        portfolio.daily_pnl         = (portfolio.daily_pnl or 0) + net_pnl
        portfolio.total_pnl         = (portfolio.total_pnl or 0) + net_pnl
        portfolio.total_trades   = (portfolio.total_trades or 0) + 1
        portfolio.weekly_pnl     = (portfolio.weekly_pnl or 0) + net_pnl
        if net_pnl > 0:
            portfolio.winning_trades = (portfolio.winning_trades or 0) + 1
        else:
            portfolio.losing_trades  = (portfolio.losing_trades or 0) + 1

        # Peak capital & max drawdown tracking
        new_capital = portfolio.capital_current
        if new_capital > (portfolio.peak_capital or 0):
            portfolio.peak_capital = new_capital
        peak = portfolio.peak_capital or portfolio.capital_initial or new_capital
        if peak > 0:
            dd_pct = (peak - new_capital) / peak * 100
            if dd_pct > (portfolio.max_drawdown_pct or 0):
                portfolio.max_drawdown_pct = round(dd_pct, 4)

    logger.info(
        f"Trade closed: {trade.symbol} | {reason} | "
        f"gross ₹{gross:.2f} | charges ₹{charges.total:.2f} | net ₹{net_pnl:.2f}"
    )
    # Update daily risk gate P&L and release deployed capital
    try:
        from app.core.risk.gate import record_pnl, record_deployed as _release_deployed
        record_pnl(net_pnl)
        _release_deployed(-(trade_cost + entry_charges_paid))   # negative = release
    except Exception:
        pass


# ── Expiry settler ────────────────────────────────────────────────────────────

async def _do_expiry_settlement():
    """
    Close all paper trades whose expiry_date <= today at their settlement price.
    Runs at 15:31 IST so final prices are available.
    For options:
      - Expired worthless (OTM): settlement price = 0
      - ITM: intrinsic value (spot - strike for CE, strike - spot for PE)
    """
    from app.models.trades import Trade, TradeStatus
    from app.database import AsyncSessionLocal
    from sqlalchemy import select

    today = date.today()

    async with AsyncSessionLocal() as db:
        q = select(Trade).where(
            Trade.status      == TradeStatus.OPEN,
            Trade.expiry_date <= today.isoformat(),
        )
        trades = (await db.execute(q)).scalars().all()

        if not trades:
            logger.info("Expiry settlement: no trades to settle")
            return

        # Get spot prices for settlement
        spot_prices: dict[str, float] = {}
        try:
            from kiteconnect import KiteConnect
            from app.config import settings
            if settings.kite_access_token:
                kite = KiteConnect(api_key=settings.kite_api_key)
                kite.set_access_token(settings.kite_access_token)
                underlyings = {t.underlying for t in trades}
                for u in underlyings:
                    try:
                        q_result = kite.quote([f"NSE:{u}"])
                        spot_prices[u] = q_result.get(f"NSE:{u}", {}).get("last_price", 0)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Expiry settlement: could not fetch spot prices: {e}")

        for trade in trades:
            spot = spot_prices.get(trade.underlying, 0)
            settlement_price = 0.0

            if spot and trade.strike and trade.option_type:
                if trade.option_type == "CE":
                    settlement_price = max(0.0, spot - trade.strike)
                else:  # PE
                    settlement_price = max(0.0, trade.strike - spot)

            await _close_trade(trade, settlement_price, "expiry_settlement", db)
            logger.info(
                f"Expiry settlement: {trade.symbol} spot={spot:.2f} "
                f"settlement={settlement_price:.2f}"
            )

        await db.commit()
        logger.info(f"Expiry settlement complete: {len(trades)} trades closed")


# ── EOD intraday closer ───────────────────────────────────────────────────────

async def _do_eod_close_intraday():
    """
    Close all open INTRADAY paper trades at 15:20 IST before broker auto-square-off.
    Only closes trades whose signal had trading_style='intraday' (15m/1h timeframes).
    Positional trades (4h/daily) are left open.
    """
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.models.signals import Signal
    from app.database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        q = select(Trade).where(
            Trade.status == TradeStatus.OPEN,
            Trade.mode   == TradeMode.PAPER,
        )
        open_trades = (await db.execute(q)).scalars().all()

        if not open_trades:
            logger.info("EOD close: no open trades to close")
            return

        # Get signal info to identify intraday trades
        sig_ids = [t.signal_id for t in open_trades if t.signal_id]
        sig_map: dict[int, Signal] = {}
        if sig_ids:
            sigs = (await db.execute(
                select(Signal).where(Signal.id.in_(sig_ids))
            )).scalars().all()
            sig_map = {s.id: s for s in sigs}

        closed = 0
        for trade in open_trades:
            sig = sig_map.get(trade.signal_id) if trade.signal_id else None
            style = sig.trading_style if sig else "intraday"  # default assume intraday

            # Only close intraday; leave positional open overnight
            if style not in ("intraday", None):
                continue

            # Use current_price or entry_price as exit
            exit_px = trade.current_price or trade.entry_price
            await _close_trade(trade, exit_px, "eod_squareoff", db)
            closed += 1

        await db.commit()
        logger.info(f"EOD close: squared off {closed} intraday paper trades")


@celery_app.task(name="workers.eod_close_intraday")
def eod_close_intraday():
    """Square off all open intraday paper trades at 15:20 before broker auto-square-off."""
    logger.info("EOD intraday close starting")
    try:
        _run_async(_do_eod_close_intraday())
    except Exception as exc:
        logger.error(f"EOD close failed: {exc}")


# ── Core scan logic ───────────────────────────────────────────────────────────

async def _do_scan(symbols: list[str], timeframes: list[str]):
    from app.core.scanner import run_full_scan
    from app.database import AsyncSessionLocal
    from app.api.websocket import manager

    async with AsyncSessionLocal() as db:
        result = await run_full_scan(
            symbols=symbols, timeframes=timeframes,
            broadcast_fn=manager.broadcast, db=db,
        )
        await _persist_and_broadcast(result["signals"], db, manager.broadcast)
    return result


# ── Celery tasks ──────────────────────────────────────────────────────────────

@celery_app.task(name="workers.scan_priority_instruments", bind=True, max_retries=2)
def scan_priority_instruments(self, timeframes: list[str] | None = None):
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
    from app.core.instruments import priority_scan_list
    symbols = priority_scan_list()   # respects TESTING_FOCUS when set
    tfs = timeframes or ["1h", "4h", "daily"]
    logger.info(f"Full scan: {len(symbols)} symbols × {tfs}")
    try:
        return _run_async(_do_scan(symbols, tfs))
    except Exception as exc:
        logger.error(f"Full scan failed: {exc}")
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(name="workers.run_signal_scan")
def run_signal_scan(underlying: str = "NIFTY"):
    return _run_async(_do_scan([underlying], ["15m", "1h", "daily"]))


@celery_app.task(name="workers.mtm_update")
def mtm_update():
    """Reprice all open paper positions with current option premiums."""
    logger.info("MTM update starting")
    try:
        _run_async(_do_mtm_update())
    except Exception as exc:
        logger.error(f"MTM update failed: {exc}")


@celery_app.task(name="workers.expiry_settlement")
def expiry_settlement():
    """Settle all expired paper trades at intrinsic value."""
    logger.info("Expiry settlement starting")
    try:
        _run_async(_do_expiry_settlement())
    except Exception as exc:
        logger.error(f"Expiry settlement failed: {exc}")


@celery_app.task(name="workers.sync_market_data")
def sync_market_data(underlying: str = "NIFTY"):
    """Download missing market data (bhav, VIX, FII) and rebuild PCR cache."""
    try:
        from app.core.backtest.market_data import (
            build_pcr_from_cached_bhav, fetch_india_vix, fetch_fii_fo_data
        )
        from app.core.instruments import priority_scan_list
        syms = priority_scan_list()

        # Bootstrap PCR cache from any already-downloaded bhav files
        total_pcr = 0
        for sym in syms:
            added = build_pcr_from_cached_bhav(sym)
            total_pcr += added

        # Trigger lazy downloads in background threads
        fetch_india_vix()
        fetch_fii_fo_data()

        logger.info(f"Market data sync: {total_pcr} PCR dates bootstrapped for {len(syms)} symbols")
        return {"status": "ok", "pcr_added": total_pcr, "timestamp": datetime.utcnow().isoformat()}
    except Exception as exc:
        logger.error(f"Market data sync failed: {exc}")
        return {"status": "error", "error": str(exc)}


async def _do_cleanup_stale_signals():
    """
    1. Expire ACTIVE signals whose valid_until has passed.
    2. Delete signals older than 48h with corrupted data (stale _FUT instruments or null expiry).
    """
    from app.models.signals import Signal, SignalStatus
    from app.database import AsyncSessionLocal
    from sqlalchemy import update, delete, and_, or_

    now = datetime.utcnow()
    cutoff_48h = now - timedelta(hours=48)

    async with AsyncSessionLocal() as db:
        # 1. Expire signals past their valid_until
        expire_stmt = (
            update(Signal)
            .where(
                Signal.status == SignalStatus.ACTIVE,
                Signal.valid_until <= now,
            )
            .values(status=SignalStatus.EXPIRED)
        )
        expired = await db.execute(expire_stmt)

        # 2. Delete corrupt/FUT signals older than 48h
        delete_stmt = delete(Signal).where(and_(
            Signal.created_at < cutoff_48h,
            or_(
                Signal.instrument.like("%_FUT"),
                Signal.expiry_date_iso == None,
            )
        ))
        deleted = await db.execute(delete_stmt)
        await db.commit()
        logger.info(
            f"Signal cleanup: expired {expired.rowcount} past valid_until, "
            f"deleted {deleted.rowcount} corrupt signals"
        )


@celery_app.task(name="workers.cleanup_stale_signals")
def cleanup_stale_signals():
    """Remove stale/corrupted signals older than 48h."""
    try:
        _run_async(_do_cleanup_stale_signals())
    except Exception as exc:
        logger.error(f"Signal cleanup failed: {exc}")


# ── Daily P&L reset ───────────────────────────────────────────────────────────

@celery_app.task(name="workers.reset_daily_pnl")
def reset_daily_pnl():
    """
    Reset daily P&L counter and deployed-capital tracker in Redis at 9:15 IST.
    Without this the daily-loss circuit breaker stays tripped permanently after
    a losing day and blocks all new trades.
    """
    try:
        from app.core.risk.gate import reset_daily_pnl as _reset
        _reset()
        logger.info("Daily P&L counter reset for new trading day")
    except Exception as exc:
        logger.error(f"Daily P&L reset failed: {exc}")


@celery_app.task(name="workers.reset_weekly_pnl")
def reset_weekly_pnl():
    """Reset weekly_pnl on portfolio rows every Monday at 9:15 IST."""
    async def _run():
        from app.database import AsyncSessionLocal
        from app.models.portfolio import Portfolio
        from sqlalchemy import select, update

        async with AsyncSessionLocal() as db:
            await db.execute(update(Portfolio).values(weekly_pnl=0.0))
            await db.commit()
            logger.info("Weekly P&L reset for all portfolios")

    try:
        _run_async(_run())
    except Exception as exc:
        logger.error(f"Weekly P&L reset failed: {exc}")


# ── Order fill confirmation ───────────────────────────────────────────────────

async def _do_confirm_order_fills():
    """
    Poll Kite for PENDING live trades and update entry_price + status once filled.
    Cancels orders that are still open after 5 minutes (stale limit orders).
    """
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.database import AsyncSessionLocal
    from sqlalchemy import select
    import re as _re

    async with AsyncSessionLocal() as db:
        q = select(Trade).where(
            Trade.mode   == TradeMode.LIVE,
            Trade.status == TradeStatus.PENDING,
        )
        pending = (await db.execute(q)).scalars().all()
        if not pending:
            return

        try:
            from kiteconnect import KiteConnect
            from app.config import settings as _s
            if not (_s.kite_api_key and _s.kite_access_token):
                return
            kite = KiteConnect(api_key=_s.kite_api_key)
            kite.set_access_token(_s.kite_access_token)
        except Exception as e:
            logger.warning(f"Order fill confirmation: Kite unavailable: {e}")
            return

        now = datetime.utcnow()
        for trade in pending:
            # Extract order_id from notes field: "kite_order_id:123456789|limit:150.0"
            m = _re.search(r'kite_order_id:(\d+)', trade.notes or "")
            if not m:
                continue
            order_id = m.group(1)

            try:
                history = kite.order_history(order_id)
                if not history:
                    continue
                latest = history[-1]
                kite_status = latest.get("status", "")

                if kite_status == "COMPLETE":
                    fill_price = float(latest.get("average_price") or latest.get("price") or trade.entry_price)
                    trade.entry_price   = fill_price
                    trade.current_price = fill_price
                    trade.status        = TradeStatus.OPEN
                    # Recompute target/stop based on actual fill price
                    if trade.action == "BUY":
                        trade.target_price = round(fill_price * 1.50, 2)
                        trade.stop_loss    = round(fill_price * 0.60, 2)
                    else:
                        trade.target_price = round(fill_price * 0.45, 2)
                        trade.stop_loss    = round(fill_price * 2.00, 2)
                    logger.info(
                        f"Order confirmed: {trade.symbol} {trade.action} "
                        f"filled @ ₹{fill_price:.2f} (order {order_id})"
                    )

                elif kite_status in ("REJECTED", "CANCELLED"):
                    trade.status     = TradeStatus.CANCELLED
                    trade.exit_time  = now
                    trade.exit_reason = f"order_{kite_status.lower()}"
                    logger.warning(f"Order {order_id} {kite_status}: {trade.symbol} — removing pending trade")

                else:
                    # Still OPEN/TRIGGER PENDING — cancel if placed > 5 min ago
                    age_min = (now - trade.entry_time).total_seconds() / 60
                    if age_min > 5:
                        try:
                            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
                            trade.status      = TradeStatus.CANCELLED
                            trade.exit_time   = now
                            trade.exit_reason = "order_timeout"
                            logger.info(f"Cancelled stale limit order {order_id} ({trade.symbol}, {age_min:.1f}m old)")
                        except Exception as ce:
                            logger.warning(f"Could not cancel order {order_id}: {ce}")

            except Exception as e:
                logger.warning(f"Order history fetch failed for {order_id}: {e}")

        await db.commit()
        logger.info(f"Order fill check: {len(pending)} pending trades processed")


@celery_app.task(name="workers.confirm_order_fills")
def confirm_order_fills():
    """Confirm pending live order fills and cancel stale limit orders."""
    try:
        _run_async(_do_confirm_order_fills())
    except Exception as exc:
        logger.error(f"Order fill confirmation failed: {exc}")


# ── Nightly pattern backtests ─────────────────────────────────────────────────

@celery_app.task(name="workers.run_nightly_backtests")
def run_nightly_backtests():
    """
    Run walk-forward backtests for all priority instruments × all patterns.
    Skips any (underlying, pattern, timeframe) that was run within the last 7 days.
    Results are stored in pattern_backtests / pattern_trades tables and used by
    the live scanner to filter signals to only proven-edge patterns.
    """
    async def _run():
        from app.api.v1.pattern_finder import _run_backtests_bg
        from app.models.pattern_backtest import PatternBacktest, BacktestStatus
        from app.core.patterns.registry import PatternRegistry
        from app.core.instruments import priority_scan_list
        from app.database import AsyncSessionLocal
        from sqlalchemy import select, desc
        from datetime import date, timedelta

        syms  = priority_scan_list()[:8]   # top 8 instruments to keep runtime reasonable
        pats  = [p.name for p in PatternRegistry.get().all()]
        tfs   = ["daily", "1h"]
        today = date.today().isoformat()
        year_ago = (date.today() - timedelta(days=365)).isoformat()
        run_ids = []

        async with AsyncSessionLocal() as db:
            for sym in syms:
                for pat in pats:
                    for tf in tfs:
                        ex_q = await db.execute(
                            select(PatternBacktest).where(
                                PatternBacktest.underlying   == sym,
                                PatternBacktest.pattern_name == pat,
                                PatternBacktest.timeframe    == tf,
                                PatternBacktest.status       == BacktestStatus.COMPLETE,
                            ).order_by(desc(PatternBacktest.created_at)).limit(1)
                        )
                        ex = ex_q.scalar_one_or_none()
                        if ex and ex.created_at and (date.today() - ex.created_at.date()).days < 7:
                            continue

                        bt = PatternBacktest(
                            underlying=sym, pattern_name=pat, timeframe=tf,
                            date_from=year_ago, date_to=today,
                            status=BacktestStatus.PENDING,
                        )
                        db.add(bt)
                        await db.flush()
                        run_ids.append(bt.id)
            await db.commit()

        if run_ids:
            await _run_backtests_bg(run_ids)
            logger.info(f"Nightly backtests complete: {len(run_ids)} runs")
        else:
            logger.info("Nightly backtests: all patterns up-to-date, nothing to run")

    try:
        _run_async(_run())
    except Exception as exc:
        logger.error(f"Nightly backtests failed: {exc}")


@celery_app.task(name="workers.run_nightly_discovery")
def run_nightly_discovery():
    """
    Nightly auto-discovery: run statistical miner + decision tree on all priority
    instruments, persist discovered patterns, then walk-forward backtest the top
    ones to confirm edge before they enter the live scanner.
    """
    async def _run():
        from app.api.v1.pattern_finder import _run_discovery_bg
        from app.core.instruments import priority_scan_list
        syms = priority_scan_list()[:8]
        tfs  = ["daily", "1h"]
        await _run_discovery_bg(syms, tfs)
        logger.info(f"Nightly discovery complete: {len(syms)} instruments × {len(tfs)} timeframes")

    try:
        _run_async(_run())
    except Exception as exc:
        logger.error(f"Nightly discovery failed: {exc}")
