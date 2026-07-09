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
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        # Dispose the async engine's connection pool before closing the loop.
        # asyncpg connections are bound to the event loop they were created in;
        # if we close the loop without disposing, the next task's new loop gets
        # "RuntimeError: Event loop is closed" when the pool tries to reuse them.
        try:
            from app.database import engine
            loop.run_until_complete(engine.dispose())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


def _stamp_task_run(celery_task_name: str) -> None:
    """Write task_last_run:<name> = ISO timestamp to Redis so /system/schedule shows it."""
    try:
        import redis as redis_lib
        from app.config import settings
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.set(f"task_last_run:{celery_task_name}", datetime.utcnow().isoformat(), ex=7 * 86400)
    except Exception:
        pass


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

        # Expire any active signal for this pattern that points the opposite direction.
        await db.execute(
            __import__("sqlalchemy", fromlist=["update"]).update(Signal)
            .where(and_(
                Signal.underlying   == s["underlying"],
                Signal.pattern_name == s["pattern_name"],
                Signal.direction    != s["direction"],
                Signal.status       == SignalStatus.ACTIVE,
            ))
            .values(status=SignalStatus.EXPIRED)
        )
        # Skip if an ACTIVE signal with the same key already exists (no time limit).
        # Include option_type so a CE and PE on the same pattern are distinct signals.
        q = select(Signal).where(and_(
            Signal.underlying    == s["underlying"],
            Signal.pattern_name  == s["pattern_name"],
            Signal.direction     == s["direction"],
            Signal.option_type   == s.get("option_type"),
            Signal.status        == SignalStatus.ACTIVE,
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


def _build_trade_notes(sig, action: str, premium: float, risk, hedge_trade_data) -> str:
    """Build a human-readable explanation for why this trade was placed."""
    iv_pct = round((sig.iv_at_signal or 0) * 100, 1) if (sig.iv_at_signal or 0) < 2 else round(sig.iv_at_signal or 0, 1)
    ivr = round(getattr(sig, "iv_rank", 0) or 0, 2)
    conf = round(sig.confidence_score or 0, 2)
    expiry_lbl = sig.expiry_display or sig.expiry_date_iso or "?"
    strike = sig.strike or "ATM"

    lines = [
        f"WHY: {sig.pattern_name} pattern triggered a {sig.direction.upper()} signal on {sig.underlying}.",
        f"Confidence: {conf:.0%} | IV: {iv_pct:.1f}% | IV Rank: {ivr:.0%}",
        f"Strike: {strike} {sig.option_type} | Expiry: {expiry_lbl} ({sig.expiry_dte or '?'}d DTE)",
        f"Action: {action} @ ₹{premium:.2f} | Target: ₹{round(premium*1.5,2) if action=='BUY' else round(premium*0.45,2)} | Stop: ₹{round(premium*0.6,2) if action=='BUY' else round(premium*2.0,2)}",
    ]
    if sig.explanation:
        lines.append(f"Signal: {sig.explanation[:200]}")
    if hedge_trade_data:
        lines.append(f"Hedge: BUY {hedge_trade_data['symbol']} @ ₹{hedge_trade_data['premium']:.2f} (credit spread)")
    lines.append(f"Risk/lot: ₹{risk.capital_at_risk:.0f} | Qty: {risk.recommended_qty} lot(s)")
    return " | ".join(lines)


async def _auto_paper_trade(signals, db):
    """
    Auto-execute trades for high-confidence signals DURING MARKET HOURS ONLY (09:20–15:25 IST).
    - Real-data signals (Kite OHLCV): confidence ≥ 0.72
    - Synthetic-data signals: confidence ≥ 0.82
    One trade per (underlying, pattern_name, direction). Entry charges deducted immediately.
    Hedge leg auto-added for all SELL positions.
    """
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.models.portfolio import Portfolio
    from app.core.charges import charges_for_entry_only
    from sqlalchemy import select

    # Gate: block all auto-execution outside market hours
    if not _is_market_hours():
        return []

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

    async def _fetch_option_ltp(
        cfg,                        # KiteConfig ORM row (may be None)
        underlying: str,
        expiry_iso: str,
        strike: float,
        opt_type: str,
        our_sym: str,
    ) -> tuple[float | None, str, int | None]:
        """
        Round-robin Kite ↔ Upstox for real-time option LTP.
        Returns (price, source_label, instrument_token) or (None, "none", None).
        instrument_token is non-None only when Kite is the source — store it on the
        trade so MTM can use kite.ltp([token]) which works for all option types.

        Turn selection stored in Redis key "ltp_turn" (0=Kite, 1=Upstox).
        Each call flips the turn so load is shared 50/50.
        If the selected provider fails the other is tried automatically.
        NSE chain is NOT called here — caller handles it as last resort.
        """
        import calendar as _cal
        from datetime import date as _d2
        from app.core.encryption import decrypt as _dec

        def _kite_sym(ul, exp_iso, stk, ot):
            # NSE moved all index expiries to TUESDAY effective Sep 2025.
            # Monthly = last Tuesday of month → MON3 format (e.g. NIFTY26JUL24000PE)
            # Weekly  = any other Tuesday    → YYMMDD format (e.g. NIFTY2671424000PE)
            # BSE (SENSEX/BANKEX) still uses Thursday — not handled here (NSE only).
            try:
                exp = _d2.fromisoformat(exp_iso)
                yy = str(exp.year)[2:]
                mon3 = exp.strftime("%b").upper()
                last_tue = max(
                    _d2(exp.year, exp.month, dd)
                    for dd in range(1, _cal.monthrange(exp.year, exp.month)[1] + 1)
                    if _d2(exp.year, exp.month, dd).weekday() == 1  # 1 = Tuesday
                )
                base = f"{int(stk)}{ot}"
                if exp == last_tue:
                    return f"{ul}{yy}{mon3}{base}"
                return f"{ul}{yy}{exp.month}{exp.day:02d}{base}"
            except Exception:
                return None

        today = _d2.today()
        kite_ok = bool(cfg and cfg.access_token_enc and cfg.token_date == today)
        upstox_ok = bool(cfg and cfg.upstox_access_token_enc and cfg.upstox_token_date == today)

        # Determine turn via Redis (flip atomically)
        turn = 0  # 0=Kite, 1=Upstox
        try:
            import redis as _redis_lib
            from app.config import settings as _st
            _r = _redis_lib.from_url(_st.redis_url, decode_responses=True)
            raw = _r.get("ltp_turn")
            turn = int(raw) if raw is not None else 0
            _r.set("ltp_turn", 1 - turn)  # flip for next call
        except Exception:
            pass

        providers = []
        if turn == 0:
            providers = (["kite", "upstox"] if upstox_ok else ["kite"]) if kite_ok else (["upstox"] if upstox_ok else [])
        else:
            providers = (["upstox", "kite"] if kite_ok else ["upstox"]) if upstox_ok else (["kite"] if kite_ok else [])

        from time import perf_counter as _pc
        from app.core.data.provider_health import record_success, record_failure

        for provider in providers:
            _t0 = _pc()
            try:
                if provider == "kite" and kite_ok:
                    from kiteconnect import KiteConnect as _KCS
                    kite_s = _kite_sym(underlying, expiry_iso, strike, opt_type)
                    if not kite_s:
                        continue
                    _k = _KCS(api_key=cfg.api_key)
                    _k.set_access_token(_dec(cfg.access_token_enc))
                    res = _k.ltp([f"NFO:{kite_s}"])
                    for v in res.values():
                        p = v.get("last_price", 0)
                        if p > 0:
                            tok = v.get("instrument_token")
                            record_success("kite", (_pc() - _t0) * 1000)
                            return float(p), "kite", (int(tok) if tok else None)
                    record_failure("kite", f"empty ltp for {kite_s}")
                elif provider == "upstox" and upstox_ok:
                    from app.core.data.upstox_ltp import get_ltp as _upltp
                    token = _dec(cfg.upstox_access_token_enc)
                    p = _upltp(token, underlying, expiry_iso, strike, opt_type)
                    if p and p > 0:
                        record_success("upstox", (_pc() - _t0) * 1000)
                        return p, "upstox", None
                    record_failure("upstox", f"no ltp for {our_sym}")
            except Exception as _e:
                record_failure(provider, str(_e))
                logger.debug(f"LTP provider {provider} failed for {our_sym}: {_e}")

        return None, "none", None

    def _hedge_premium(underlying: str, spot: float, hedge_strike: float,
                       opt_type: str, expiry_date_iso: str) -> float:
        """
        Hedge leg premium — prefer chain LTP (real market price) over Black-Scholes.
        Using BS with a fixed sigma causes a systematic overestimate when real IV is low,
        which made hedge premiums appear MORE expensive than the main leg.
        """
        # 1. Try live chain LTP first
        try:
            from app.core.options.chain_service import ChainService
            import pandas as _pd
            chain = ChainService().get_chain(underlying)
            ltp_col = "ce_ltp" if opt_type == "CE" else "pe_ltp"
            row = chain.iloc[(chain["strike"] - hedge_strike).abs().argsort()[:1]].iloc[0]
            ltp = float(row.get(ltp_col, 0) or 0)
            if ltp >= 0.05:
                return round(ltp, 2)
        except Exception:
            pass
        # 2. Fall back to Black-Scholes with a more realistic IV estimate
        try:
            from datetime import date as _date
            from app.core.options.chain_service import ChainService
            from app.core.options.iv_rank import IVRankService
            iv_hist = ChainService().get_iv_history(underlying)
            chain = ChainService().get_chain(underlying)
            try:
                atm_row = chain.iloc[(chain["strike"] - spot).abs().argsort()[:1]].iloc[0]
                raw_iv = float(atm_row.get("ce_iv") or 0)
                sigma = raw_iv * 100 if raw_iv < 2 else raw_iv
                sigma = sigma / 100.0 if sigma > 2.0 else sigma
                if sigma < 0.08 or sigma > 0.80:
                    sigma = 0.15
            except Exception:
                sigma = 0.15
            dte = max(1, (_date.fromisoformat(expiry_date_iso) - _date.today()).days)
            T = dte / 365.0
            return round(max(0.05, _bs_price(spot, hedge_strike, T, _RF, sigma, opt_type)), 2)
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
        # HARD market-hours gate for ALL entries (not just synthetic).
        # The 09:00 pre-market scan and 15:35 EOD scan were auto-executing on
        # previous-close/frozen prices — no real order could fill at those
        # prices (user caught a 15:45 IST entry, 2026-07-08).
        if not market_open:
            logger.info(f"Skipping entry {sig.pattern_name}/{sig.underlying}: outside market hours (09:20-15:25 IST)")
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
        # Block near RBI/FOMC/expiry events — but NOT patterns that specifically
        # exploit expiry mechanics (max_pain, expiry_week thrive near expiry).
        _EXPIRY_SAFE = {"max_pain", "expiry_week"}
        if sig.pattern_name not in _EXPIRY_SAFE:
            try:
                from app.core.options.event_calendar import EventCalendar
                from datetime import date as _today_dt
                if EventCalendar().is_event_risk(_today_dt.today(), dte=1):
                    logger.info(f"Skipping {sig.pattern_name}/{sig.underlying}: event risk window (RBI/FOMC/expiry within 1 day)")
                    continue
            except Exception:
                pass

        # ── Tue-Thu entry rule (adopted 2026-07-04, tested on real data) ──────
        # 21mo Upstox study: Mon entries PF 0.57, Fri PF 0.66 vs Tue-Thu 1.4-2.3
        # (weekend gaps bracket the position's most fragile first days).
        # Also blocks Sat/Sun: broker LTP endpoints serve stale Friday closes
        # on weekends — a trade "filled" then is priced on a frozen market.
        if date.today().weekday() not in (1, 2, 3):
            logger.info(f"Skipping {sig.underlying} entry: Tue-Thu rule (weekday={date.today().weekday()})")
            continue

        premium  = sig.estimated_premium

        # ── Entry price: Kite ↔ Upstox round-robin → NSE chain → BS ─────────
        # Load KiteConfig once (has both Kite + Upstox tokens)
        _entry_cfg = None
        try:
            from app.models.kite_config import KiteConfig as _EntryCfg
            from app.database import AsyncSessionLocal as _EDB
            from sqlalchemy import select as _esel
            async with _EDB() as _es:
                _entry_cfg = (await _es.execute(_esel(_EntryCfg).limit(1))).scalar_one_or_none()
        except Exception:
            pass

        # 1. Try Kite / Upstox round-robin
        _live_ltp, _ltp_src, _entry_token = await _fetch_option_ltp(
            _entry_cfg, sig.underlying, sig.expiry_date_iso,
            sig.strike, sig.option_type, sig.instrument or sig.underlying,
        )
        if _live_ltp and _live_ltp > 0:
            premium = _live_ltp
            logger.info(f"Entry {_ltp_src.upper()} LTP: {sig.instrument} = ₹{premium} (BS was ₹{sig.estimated_premium})")

        # 2. NSE chain fallback (jugaad-data — last resort before BS)
        if not _live_ltp:
            try:
                from app.core.options.chain_service import ChainService as _CS
                _chain = _CS().get_chain(sig.underlying, expiry_iso=sig.expiry_date_iso)
                _row = _chain[_chain["strike"] == sig.strike] if not _chain.empty else None
                if _row is not None and not _row.empty:
                    ltp_col = "ce_ltp" if sig.option_type == "CE" else "pe_ltp"
                    _ltp = float(_row[ltp_col].iloc[0])
                    if _ltp > 5:
                        premium = _ltp
                        logger.info(f"Entry NSE chain LTP: {sig.instrument} = ₹{premium} (BS was ₹{sig.estimated_premium})")
            except Exception as _e:
                logger.debug(f"Entry NSE chain failed for {sig.instrument}: {_e}")

        quantity = sig.lot_size

        # ── Build composite multi-leg strategy (no naked positions) ───────────
        from app.core.strategies.composite import (
            build_composite, net_credit as _net_credit,
            strategy_name as _strat_name, strategy_rationale as _strat_rationale,
        )
        from app.core.options.expiry import available_expiries as _avail_exp

        _spot_now = _spot_price(sig.underlying)
        _step = _STEPS.get(sig.underlying.upper(), 50)
        _iv = sig.iv_at_signal or 0.18
        if _iv > 2.0:
            _iv /= 100.0
        _iv_rank = getattr(sig, "iv_rank", 0.3) or 0.3

        _avail = _avail_exp(sig.underlying, date.today())

        # ── Live condor experiment (2026-07-03): every 3rd directional signal
        # opens a skewed condor at 1 lot instead of a plain spread, so both
        # structures face identical markets. Compare via strategy filter in
        # Positions. BS backtest rejected condors; this tests REAL credits.
        _is_condor_exp = False
        if (sig.pattern_name or "").lower() not in ("iv_crush", "expiry_week"):
            try:
                import redis as _rc
                from app.config import settings as _sc
                _cnt = _rc.from_url(_sc.redis_url, decode_responses=True).incr("exp_condor_counter")
                _is_condor_exp = (_cnt % 3 == 0)
            except Exception:
                pass

        if _is_condor_exp:
            from app.core.strategies.composite import build_skewed_condor
            composite_legs = build_skewed_condor(
                underlying=sig.underlying, spot=_spot_now,
                direction=sig.direction or "long", iv=_iv, iv_rank=_iv_rank,
                available_expiries=_avail, step=_step,
            )
        else:
            composite_legs = build_composite(
                underlying        = sig.underlying,
                spot              = _spot_now,
                direction         = sig.direction or "long",
                iv_rank           = _iv_rank,
                iv                = _iv,
                pattern_name      = sig.pattern_name,
                available_expiries= _avail,
                step              = _step,
            )

        if not composite_legs or len(composite_legs) < 2:
            logger.warning(f"Composite strategy builder returned < 2 legs for {sig.underlying} — skipping")
            continue

        # DTE cap: beyond ~21 days theta accrual is too slow to beat friction
        # (observed live 2026-07-02: BANKNIFTY 26-DTE decay invisible vs mark
        # noise). Skip entries whose nearest expiry is too far out — mostly
        # affects BANKNIFTY right after monthly expiry rolls.
        _min_dte = min(l.expiry_dte for l in composite_legs)
        if _min_dte > 21:
            logger.info(f"Skipping {sig.underlying}: nearest expiry {_min_dte}d out (>21d DTE cap)")
            continue

        _strat = _strat_name(composite_legs)
        _rationale = _strat_rationale(composite_legs, _iv_rank, sig.direction or "long")

        # Net credit received per unit (always positive for valid composite)
        _net_cost_per_unit = _net_credit(composite_legs)
        cost = abs(_net_cost_per_unit) * quantity
        # Add charges for all legs
        for _leg in composite_legs:
            cost += charges_for_entry_only(_leg.estimated_premium, quantity, _leg.action)

        # Primary leg drives the "main" action/premium for notes and risk gate
        _primary = next((l for l in composite_legs if l.role in ("primary", "calendar_long", "condor_short_ce")), composite_legs[0])
        action  = _primary.action
        premium = _primary.estimated_premium

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

        # ── Max concurrent trades gate ────────────────────────────────────────
        try:
            from app.core.risk.gate import get_risk_params as _rp
            _max_trades = _rp().get("max_concurrent_trades", 10)
            open_count_q = select(Trade).where(Trade.status == _TS.OPEN, Trade.mode == TradeMode.PAPER)
            _open_count = len((await db.execute(open_count_q)).scalars().all())
            if _open_count >= _max_trades:
                logger.warning(f"Max concurrent trades ({_max_trades}) reached — skipping {sig.underlying}")
                continue
        except Exception:
            pass

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

        # -- Atomic insert of ALL composite legs (all succeed or none saved) --
        import uuid as _uuid
        group_id = str(_uuid.uuid4())
        try:
            total_deployed = 0.0
            composite_notes_prefix = (
                f"STRATEGY:{_strat}|{_rationale}|"
                f"legs:{len(composite_legs)}|group:{group_id[:8]}"
            )

            # ── Pass 1: price every leg (real LTP cascade + slippage) ─────────
            _priced_legs = []
            for _leg in composite_legs:
                # Three-tier cascade:
                # 1. Kite/Upstox real-time LTP (requires credentials)
                # 2. Chain service LTP (synthetic but strike-accurate)
                # 3. BS estimate from composite builder (last resort)
                _leg_prem = _leg.estimated_premium
                _leg_price_src = "bs"
                _leg_token = None   # Kite instrument token for THIS leg's symbol
                try:
                    _ll, _ls, _lt = await _fetch_option_ltp(
                        _entry_cfg, sig.underlying, _leg.expiry_iso,
                        _leg.strike, _leg.option_type, _leg.symbol,
                    )
                    if _ll and _ll > 0:
                        _leg_prem = _ll
                        _leg_price_src = _ls
                        _leg_token = _lt   # non-None only when Kite priced this exact leg
                except Exception:
                    pass

                if _leg_price_src == "bs":
                    try:
                        from app.core.options.chain_service import ChainService as _CS
                        _chain = _CS().get_chain(sig.underlying)
                        _ltp_col = "ce_ltp" if _leg.option_type == "CE" else "pe_ltp"
                        _crow = _chain.iloc[(_chain["strike"] - _leg.strike).abs().argsort()[:1]].iloc[0]
                        _chain_ltp = float(_crow.get(_ltp_col, 0) or 0)
                        if _chain_ltp >= 1.0:
                            _leg_prem = round(_chain_ltp, 2)
                            _leg_price_src = "chain"
                    except Exception:
                        pass

                # Slippage: BUY fills at ask (pay more), SELL at bid (receive less)
                _slip = max(0.25, _leg_prem * 0.005)
                if _leg.action == "BUY":
                    _leg_prem = round(_leg_prem + _slip, 2)
                else:
                    _leg_prem = round(max(0.05, _leg_prem - _slip), 2)

                logger.debug(f"Leg {_leg.symbol} price={_leg_prem:.2f} source={_leg_price_src} slip={_slip:.2f}")
                _priced_legs.append((_leg, _leg_prem, _leg_price_src, _leg_token))

            # ── Credit/width sanity gate on REAL prices (backtest rule) ───────
            # Credit must be 20-80% of spread width. <20% isn't worth the risk;
            # >80% means near-zero max risk — a stale/synthetic pricing artifact.
            _real_credit = sum(p if l.action == "SELL" else -p for l, p, _, _ in _priced_legs)
            _sells = [l.strike for l, _, _, _ in _priced_legs if l.action == "SELL"]
            _buys  = [l.strike for l, _, _, _ in _priced_legs if l.action == "BUY"]
            _width = abs(_sells[0] - _buys[0]) if _sells and _buys else 2 * _step
            if not (_width * 0.20 <= _real_credit <= _width * 0.80):
                logger.info(
                    f"Skipping {sig.underlying} {_strat}: real credit ₹{_real_credit:.1f} "
                    f"outside 20-80% of width ₹{_width:.0f}"
                )
                await db.rollback()
                continue

            # ── Dynamic lot sizing toward the heat budget (user: use 50% of
            # capital). Each spread targets heat_cap / max_concurrent_spreads
            # of margin, bounded by max_risk_per_trade and remaining heat room.
            try:
                from app.core.risk.gate import get_risk_params as _grp
                import redis as _rl
                from app.config import settings as _stl
                _rp2 = _grp()
                _cap = float(_rp2.get("paper_capital") or 1_000_000)
                _heat_budget = _cap * float(_rp2.get("max_portfolio_heat") or 10) / 100.0
                _max_spreads = max(1, int(_rp2.get("max_concurrent_trades") or 20) // 2)
                _per_trade_target = min(
                    _heat_budget / _max_spreads,
                    _cap * float(_rp2.get("max_risk_per_trade") or 1) / 100.0,
                )
                _rr = _rl.from_url(_stl.redis_url, decode_responses=True)
                _heat_used = float(_rr.get("daily_deployed") or 0)
                _heat_room = max(0.0, _heat_budget - _heat_used)
                _margin_per_lot = max((_width - _real_credit), _width * 0.20) * sig.lot_size
                _lots = int(min(_per_trade_target, _heat_room) // _margin_per_lot)
                _lots = max(1, min(_lots, 20))   # hard cap 20 lots/spread
            except Exception as _se:
                logger.warning(f"Lot sizing failed ({_se}) — defaulting to 1 lot")
                _lots = 1
            if _is_condor_exp:
                _lots = 1   # experiments always run at minimum size

            # ── VIX goldilocks sizing (tested: VIX 13-16 → PF 1.66; outside → <1)
            # Outside the band we still trade (evidence keeps flowing) but at 1 lot.
            try:
                import pandas as _pdv
                _vix_df = _pdv.read_csv("/app/market_data/india_vix.csv")
                _vix_now = float(_vix_df["vix"].iloc[-1])
                if not (13.0 <= _vix_now <= 16.0):
                    _lots = min(_lots, 1)
                    logger.info(f"VIX {_vix_now:.1f} outside 13-16 band → sizing capped at 1 lot")
            except Exception:
                pass

            # ── BullPut probation (real data: PF 0.66-0.91 across all variants;
            # BearCall 1.2-1.9). Keep collecting evidence at minimum size only.
            if "Bull Put" in _strat:
                _lots = min(_lots, 1)

            # ── BANKNIFTY probation (2026-07-04 reality check on 21mo real
            # Upstox prices: BS model said PF 2.98-5.37, reality PF 0.68 —
            # BullPut 0.43, BearCall 1.18 marginal). Evidence at 1 lot only.
            if sig.underlying == "BANKNIFTY":
                _lots = min(_lots, 1)

            quantity = _lots * sig.lot_size
            if _lots > 1:
                logger.info(f"Sizing {sig.underlying} {_strat}: {_lots} lots "
                            f"(target ₹{_per_trade_target:.0f}/trade, margin/lot ₹{_margin_per_lot:.0f})")

            # ── Margin-style capital accounting ───────────────────────────────
            # A defined-risk spread's capital at risk is its MAX LOSS
            # (width − credit), not the premium value of both legs. Counting
            # premium turnover as "deployed" let ONE spread eat the whole heat
            # cap (₹104k blocked for a trade risking ₹2.8k).
            _group_margin = max((_width - _real_credit), _width * 0.20) * quantity
            _margin_per_leg = _group_margin / len(_priced_legs)

            # ── Pass 2: insert all legs with validated real prices ────────────
            _net_cash = 0.0
            for _idx, (_leg, _leg_prem, _leg_price_src, _leg_token) in enumerate(_priced_legs):
                _leg_charges = charges_for_entry_only(_leg_prem, quantity, _leg.action)
                # Cash flow: BUY pays premium, SELL receives it; charges always paid
                _leg_cash = (-(_leg_prem * quantity) if _leg.action == "BUY"
                             else (_leg_prem * quantity)) - _leg_charges
                _leg_cost = _margin_per_leg + _leg_charges   # capital consumed (margin basis)

                if _leg.action == "BUY":
                    _leg_target = round(_leg_prem * 1.50, 2)
                    _leg_stop   = round(_leg_prem * 0.60, 2)
                else:
                    _leg_target = round(_leg_prem * 0.45, 2)
                    _leg_stop   = round(_leg_prem * 2.00, 2)

                _leg_note = (
                    f"{composite_notes_prefix}|"
                    f"leg:{_idx+1}/{len(composite_legs)}({_leg.role})|"
                    f"WHY: {sig.pattern_name} {sig.direction} signal. "
                    f"Conf:{sig.confidence_score:.0%} IV:{round(_iv*100,1)}% IVR:{_iv_rank:.0%} "
                    f"Strike:{_leg.strike}{_leg.option_type} Exp:{_leg.expiry_display}({_leg.expiry_dte}d)"
                )

                _leg_trade = Trade(
                    signal_id    = sig.id, mode = TradeMode.PAPER,
                    symbol       = _leg.symbol, underlying = sig.underlying,
                    option_type  = _leg.option_type, strike = _leg.strike,
                    lot_size     = sig.lot_size, expiry_date = _leg.expiry_iso,
                    expiry_display = _leg.expiry_display,
                    action       = _leg.action, direction = sig.direction,
                    quantity     = quantity,
                    entry_price  = _leg_prem, current_price = _leg_prem,
                    target_price = _leg_target, stop_loss = _leg_stop,
                    charges_entry = _leg_charges, unrealized_pnl = 0.0,
                    status       = TradeStatus.OPEN, entry_time = now,
                    notes        = _leg_note,
                    capital_at_risk_pct = round((_leg_cost / max(portfolio.capital_current, 1)) * 100, 4),
                    # Token for THIS leg's symbol only — assigning the signal's
                    # token to leg 0 priced legs with the WRONG option's LTP
                    # (CE closed at PE's price → phantom P&L)
                    instrument_token = _leg_token,
                    trade_group_id = group_id,
                    leg_role       = _leg.role,
                    entry_price_source = _leg_price_src,
                    margin_blocked = round(_margin_per_leg, 2),
                )
                db.add(_leg_trade)
                total_deployed += _leg_cost          # margin + charges (heat basis)
                _net_cash      += _leg_cash

            # Cash: credit received minus charges flows INTO capital; the margin
            # is blocked separately via capital_deployed (heat), like a broker.
            portfolio.capital_deployed += total_deployed
            portfolio.capital_current  += _net_cash - _group_margin

            logger.info(
                f"Composite [{_strat}]: {sig.underlying} {len(composite_legs)} legs | "
                f"margin ₹{_group_margin:.0f} | net cash ₹{_net_cash:+.0f} | group {group_id[:8]}"
            )
            try:
                from app.core.risk.gate import record_deployed as _record_deployed
                _record_deployed(total_deployed)
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"Composite trade insert failed for {sig.underlying}: {exc}")
            await db.rollback()
            continue

    await db.commit()

    # ── Live order placement — DISABLED (paper-only mode enforced) ────────────
    # SAFETY LOCK: Real Kite order placement is permanently disabled.
    # All trading is paper-only. This block must never be re-enabled without
    # explicit user confirmation and a separate safety review.
    if True:  # PAPER_ONLY_LOCK — do not remove
        logger.debug("Live order placement blocked: PAPER_ONLY_LOCK is active")
    elif not market_open:
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
            from app.core.data.kite_ticker import ticker_service, _token_to_sym
            from app.database import AsyncSessionLocal as _ASL
            ticker_service.subscribe_option_tokens(option_symbols)
            # After subscription, _token_to_sym is populated — store tokens on trades for chart lookup
            sym_to_token = {sym: tok for tok, sym in _token_to_sym.items()}
            async with _ASL() as _db2:
                from app.models.trades import Trade as _T2, TradeStatus as _TS3
                _open = await _db2.execute(
                    select(_T2).where(_T2.status == TradeStatus.OPEN, _T2.instrument_token.is_(None))
                )
                updated = 0
                for _tr in _open.scalars().all():
                    tok = sym_to_token.get(_tr.symbol)
                    if tok:
                        _tr.instrument_token = tok
                        updated += 1
                if updated:
                    await _db2.commit()
                    logger.info(f"Stored instrument tokens for {updated} open trades")
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
                from app.models.kite_config import KiteConfig as _KC
                from app.core.encryption import decrypt as _decrypt
                from app.database import AsyncSessionLocal as _AMTM
                from sqlalchemy import select as _sel_mtm
                from datetime import date as _dt
                async with _AMTM() as _ksess:
                    _kcfg = (await _ksess.execute(_sel_mtm(_KC).limit(1))).scalar_one_or_none()
                _token_valid = (_kcfg and _kcfg.access_token_enc and
                                _kcfg.token_date == _dt.today())
                if _token_valid:
                    _access_token = _decrypt(_kcfg.access_token_enc)
                    kite = KiteConnect(api_key=_kcfg.api_key)
                    kite.set_access_token(_access_token)
                    # Build token→symbol map for trades that have instrument_token stored.
                    # kite.ltp() with symbol name returns {} for weekly options (Kite quirk),
                    # but calling it with the numeric instrument_token always works.
                    token_to_sym: dict[int, str] = {}
                    sym_to_kite: dict[str, str] = {}  # sym -> "NFO:SYM" for non-token trades
                    for t in trades:
                        if t.symbol in missing:
                            if t.instrument_token:
                                token_to_sym[t.instrument_token] = t.symbol
                            else:
                                sym_to_kite[t.symbol] = f"NFO:{t.symbol}"

                    # Call ltp() using numeric tokens (reliable for all option types)
                    if token_to_sym:
                        try:
                            ltp_data = kite.ltp(list(token_to_sym.keys()))
                            for tok_key, data in ltp_data.items():
                                tok_int = int(tok_key) if str(tok_key).isdigit() else None
                                sym = token_to_sym.get(tok_int) if tok_int else None
                                ltp_val = data.get("last_price", 0)
                                if sym and ltp_val > 0:
                                    prices[sym] = ltp_val
                                    logger.info(f"MTM Kite LTP (token): {sym} = ₹{ltp_val}")
                        except Exception as e:
                            logger.warning(f"MTM Kite ltp (token) failed: {e}")

                    # Fallback: trades without stored token — convert to Kite symbol format
                    if sym_to_kite:
                        # Build kite_sym→our_sym map using YYMMDD format conversion
                        kite_sym_map: dict[str, str] = {}
                        for t in trades:
                            if t.symbol in sym_to_kite and t.expiry_date and t.strike and t.option_type:
                                try:
                                    from datetime import date as _d2
                                    import calendar as _cal2
                                    exp2 = _d2.fromisoformat(str(t.expiry_date)[:10])
                                    yy2 = str(exp2.year)[2:]
                                    mon3_2 = exp2.strftime("%b").upper()
                                    last_tue2 = max(
                                        _d2(exp2.year, exp2.month, d)
                                        for d in range(1, _cal2.monthrange(exp2.year, exp2.month)[1]+1)
                                        if _d2(exp2.year, exp2.month, d).weekday() == 1  # Tuesday
                                    )
                                    if exp2 == last_tue2:
                                        ks2 = f"NFO:{t.underlying}{yy2}{mon3_2}{int(t.strike)}{t.option_type}"
                                    else:
                                        ks2 = f"NFO:{t.underlying}{yy2}{exp2.month}{exp2.day:02d}{int(t.strike)}{t.option_type}"
                                    kite_sym_map[ks2] = t.symbol
                                except Exception:
                                    kite_sym_map[f"NFO:{t.symbol}"] = t.symbol
                        kite_syms = list(kite_sym_map.keys())
                        # sym→trade map so we can backfill instrument_token
                        sym_to_trade = {t.symbol: t for t in trades if t.symbol in sym_to_kite}
                        for i in range(0, len(kite_syms), 500):
                            batch = kite_syms[i:i+500]
                            try:
                                ltp_data = kite.ltp(batch)
                                for ks, data in ltp_data.items():
                                    sym = kite_sym_map.get(ks, ks.replace("NFO:", ""))
                                    ltp_val = data.get("last_price", 0)
                                    if ltp_val > 0:
                                        prices[sym] = ltp_val
                                        logger.info(f"MTM Kite LTP (sym): {sym} = ₹{ltp_val}")
                                        # Backfill instrument_token so next run uses faster token path
                                        tok = data.get("instrument_token")
                                        tr = sym_to_trade.get(sym)
                                        if tok and tr and not tr.instrument_token:
                                            tr.instrument_token = int(tok)
                            except Exception as e:
                                logger.warning(f"MTM Kite ltp (sym) batch failed: {e}")
                else:
                    logger.debug("MTM: no valid Kite token today, skipping ltp()")
            except Exception as e:
                logger.warning(f"MTM Kite ltp unavailable: {e}")

        # 3. Upstox LTP for any symbols still missing after Kite
        still_missing = {t for t in trades if t.symbol not in prices}
        if still_missing:
            try:
                from datetime import date as _dt_up
                _up_valid = (_kcfg and _kcfg.upstox_access_token_enc and
                             _kcfg.upstox_token_date == _dt_up.today())
                if _up_valid:
                    from app.core.encryption import decrypt as _dec_up
                    from app.core.data.upstox_ltp import get_ltp_batch as _up_batch
                    _up_token = _dec_up(_kcfg.upstox_access_token_enc)
                    _up_reqs = []
                    for t in still_missing:
                        if t.expiry_date and t.strike and t.option_type:
                            _up_reqs.append({
                                "underlying": t.underlying.upper(),
                                "expiry_iso": str(t.expiry_date)[:10],
                                "strike": float(t.strike),
                                "opt_type": t.option_type,
                                "sym": t.symbol,
                            })
                    if _up_reqs:
                        _up_prices = _up_batch(_up_token, _up_reqs)
                        for sym, ltp_val in _up_prices.items():
                            if ltp_val > 0:
                                prices[sym] = ltp_val
                                logger.info(f"MTM Upstox LTP: {sym} = ₹{ltp_val}")
            except Exception as e:
                logger.debug(f"MTM Upstox ltp unavailable: {e}")

        # Build spot price lookup for BS fallback — read from Redis (cross-process)
        spot_prices: dict[str, float] = {}
        try:
            import redis as _redis_lib
            from app.config import settings
            _r = _redis_lib.from_url(settings.redis_url, decode_responses=True)
            for sym in ["NIFTY", "BANKNIFTY", "SENSEX"]:
                val = _r.get(f"spot:{sym}")
                if val:
                    spot_prices[sym] = float(val)
        except Exception:
            pass
        # Fallback to in-process snapshot (populated in FastAPI process only)
        if not spot_prices:
            try:
                from app.core.data.kite_ticker import ticker_service
                snap = ticker_service.get_snapshot()
                for sym, data in snap.items():
                    if data.get("ltp", 0) > 0:
                        spot_prices[sym] = data["ltp"]
            except Exception:
                pass

        now = datetime.utcnow()
        # Legs whose MTM price came from an estimate (chain/BS) rather than a
        # real broker LTP. If a leg entered at a REAL price, exiting it on an
        # estimated price books phantom P&L (BS can be ₹500+ off deep options).
        _est_repriced: set[int] = set()

        for trade in trades:
            current = prices.get(trade.symbol)

            # Fallback 1: try real NSE chain LTP for the trade's specific expiry
            if not current and trade.strike and trade.option_type and trade.underlying:
                try:
                    from app.core.options.chain_service import ChainService as _CS2
                    _trade_exp = str(trade.expiry_date)[:10] if trade.expiry_date else None
                    _chain2 = _CS2().get_chain(trade.underlying.upper(), expiry_iso=_trade_exp)
                    if not _chain2.empty:
                        _row2 = _chain2[_chain2["strike"] == float(trade.strike)]
                        if not _row2.empty:
                            ltp_col2 = "ce_ltp" if trade.option_type == "CE" else "pe_ltp"
                            _ltp2 = float(_row2[ltp_col2].iloc[0])
                            if _ltp2 > 0.5:
                                current = _ltp2
                                _est_repriced.add(trade.id)
                except Exception:
                    pass

            # Fallback 2: reprice via Black-Scholes using live spot
            if not current and trade.strike and trade.option_type and trade.underlying:
                try:
                    from app.core.options.greeks import _bs_price, RISK_FREE_RATE
                    from app.core.options.chain_service import ChainService
                    from app.core.instruments import BASE_PRICES

                    spot = spot_prices.get(trade.underlying.upper()) or \
                           BASE_PRICES.get(trade.underlying.upper(), 0)
                    if spot > 0:
                        # DTE: days remaining to expiry (floor at 0.5 to avoid div-zero)
                        if trade.expiry_date:
                            from datetime import date as _date
                            exp_d = _date.fromisoformat(str(trade.expiry_date)[:10])
                            dte = max(0.5, (exp_d - _date.today()).days)
                        else:
                            dte = 7.0
                        T = dte / 365.0
                        # Use ATM chain IV for this underlying (more accurate than fixed 18%)
                        iv = 0.18  # default
                        try:
                            chain_df = ChainService().get_chain(trade.underlying.upper())
                            atm_strike = min(chain_df["strike"].unique(), key=lambda s: abs(s - spot))
                            atm_row = chain_df[chain_df["strike"] == atm_strike].iloc[0]
                            ce_iv = float(atm_row.get("ce_iv") or 0)
                            pe_iv = float(atm_row.get("pe_iv") or 0)
                            raw_iv = (ce_iv + pe_iv) / 2 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv)
                            atm_iv = raw_iv if raw_iv >= 0.05 else (raw_iv * 100 if raw_iv > 0 else 0)
                            if 0.05 < atm_iv < 2.0:
                                iv = atm_iv  # already as fraction (e.g. 0.18)
                            elif atm_iv >= 2.0:
                                iv = atm_iv / 100.0  # convert from % to fraction
                        except Exception:
                            pass  # keep default iv=0.18
                        current = round(_bs_price(spot, float(trade.strike), T,
                                                   RISK_FREE_RATE, iv, trade.option_type), 2)
                        current = max(0.05, current)
                        _est_repriced.add(trade.id)
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

            # Composite legs NEVER exit individually — closing one leg of a
            # spread alone breaks the hedge and books phantom P&L. The group
            # loop below applies the managed exit regime to all legs at once.
            if trade.trade_group_id:
                continue

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

            # Stop loss / target hit check.
            # For paper-trading simulation we fill at the order price (stop/target),
            # not at `current` — which can be far past the level if MTM polling
            # was delayed. This matches real broker stop-order fill semantics.
            if trade.action == "BUY":
                if current >= trade.target_price:
                    await _close_trade(trade, trade.target_price, "target_hit", db)
                    continue
                elif current <= trade.stop_loss:
                    await _close_trade(trade, trade.stop_loss, "stop_hit", db)
                    continue
            else:
                if current <= trade.target_price:
                    await _close_trade(trade, trade.target_price, "target_hit", db)
                    continue
                elif current >= trade.stop_loss:
                    await _close_trade(trade, trade.stop_loss, "stop_hit", db)
                    continue

        # ── Group-level exit: close ALL legs atomically when net group P&L hits target/stop ──
        # Individual leg stops are disabled for composite trades — only the group P&L matters.
        # This prevents the "one leg closes, naked exposure remains" problem.
        from collections import defaultdict as _dd
        group_buckets: dict[str, list] = _dd(list)
        for t in trades:
            if t.status == TradeStatus.OPEN and t.trade_group_id:
                group_buckets[t.trade_group_id].append(t)

        for group_id, group_trades in group_buckets.items():
            # User's own broker positions (manual tracking) are NEVER auto-
            # closed — the system monitors them, the user manages them.
            if any((t.leg_role or "") == "manual" for t in group_trades):
                continue

            # Sum net cost (absolute) of the group at entry — this is our risk capital
            net_entry_cost = 0.0
            net_unrealized = 0.0
            for t in group_trades:
                if t.action == "BUY":
                    net_entry_cost -= t.entry_price * t.quantity   # paid
                    net_unrealized += (t.current_price - t.entry_price) * t.quantity
                else:
                    net_entry_cost += t.entry_price * t.quantity   # received
                    net_unrealized += (t.entry_price - t.current_price) * t.quantity

            # net_entry_cost > 0 means we collected net credit at entry
            # net_unrealized > 0 means the group is currently profitable
            # For a credit spread: net_entry_cost = credit received, max_loss = spread - credit

            # Determine max risk (spread width per side - net credit)
            spread_width = 0.0
            sell_legs = [t for t in group_trades if t.action == "SELL"]
            buy_legs  = [t for t in group_trades if t.action == "BUY"]
            if sell_legs and buy_legs:
                spread_width = abs(
                    (sell_legs[0].strike or 0) - (buy_legs[0].strike or 0)
                ) * (sell_legs[0].quantity or 1)

            # ── Managed exit regime (validated in 5y backtest, Jul 2026) ──────
            # TP at 50% of credit, SL at 2× credit, time-exit at half the DTE.
            # vs classic (TP 70%/SL half-max-risk): win rate 54-61% → 67-77%,
            # PF 1.85-2.43 → 2.46-5.37, max drawdown roughly halved.
            take_profit_threshold = net_entry_cost * 0.50 if net_entry_cost > 0 else 0
            stop_loss_threshold = -(net_entry_cost * 2.0) if net_entry_cost > 0 \
                else -max(spread_width - net_entry_cost, 5000.0) * 0.50

            # Time exit: half the original DTE burned without hitting either level
            time_exit_due = False
            try:
                from datetime import date as _gd
                _lead = group_trades[0]
                if _lead.expiry_date and _lead.entry_time:
                    _exp = _gd.fromisoformat(_lead.expiry_date[:10])
                    _ent = _lead.entry_time.date()
                    _dte_total = max((_exp - _ent).days, 1)
                    _days_held = (datetime.utcnow().date() - _ent).days
                    time_exit_due = _days_held >= _dte_total * 0.5
            except Exception:
                pass

            # Price-source consistency: never trigger an exit when a leg that
            # entered at a REAL price is currently marked from an estimate
            # (chain/BS) — the model-vs-market gap books phantom P&L.
            _mixed_pricing = any(
                t.id in _est_repriced and (t.entry_price_source in ("kite", "upstox"))
                for t in group_trades
            )

            # ── CONDORIZE mitigation (adopted 2026-07-04, tested on 144 real
            # trades: net 3x vs 2x-stop baseline). When a plain 2-leg spread
            # falls to −1× its credit, sell an opposite-side spread in the same
            # expiry: the threatened side's fall made the other side's premium
            # rich; new credit finances recovery, combined TP/SL adapt
            # automatically since the legs join the same group. Uses the
            # SEPARATE mitigation budget (₹10L), not the deployment heat cap.
            _roles = {(t.leg_role or "") for t in group_trades}
            _is_plain_spread = (len(group_trades) == 2 and
                                not any(r.startswith(("mitigation", "manual", "zdte")) for r in _roles))
            if (_is_plain_spread and not _mixed_pricing and net_entry_cost > 0
                    and net_unrealized <= -net_entry_cost):
                try:
                    await _condorize_group(group_id, group_trades, db)
                    continue   # thresholds recompute from combined legs next cycle
                except Exception as _ce:
                    logger.warning(f"condorize failed for {group_id[:8]}: {_ce}")

            reason = None
            if net_entry_cost > 0 and net_unrealized >= take_profit_threshold:
                reason = "group_target"
            elif net_unrealized <= stop_loss_threshold:
                reason = "group_stop"
            elif time_exit_due:
                reason = "group_time_exit"

            # 0DTE straddle groups: tighter rules — SL at 40% of credit, and
            # they never survive past the EOD square-off (intraday only).
            if "zdte" in _roles:
                reason = None
                if net_entry_cost > 0 and net_unrealized <= -(net_entry_cost * 0.40):
                    reason = "zdte_stop"
                elif net_entry_cost > 0 and net_unrealized >= net_entry_cost * 0.60:
                    reason = "zdte_target"

            if reason and _mixed_pricing:
                logger.warning(
                    f"Group {group_id[:8]}: exit '{reason}' SUPPRESSED — real-entry legs "
                    f"currently priced by estimate (no live LTP). Waiting for real prices."
                )
                reason = None

            if reason:
                logger.info(
                    f"Group exit [{group_id[:8]}]: {reason} | "
                    f"net_credit=₹{net_entry_cost:.0f} unrealized=₹{net_unrealized:.0f} "
                    f"({len(group_trades)} legs)"
                )
                for t in group_trades:
                    exit_px = t.current_price or t.entry_price
                    await _close_trade(t, exit_px, reason, db)

        await db.commit()
        logger.info(f"MTM update: {len(trades)} open trades repriced")


async def _close_trade(trade, exit_price: float, reason: str, db):
    """Book a trade as closed, compute final charges and net P&L."""
    from app.models.trades import TradeStatus
    from app.models.portfolio import Portfolio
    from app.core.charges import calculate_charges
    from sqlalchemy import select

    # Exit slippage: closing a BUY means selling at bid (receive less);
    # closing a SELL means buying at ask (pay more).
    _slip = max(0.25, exit_price * 0.005)
    if trade.action == "BUY":
        exit_price = round(max(0.05, exit_price - _slip), 2)
    else:
        exit_price = round(exit_price + _slip, 2)

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
        if trade.margin_blocked is not None:
            # Margin-style accounting (spreads): entry took net cash flow and
            # blocked margin. On close: settle the exit leg's cash and release
            # the margin. Lifecycle net effect on capital == net_pnl exactly.
            exit_charges = max(0.0, charges.total - entry_charges_paid)
            if trade.action == "BUY":
                cash = exit_price * trade.quantity - exit_charges   # sell to close
            else:
                cash = -(exit_price * trade.quantity) - exit_charges  # buy to close
            portfolio.capital_current  += cash + trade.margin_blocked
            portfolio.capital_deployed  = max(
                0, portfolio.capital_deployed - trade.margin_blocked - entry_charges_paid)
        else:
            # Legacy premium-value accounting (pre-margin trades)
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
    # Update daily risk gate P&L and release deployed capital.
    # Release must mirror what was RECORDED at entry: margin-style
    # (margin_blocked + entry charges) for margin trades, premium value for
    # legacy rows. Releasing premium against a margin-style entry drifted the
    # Redis heat counter by lakhs/day (anomaly journal, 2026-07-07).
    try:
        from app.core.risk.gate import record_pnl, record_deployed as _release_deployed
        record_pnl(net_pnl)
        if trade.margin_blocked is not None:
            _release_deployed(-(trade.margin_blocked + entry_charges_paid))
        else:
            _release_deployed(-(trade_cost + entry_charges_paid))   # legacy premium-value rows
    except Exception:
        pass

    # Auto-close hedge leg when main trade closes (they share the same symbol prefix)
    # Hedge is identified by notes containing "spread_leg:hedge|main_sym:<symbol>"
    if trade.notes and "spread_leg:main" in trade.notes:
        try:
            from app.models.trades import Trade as _Trade, TradeStatus as _TStatus
            from sqlalchemy import select as _sel
            hedge_marker = f"main_sym:{trade.symbol}"
            hedge_q = await db.execute(
                _sel(_Trade).where(
                    _Trade.status == _TStatus.OPEN,
                    _Trade.underlying == trade.underlying,
                    _Trade.notes.like(f"%{hedge_marker}%"),
                )
            )
            hedge_trade = hedge_q.scalar_one_or_none()
            if hedge_trade:
                await _close_trade(hedge_trade, exit_price, f"hedge_{reason}", db)
        except Exception as _he:
            logger.debug(f"Hedge auto-close skipped: {_he}")


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

        # Get spot prices for settlement — try Kite first, then Redis ticker cache
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
            logger.warning(f"Expiry settlement: could not fetch Kite prices: {e}")

        # Fallback: Redis spot cache written by ticker service
        if not spot_prices:
            try:
                import redis as _redis_lib
                from app.config import settings as _s
                _r = _redis_lib.from_url(_s.redis_url, decode_responses=True)
                for t in trades:
                    u = t.underlying.upper()
                    val = _r.get(f"spot:{u}")
                    if val:
                        spot_prices[u] = float(val)
            except Exception:
                pass

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
            # Composite spreads are POSITIONAL by construction: defined-risk,
            # margin-blocked, 7-26 DTE, with their own managed exits (TP/SL/
            # half-DTE). Squaring them off same-day guaranteed a friction loss
            # (~₹400-900/group) and made live holds 3h vs backtest 5-12 days.
            # EXCEPTION: 0DTE straddles are intraday-only by design — square
            # them off here. Manual (user's own) positions are never touched.
            if trade.trade_group_id:
                if (trade.leg_role or "") == "zdte":
                    exit_px = trade.current_price or trade.entry_price
                    await _close_trade(trade, exit_px, "zdte_eod", db)
                    closed += 1
                continue

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
        _stamp_task_run("workers.eod_close_intraday")
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
    # Return only JSON-native types — numpy int64 values crash Celery's Redis result store
    return {
        "signals_found": int(len(result.get("signals", []))),
        "symbols_scanned": int(len(symbols)),
        "timeframes": list(timeframes),
    }


# ── Celery tasks ──────────────────────────────────────────────────────────────

@celery_app.task(name="workers.scan_priority_instruments", bind=True, max_retries=2)
def scan_priority_instruments(self, timeframes: list[str] | None = None):
    from app.core.instruments import priority_scan_list
    symbols = priority_scan_list()
    tfs = timeframes or ["15m", "1h"]
    logger.info(f"Priority scan: {len(symbols)} symbols × {tfs}")
    try:
        result = _run_async(_do_scan(symbols, tfs))
        _stamp_task_run("workers.scan_priority_instruments")
        return result
    except Exception as exc:
        logger.error(f"Priority scan failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="workers.scan_all_instruments", bind=True, max_retries=2)
def scan_all_instruments(self, timeframes: list[str] | None = None, task_label: str | None = None):
    from app.core.instruments import priority_scan_list
    symbols = priority_scan_list()   # respects TESTING_FOCUS when set
    tfs = timeframes or ["1h", "4h", "daily"]
    logger.info(f"Full scan: {len(symbols)} symbols × {tfs}")
    try:
        result = _run_async(_do_scan(symbols, tfs))
        # Stamp both the generic key and the caller-specific label (for beat schedule tracking)
        _stamp_task_run("workers.scan_all_instruments")
        if task_label:
            _stamp_task_run(task_label)
        return result
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
        _stamp_task_run("workers.mtm_update")
    except Exception as exc:
        logger.error(f"MTM update failed: {exc}")


@celery_app.task(name="workers.expiry_settlement")
def expiry_settlement():
    """Settle all expired paper trades at intrinsic value."""
    logger.info("Expiry settlement starting")
    try:
        _run_async(_do_expiry_settlement())
        _stamp_task_run("workers.expiry_settlement")
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
        _stamp_task_run("workers.sync_market_data")
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
        _stamp_task_run("workers.cleanup_stale_signals")
    except Exception as exc:
        logger.error(f"Signal cleanup failed: {exc}")


async def _sync_deployed_from_db() -> None:
    """Re-seed DAILY_DEPLOYED_KEY from actual open trades in DB (corrects Redis drift)."""
    try:
        from sqlalchemy import select, func
        from app.database import AsyncSessionLocal
        from app.models.trades import Trade, TradeStatus, TradeMode
        from app.core.risk.gate import record_deployed

        async with AsyncSessionLocal() as db:
            # Margin-style heat, same formula as main.py startup sync and
            # health-scan resync. The old premium-value formula here
            # (entry_price × quantity) re-seeded ₹3.5L against a true ₹0.45L
            # every day at 09:15 — the anomaly journal's first real catch.
            rows = (await db.execute(
                select(Trade).where(
                    Trade.status == TradeStatus.OPEN,
                    Trade.mode   == TradeMode.PAPER,
                )
            )).scalars().all()
            deployed = sum(
                (t.margin_blocked + (t.charges_entry or 0.0))
                if t.margin_blocked is not None
                else (t.entry_price or 0) * (t.quantity or 1)
                for t in rows
            )
        if deployed > 0:
            record_deployed(float(deployed))
            logger.info(f"Portfolio heat re-seeded from DB (margin-style): ₹{deployed:,.0f}")
    except Exception as exc:
        logger.warning(f"Could not re-seed portfolio heat from DB: {exc}")


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
        # Re-seed deployed capital from actual open trades (handles Redis drift)
        _run_async(_sync_deployed_from_db())
        logger.info("Daily P&L counter reset for new trading day")
        _stamp_task_run("workers.reset_daily_pnl")
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
        _stamp_task_run("workers.reset_weekly_pnl")
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
        _stamp_task_run("workers.confirm_order_fills")
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
        _stamp_task_run("workers.run_nightly_backtests")
    except Exception as exc:
        logger.error(f"Nightly backtests failed: {exc}")


@celery_app.task(name="workers.generate_briefing")
def generate_briefing():
    """
    Pre-market AI briefing at 08:45 IST.
    Gathers PCR, FII, India VIX, IV rank, and recommended patterns, then calls
    Claude Sonnet 4.6 to generate a structured market briefing stored in Redis
    so the Dashboard pre-market endpoint can serve it instantly.
    """
    async def _run():
        import json
        from datetime import date

        # Collect market context
        try:
            from app.core.options.chain_service import ChainService
            from app.core.options.iv_rank import IVRankService
            from app.core.options.regime import RegimeDetector

            chain_svc = ChainService()
            context_parts: list[str] = []

            for sym in ["NIFTY", "BANKNIFTY"]:
                iv_hist = chain_svc.get_iv_history(sym)
                chain_df = chain_svc.get_chain(sym)
                # current IV proxy from chain ATM
                atm_iv = float(chain_df["ce_iv"].dropna().mean()) if "ce_iv" in chain_df.columns else 18.0
                iv_rank = IVRankService.iv_rank(atm_iv, iv_hist)
                bias = IVRankService.strategy_bias(iv_rank)

                # PCR from cache
                pcr_val = "N/A"
                try:
                    from app.core.backtest.market_data import load_pcr_cache
                    pcr_df = load_pcr_cache(sym)
                    if pcr_df is not None and len(pcr_df) > 0:
                        pcr_val = round(float(pcr_df["pcr"].iloc[-1]), 3)
                except Exception:
                    pass

                context_parts.append(
                    f"{sym}: IV rank={iv_rank:.1%}, strategy_bias={bias}, PCR={pcr_val}"
                )

            # VIX
            try:
                from app.core.backtest.market_data import fetch_india_vix
                vix = fetch_india_vix()
                context_parts.append(f"India VIX: {vix:.2f}")
            except Exception:
                pass

            context = "\n".join(context_parts)
            today = date.today().strftime("%A %d %b %Y")
            prompt = (
                f"Today is {today} — NSE F&O pre-market briefing.\n\n"
                f"Market data:\n{context}\n\n"
                "Write a concise pre-market briefing with these sections:\n"
                "## Market Mood\n"
                "## Key Levels (NIFTY & BANKNIFTY)\n"
                "## Pattern Opportunities (3 bullets max)\n"
                "## Risk Flags\n\n"
                "Keep it under 250 words. Be specific — mention actual IV levels and PCR readings."
            )

            # Call Anthropic API
            from sqlalchemy import select
            from app.database import AsyncSessionLocal
            from app.models.kite_config import KiteConfig
            async with AsyncSessionLocal() as db:
                cfg = (await db.execute(select(KiteConfig).limit(1))).scalar_one_or_none()
                # Column is anthropic_api_key_enc (encrypted) — the old attribute
                # name raised AttributeError and the briefing silently never ran
                api_key = None
                if cfg and cfg.anthropic_api_key_enc:
                    from app.core.encryption import decrypt as _dec
                    api_key = _dec(cfg.anthropic_api_key_enc)

            if not api_key:
                logger.warning("generate_briefing: Anthropic API key not set — skipping")
                return

            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            briefing_text = msg.content[0].text if msg.content else ""

            # Store in Redis with 6h TTL
            import redis as redis_lib
            from app.config import settings
            r = redis_lib.from_url(settings.redis_url, decode_responses=True)
            r.setex(
                "premarket_briefing",
                21600,
                json.dumps({"date": str(date.today()), "briefing": briefing_text}),
            )
            logger.info("generate_briefing: AI pre-market briefing stored in Redis")

        except Exception as exc:
            logger.error(f"generate_briefing: {exc}")

    try:
        _run_async(_run())
        _stamp_task_run("workers.generate_briefing")
    except Exception as exc:
        logger.error(f"generate_briefing task failed: {exc}")


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
        _stamp_task_run("workers.run_nightly_discovery")
    except Exception as exc:
        logger.error(f"Nightly discovery failed: {exc}")


# ── Lot-size verifier ─────────────────────────────────────────────────────────

@celery_app.task(name="workers.verify_lot_sizes")
def verify_lot_sizes():
    """
    Cross-check configured lot sizes in instruments.py against Kite NFO instrument master.
    Uses the Redis-cached token map (populated at startup) — avoids hitting kite.instruments()
    rate limit by reading from cache first. Logs WARNING for any mismatch.
    Runs daily at 08:30 IST via beat schedule.
    See docs/NSE_MARKET_CONVENTIONS.md for full lot size history.
    """
    import redis as _redis_lib
    import json as _json
    from app.config import settings as _s
    from app.core.instruments import LOT_SIZES, TESTING_FOCUS

    logger.info("verify-lot-sizes: starting lot size cross-check")
    mismatches: list[str] = []

    try:
        from kiteconnect import KiteConnect
        from app.models.kite_config import KiteConfig as _KC
        from app.core.encryption import decrypt as _dec
        from app.database import AsyncSessionLocal as _DB
        from sqlalchemy import select as _sel
        from datetime import date as _dt

        async def _run():
            async with _DB() as db:
                cfg = (await db.execute(_sel(_KC).limit(1))).scalar_one_or_none()
            if not cfg or not cfg.access_token_enc or cfg.token_date != _dt.today():
                logger.info("verify-lot-sizes: no valid Kite token today, skipping live check")
                return

            kite = KiteConnect(api_key=cfg.api_key)
            kite.set_access_token(_dec(cfg.access_token_enc))

            # Try Redis cache first to avoid rate limit
            _r = _redis_lib.from_url(_s.redis_url, decode_responses=True)
            _CACHE_KEY = "kite:nfo_lot_sizes"
            cached = _r.get(_CACHE_KEY)
            kite_lot_sizes: dict[str, int] = {}

            if cached:
                kite_lot_sizes = _json.loads(cached)
                logger.info(f"verify-lot-sizes: loaded {len(kite_lot_sizes)} lot sizes from Redis cache")
            else:
                # Fetch fresh — rate limited to ~1/day, cache result
                try:
                    instruments = kite.instruments("NFO")
                    for inst in instruments:
                        sym = inst.get("name") or inst.get("tradingsymbol", "")
                        # Index instruments have `name` = "NIFTY 50", "NIFTY BANK" etc.
                        # We map them to our internal symbols
                        _alias = {
                            "NIFTY 50": "NIFTY", "NIFTY": "NIFTY",
                            "NIFTY BANK": "BANKNIFTY", "BANKNIFTY": "BANKNIFTY",
                            "NIFTY FIN SERVICE": "FINNIFTY", "FINNIFTY": "FINNIFTY",
                            "NIFTY MID SELECT": "MIDCPNIFTY", "MIDCPNIFTY": "MIDCPNIFTY",
                        }
                        internal = _alias.get(sym) or _alias.get(inst.get("name", ""))
                        if internal and inst.get("lot_size"):
                            kite_lot_sizes[internal] = int(inst["lot_size"])
                    _r.setex(_CACHE_KEY, 23 * 3600, _json.dumps(kite_lot_sizes))
                    logger.info(f"verify-lot-sizes: fetched {len(kite_lot_sizes)} lot sizes from Kite, cached 23h")
                except Exception as e:
                    logger.warning(f"verify-lot-sizes: kite.instruments() failed: {e}")
                    return

            for sym in TESTING_FOCUS:
                our_size = LOT_SIZES.get(sym)
                kite_size = kite_lot_sizes.get(sym)
                if kite_size and our_size and kite_size != our_size:
                    msg = (f"LOT SIZE MISMATCH — {sym}: instruments.py={our_size} "
                           f"vs Kite={kite_size}. Update instruments.py and docs/NSE_MARKET_CONVENTIONS.md")
                    logger.warning(msg)
                    mismatches.append(msg)
                elif kite_size and our_size:
                    logger.info(f"verify-lot-sizes: {sym} lot_size={our_size} ✓ matches Kite")

        _run_async(_run())
        _stamp_task_run("workers.verify_lot_sizes")
        if mismatches:
            return {"status": "mismatch", "mismatches": mismatches}
        return {"status": "ok"}
    except Exception as exc:
        logger.error(f"verify-lot-sizes failed: {exc}")


# ── Health-check scanner ───────────────────────────────────────────────────────

@celery_app.task(name="workers.health_scan")
def health_scan():
    """
    Periodic health scanner — runs every 5 minutes.

    Checks and auto-heals:
      1. Redis deployed-capital drift  — resyncs from DB open trades
      2. Stale ACTIVE signals (> 2h)   — expires them so fresh scan replaces
      3. Kill-switch / halt auto-clear  — resumes if daily-loss gate cleared itself
      4. Negative deployed capital      — resets to 0 (float imprecision artifact)
      5. Signal queue empty (no ACTIVE) — logs warning to prompt manual scan

    Returns a health dict with 'issues' list (empty = all clear).
    """
    import asyncio as _asyncio
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    issues: list[str] = []
    fixes:  list[str] = []

    try:
        import redis as _redis_lib
        from app.config import settings as _st
        from app.core.risk.gate import (
            DAILY_DEPLOYED_KEY, DAILY_PNL_KEY, KILL_SWITCH_KEY,
            get_risk_params, is_halted,
        )

        r = _redis_lib.from_url(_st.redis_url, decode_responses=True)

        # ── 1. Deployed capital drift check ──────────────────────────────────
        async def _resync_heat():
            from app.database import AsyncSessionLocal as _DB
            from sqlalchemy import select as _s
            from app.models.trades import Trade, TradeStatus, TradeMode
            async with _DB() as db:
                rows = (await db.execute(
                    _s(Trade).where(
                        Trade.status == TradeStatus.OPEN,
                        Trade.mode  == TradeMode.PAPER,
                    )
                )).scalars().all()
                # Margin-style heat; legacy rows fall back to premium value.
                # (Old code also multiplied lot_size × quantity — double count,
                # since quantity already includes lot_size.)
                return sum(
                    (t.margin_blocked + (t.charges_entry or 0.0))
                    if t.margin_blocked is not None
                    else (t.entry_price or 0) * (t.quantity or 1)
                    for t in rows
                )

        db_deployed = _run_async(_resync_heat())
        redis_deployed = float(r.get(DAILY_DEPLOYED_KEY) or 0)
        drift = abs(redis_deployed - db_deployed)

        if redis_deployed < 0:
            r.set(DAILY_DEPLOYED_KEY, str(max(db_deployed, 0)))
            fixes.append(f"deployed_negative_reset: Redis={redis_deployed:.0f} → DB={db_deployed:.0f}")
        elif drift > 5000:
            r.set(DAILY_DEPLOYED_KEY, str(db_deployed))
            fixes.append(f"deployed_drift_corrected: Redis={redis_deployed:.0f} → DB={db_deployed:.0f} (drift ₹{drift:.0f})")

        # ── 2. Stale signal expiry (> 2h old ACTIVE signals) ─────────────────
        async def _expire_stale():
            from app.database import AsyncSessionLocal as _DB
            from sqlalchemy import update as _u, text as _text
            from app.models.signals import Signal, SignalStatus
            # Use SQL NOW() - INTERVAL to avoid asyncpg naive-datetime issues
            stale_expr = Signal.created_at < _text("NOW() - INTERVAL '2 hours'")
            async with _DB() as db:
                res = await db.execute(
                    _u(Signal)
                    .where(Signal.status == SignalStatus.ACTIVE, stale_expr)
                    .values(status=SignalStatus.EXPIRED)
                    .returning(Signal.id, Signal.underlying, Signal.pattern_name)
                )
                expired = res.fetchall()
                await db.commit()
                return expired

        expired = _run_async(_expire_stale())
        if expired:
            syms = ", ".join(f"{row[1]}/{row[2]}" for row in expired[:5])
            fixes.append(f"stale_signals_expired: {len(expired)} ({syms}{'…' if len(expired)>5 else ''})")

        # ── 3. Kill-switch / halt check ───────────────────────────────────────
        if is_halted():
            reason = r.get("TRADING_HALT_REASON") or "unknown"
            halt_ts = r.get("TRADING_HALT_TS")
            halt_age_min = (_dt.now(_tz.utc).timestamp() - float(halt_ts)) / 60 if halt_ts else 0
            rp = get_risk_params()
            daily_pnl = float(r.get(DAILY_PNL_KEY) or 0)
            capital = rp.get("paper_capital", 500000)
            daily_loss_pct = (daily_pnl / capital) * 100
            # Auto-resume if >30 min old AND loss has recovered to within 80% of limit
            if halt_age_min > 30 and daily_loss_pct > -(rp.get("max_daily_loss_pct", 2) * 0.8):
                r.delete(KILL_SWITCH_KEY)
                r.delete("TRADING_HALT_REASON")
                fixes.append(f"halt_auto_cleared: halted {halt_age_min:.0f}m for '{reason}', daily_pnl={daily_loss_pct:.1f}%")
            else:
                issues.append(f"trading_halted: reason='{reason}' age={halt_age_min:.0f}m daily_pnl={daily_loss_pct:.1f}%")

        # ── 4. Active signal count ────────────────────────────────────────────
        async def _count_active():
            from app.database import AsyncSessionLocal as _DB
            from sqlalchemy import select as _s, func as _f
            from app.models.signals import Signal, SignalStatus
            async with _DB() as db:
                res = await db.execute(
                    _s(_f.count(Signal.id)).where(Signal.status == SignalStatus.ACTIVE)
                )
                return res.scalar() or 0

        active_signals = _run_async(_count_active())

        # Only meaningful during market hours — overnight the scanner is
        # deliberately idle and an empty queue is normal (journal noise otherwise)
        _hs_now_ist = _dt.now(_tz.utc) + _td(hours=5, minutes=30)
        _hs_mkt = (_hs_now_ist.weekday() < 5 and
                   (9, 15) <= (_hs_now_ist.hour, _hs_now_ist.minute) <= (15, 30))
        if active_signals == 0 and _hs_mkt:
            issues.append("no_active_signals: scanner may be stalled — trigger scan-priority-15m")

        # ── 4b. Real-tick heartbeat (market hours only) ───────────────────────
        # If the Kite WebSocket dies, spot: keys silently degrade to synthetic
        # random-walk values — wrong strikes for new entries. Flag staleness.
        try:
            _now_ist = _dt.now(_tz.utc) + _td(hours=5, minutes=30)
            _mkt_open = (_now_ist.weekday() < 5 and
                         (9, 20) <= (_now_ist.hour, _now_ist.minute) <= (15, 30))
            if _mkt_open:
                _hb = r.get("ticker:last_real_tick")
                import time as _time
                if not _hb or (_time.time() - float(_hb)) > 180:
                    issues.append(
                        "ticker_stale: no REAL Kite tick in >3 min during market hours — "
                        "spot: keys may be synthetic; restart backend to reconnect WebSocket")
        except Exception:
            pass

        # ── 5. Trade integrity verification ──────────────────────────────────
        # Automated version of the manual checks that caught the phantom-P&L
        # bugs: structural P&L bounds, charge recomputation, price-swap
        # detection, group atomicity. Violations are surfaced, never silently
        # fixed — a wrong number must be investigated, not papered over.
        integrity_violations = _run_async(_verify_trade_integrity())
        for v in integrity_violations:
            issues.append(f"integrity: {v}")
        try:
            import json as _ij
            r.setex("trade_integrity:last", 3600, _ij.dumps({
                "violations": integrity_violations,
                "checked_at_ist": (_dt.now(_tz.utc) + _td(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M IST"),
            }))
        except Exception:
            pass

        # ── 5b. Signal churn spike — >20 signals/pattern/day is a defect
        # (this is how the 69/day max_pain flood should have been caught)
        try:
            churn = _run_async(_signal_churn_today())
            for pat, n in churn.items():
                if n > 20:
                    issues.append(f"signal_churn: {pat} created {n} signals today (>20 = dedup/data defect)")
        except Exception:
            pass

        # ── 5c. Spot sanity vs last EOD digest close — catches the synthetic-
        # drift class of bug (spot keys wandering far from last known real close)
        try:
            import json as _sj
            from pathlib import Path as _P
            snaps = sorted(_P("/app/market_data/daily_snapshots").glob("*.json"))
            if snaps:
                last_digest = _sj.loads(snaps[-1].read_text())
                for ul in ("nifty", "banknifty"):
                    ref = (last_digest.get(ul) or {}).get("close")
                    cur = r.get(f"spot:{ul.upper()}")
                    if ref and cur and abs(float(cur) / ref - 1) > 0.05:
                        issues.append(
                            f"spot_sanity: spot:{ul.upper()}={float(cur):.0f} is "
                            f">{5}% from last real close {ref:.0f} — possible synthetic/stale price")
        except Exception:
            pass

        # ── 5d. Journal everything permanently (Redis state expires; this doesn't)
        try:
            entries = []
            for f in fixes:
                entries.append({"source": "health_scan", "kind": f.split(":", 1)[0],
                                "severity": "warn", "detail": {"msg": f}, "auto_fixed": True})
            for i in issues:
                kind = i.split(":", 1)[0]
                src = "integrity" if kind == "integrity" else (
                    "signal_churn" if kind == "signal_churn" else (
                        "data_check" if kind in ("spot_sanity", "ticker_stale") else "health_scan"))
                sev = "critical" if kind in ("integrity", "ticker_stale", "trading_halted", "spot_sanity") else "warn"
                entries.append({"source": src, "kind": kind, "severity": sev,
                                "detail": {"msg": i}, "auto_fixed": False})
            if entries:
                _run_async(_journal_anomalies(entries))
        except Exception as _je:
            logger.error(f"anomaly journal write failed: {_je}")

        # ── 6. Summary ────────────────────────────────────────────────────────
        status = "ok" if not issues else "degraded"
        result = {
            "status":         status,
            "issues":         issues,
            "fixes_applied":  fixes,
            "active_signals": active_signals,
            "redis_deployed": redis_deployed,
            "db_deployed":    db_deployed,
            "ts_ist":         (_dt.now(_tz.utc) + _td(hours=5, minutes=30)).strftime("%H:%M IST"),
        }
        if issues:
            logger.warning(f"health-scan DEGRADED: {issues}")
        if fixes:
            logger.info(f"health-scan fixes applied: {fixes}")
        if status == "ok" and not fixes:
            logger.info(f"health-scan OK — deployed=₹{db_deployed:.0f}, active_signals={active_signals}")

        _stamp_task_run("workers.health_scan")
        return result

    except Exception as exc:
        logger.error(f"health-scan failed: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}


async def _signal_churn_today() -> dict:
    """Signals created today per pattern — churn detector input."""
    from sqlalchemy import text as _text
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(_text(
            "SELECT pattern_name, count(*) FROM signals "
            "WHERE created_at >= CURRENT_DATE GROUP BY 1"))).all()
    return {p: int(n) for p, n in rows}


async def _journal_anomalies(entries: list[dict]) -> int:
    """
    Persist anomalies to the permanent journal (anomalies table).
    Dedup: skip if an unresolved row with the same source+kind exists in the
    last 60 minutes — health-scan runs every 5 min and must not spam the
    journal with the same ongoing condition.
    """
    from sqlalchemy import text as _text
    from app.database import AsyncSessionLocal
    from app.models.anomaly import Anomaly
    written = 0
    async with AsyncSessionLocal() as db:
        for e in entries:
            # Slow-changing daily conditions journal once per day, not hourly
            window = ("CURRENT_DATE" if e["source"] in ("signal_churn",)
                      else "NOW() - INTERVAL '60 minutes'")
            dup = (await db.execute(_text(
                "SELECT 1 FROM anomalies WHERE source=:s AND kind=:k "
                f"AND resolved=false AND ts > {window} LIMIT 1"
            ), {"s": e["source"], "k": e["kind"]})).first()
            if dup:
                continue
            db.add(Anomaly(source=e["source"], kind=e["kind"],
                           severity=e.get("severity", "warn"),
                           detail=e.get("detail", {}),
                           auto_fixed=e.get("auto_fixed", False)))
            written += 1
        await db.commit()
    return written


async def _verify_trade_integrity() -> list[str]:
    """
    Verify every recent trade's numbers are arithmetically possible.
    Returns a list of human-readable violations (empty = all good).

    Checks (each one has caught a real bug before):
      1. Group P&L bounds — a spread can never make more than its credit
         or lose more than width−credit (catches wrong-instrument pricing)
      2. Charges recomputation — stored charges must match calculate_charges
         re-run on the same inputs (catches rate drift)
      3. pnl == gross − charges consistency per closed leg
      4. CE/PE price-swap detection — same-strike same-expiry CE and PE
         having crossed prices vs entry (catches token mix-ups)
      5. Group atomicity — all legs of a group must share OPEN/closed state
      6. Price sanity — entry/exit in (0, 20% of strike]
    """
    from sqlalchemy import select as _sel
    from app.database import AsyncSessionLocal
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.core.charges import calculate_charges
    from collections import defaultdict

    violations: list[str] = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            _sel(Trade).where(
                Trade.mode == TradeMode.PAPER,
                Trade.status.in_([TradeStatus.OPEN, TradeStatus.CLOSED]),
            ).order_by(Trade.entry_time.desc()).limit(200)
        )).scalars().all()

    groups: dict[str, list] = defaultdict(list)
    for t in rows:
        if t.trade_group_id:
            groups[t.trade_group_id].append(t)

    for gid, legs in groups.items():
        g = gid[:8]

        # 5. Atomicity: no group may be half-open
        states = {str(t.status.value if hasattr(t.status, "value") else t.status) for t in legs}
        if len(states) > 1:
            violations.append(f"group {g}: legs in mixed states {states} — atomicity broken")

        # 1. Structural P&L bounds (closed groups)
        closed = [t for t in legs if t.exit_price is not None and t.pnl is not None]
        if len(closed) == len(legs) and len(legs) >= 2:
            qty = legs[0].quantity or 1
            sells = [t for t in legs if t.action == "SELL"]
            buys  = [t for t in legs if t.action == "BUY"]
            if sells and buys and sells[0].strike and buys[0].strike:
                width  = abs(sells[0].strike - buys[0].strike)
                credit = sum(t.entry_price for t in sells) - sum(t.entry_price for t in buys)
                group_pnl = sum(t.pnl for t in legs)
                max_profit = credit * qty * 1.05 + 50          # 5% + ₹50 tolerance
                max_loss   = (width - credit) * qty * 1.05 + 50
                if group_pnl > max_profit:
                    violations.append(
                        f"group {g}: pnl ₹{group_pnl:.0f} EXCEEDS max profit ₹{credit*qty:.0f} — pricing corrupt")
                if group_pnl < -max_loss:
                    violations.append(
                        f"group {g}: loss ₹{group_pnl:.0f} EXCEEDS max loss ₹{-(width-credit)*qty:.0f} — pricing corrupt")

    for t in rows:
        sym = t.symbol
        # 6. Price sanity
        for label, px in (("entry", t.entry_price), ("exit", t.exit_price)):
            if px is not None and t.strike and not (0 < px <= t.strike * 0.20):
                violations.append(f"{sym} #{t.id}: {label} price ₹{px} implausible for strike {t.strike:.0f}")

        # 2+3. Charges + P&L recomputation on closed legs
        if t.status == TradeStatus.CLOSED and t.exit_price is not None and t.pnl is not None:
            c = calculate_charges(t.entry_price, t.exit_price, t.quantity or 1, t.action or "BUY")
            if t.charges_total is not None and abs(c.total - t.charges_total) > max(1.0, c.total * 0.02):
                violations.append(
                    f"{sym} #{t.id}: stored charges ₹{t.charges_total:.2f} ≠ recomputed ₹{c.total:.2f}")
            gross = ((t.exit_price - t.entry_price) if t.action == "BUY"
                     else (t.entry_price - t.exit_price)) * (t.quantity or 1)
            expect_pnl = gross - c.total
            if abs((t.pnl or 0) - expect_pnl) > max(5.0, abs(expect_pnl) * 0.02):
                violations.append(
                    f"{sym} #{t.id}: pnl ₹{t.pnl:.2f} ≠ gross−charges ₹{expect_pnl:.2f}")

    # 4. CE/PE swap heuristic: same strike+expiry, both legs moved >15% in
    # opposite directions AND each leg's current price is within 3% of the
    # OTHER leg's entry — the signature of a token mix-up.
    by_key: dict[tuple, list] = defaultdict(list)
    for t in rows:
        if t.status == TradeStatus.OPEN and t.strike and t.option_type and t.current_price:
            by_key[(t.underlying, t.strike, t.expiry_date)].append(t)
    for key, pair in by_key.items():
        ces = [t for t in pair if t.option_type == "CE"]
        pes = [t for t in pair if t.option_type == "PE"]
        if ces and pes:
            ce, pe = ces[0], pes[0]
            if (abs(ce.current_price - pe.entry_price) < pe.entry_price * 0.03 and
                    abs(pe.current_price - ce.entry_price) < ce.entry_price * 0.03 and
                    abs(ce.current_price - ce.entry_price) > ce.entry_price * 0.15):
                violations.append(
                    f"{ce.symbol}/{pe.symbol}: CE and PE prices appear SWAPPED (token mix-up?)")

    if violations:
        logger.warning(f"TRADE INTEGRITY violations: {violations}")
    return violations


# ── Persistent market watch — snapshots every 15 min on trading days ─────────

async def _do_market_watch_snapshot():
    """
    Record a market snapshot to Redis so learning survives across sessions:
    spot levels, per-group unrealized P&L, closes so far, integrity status.
    List key market_watch:YYYY-MM-DD (7-day TTL), one JSON entry per snapshot.
    """
    import json as _json
    import redis as _r
    from datetime import datetime as _dt2, timedelta as _td2, timezone as _tz2
    from sqlalchemy import select as _sel, text as _text
    from app.config import settings as _st
    from app.database import AsyncSessionLocal
    from app.models.trades import Trade, TradeStatus, TradeMode

    r = _r.from_url(_st.redis_url, decode_responses=True)
    now_ist = _dt2.now(_tz2.utc) + _td2(hours=5, minutes=30)
    if now_ist.weekday() >= 5 or not ((9, 15) <= (now_ist.hour, now_ist.minute) <= (15, 35)):
        return  # only during market hours on weekdays

    snap = {"ts_ist": now_ist.strftime("%H:%M"),
            "nifty": r.get("spot:NIFTY"), "banknifty": r.get("spot:BANKNIFTY"),
            "real_ticks": bool(r.get("ticker:last_real_tick"))}

    async with AsyncSessionLocal() as db:
        open_rows = (await db.execute(
            _sel(Trade).where(Trade.status == TradeStatus.OPEN, Trade.mode == TradeMode.PAPER)
        )).scalars().all()
        groups: dict = {}
        for t in open_rows:
            g = groups.setdefault((t.trade_group_id or "?")[:8], {"pnl": 0.0, "ul": t.underlying})
            g["pnl"] += float(t.unrealized_pnl or 0)
        snap["open_groups"] = {k: round(v["pnl"]) for k, v in groups.items()}

        closed = (await db.execute(_text(
            "SELECT COALESCE(ROUND(SUM(pnl)),0), count(DISTINCT trade_group_id), "
            "COALESCE(string_agg(DISTINCT exit_reason, ','),'') "
            "FROM trades WHERE status='CLOSED' AND exit_time >= CURRENT_DATE"))).first()
        snap["closed_today"] = {"net": float(closed[0]), "groups": int(closed[1]), "reasons": closed[2]}

    try:
        integ = r.get("trade_integrity:last")
        snap["integrity_violations"] = len(_json.loads(integ)["violations"]) if integ else None
    except Exception:
        snap["integrity_violations"] = None

    key = f"market_watch:{now_ist.strftime('%Y-%m-%d')}"
    r.rpush(key, _json.dumps(snap))
    r.expire(key, 86400 * 7)
    logger.info(f"market-watch snapshot: N={snap['nifty']} B={snap['banknifty']} "
                f"open={len(snap['open_groups'])} closed_net={snap['closed_today']['net']}")


@celery_app.task(name="workers.market_watch_snapshot")
def market_watch_snapshot():
    """Persist a market/book snapshot every 15 min on trading days."""
    try:
        _run_async(_do_market_watch_snapshot())
        _stamp_task_run("workers.market_watch_snapshot")
    except Exception as exc:
        logger.error(f"market-watch snapshot failed: {exc}")


# ── Nightly intraday-candle collection (own the data before it expires) ──────

async def _do_collect_option_candles():
    """
    Save today's 30-min candles for NIFTY/BANKNIFTY options near the money
    (±5% strikes, expiries ≤ 45 DTE) to /app/market_data/intraday/.
    Expired contracts vanish from every API — this builds our own permanent
    intraday dataset for strategy backtesting (Upstox charges for theirs).
    """
    import csv as _csv
    import time as _time
    from datetime import date as _d, timedelta as _tdl
    from pathlib import Path
    from sqlalchemy import select as _sel
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.core.encryption import decrypt as _dec
    from kiteconnect import KiteConnect

    async with AsyncSessionLocal() as db:
        cfg = (await db.execute(_sel(KiteConfig).limit(1))).scalar_one_or_none()
    if not cfg or not cfg.access_token_enc or cfg.token_date != _d.today():
        logger.warning("collect-candles: no valid Kite token today — skipped")
        return {"status": "skipped", "reason": "no kite token"}

    kite = KiteConnect(api_key=cfg.api_key)
    kite.set_access_token(_dec(cfg.access_token_enc))

    import redis as _r
    from app.config import settings as _st
    r = _r.from_url(_st.redis_url, decode_responses=True)

    inst = kite.instruments("NFO")   # the one allowed daily call
    today = _d.today()
    out_dir = Path("/app/market_data/intraday")
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = []
    for ul, step, pct in (("NIFTY", 50, 0.05), ("BANKNIFTY", 100, 0.05)):
        spot = float(r.get(f"spot:{ul}") or 0)
        if spot <= 0:
            continue
        lo, hi = spot * (1 - pct), spot * (1 + pct)
        for row in inst:
            if row["name"] != ul or row["segment"] != "NFO-OPT":
                continue
            exp = row["expiry"] if isinstance(row["expiry"], _d) else row["expiry"].date()
            if not (0 <= (exp - today).days <= 45):
                continue
            if not (lo <= float(row["strike"]) <= hi):
                continue
            targets.append((ul, row["tradingsymbol"], row["instrument_token"],
                            str(exp), float(row["strike"]), row["instrument_type"]))

    logger.info(f"collect-candles: {len(targets)} contracts to fetch")
    written = 0
    fname = out_dir / f"candles_{today.isoformat()}.csv"
    new_file = not fname.exists()
    with open(fname, "a", newline="") as fh:
        w = _csv.writer(fh)
        if new_file:
            w.writerow(["symbol", "underlying", "expiry", "strike", "type",
                        "ts", "open", "high", "low", "close", "volume", "oi"])
        for ul, sym, tok, exp, strike, ot in targets:
            try:
                candles = kite.historical_data(tok, today, today, "30minute", oi=True)
                for c in candles:
                    w.writerow([sym, ul, exp, strike, ot, c["date"].isoformat(),
                                c["open"], c["high"], c["low"], c["close"],
                                c.get("volume", 0), c.get("oi", 0)])
                written += 1
            except Exception as e:
                logger.debug(f"collect-candles {sym}: {e}")
            _time.sleep(0.35)   # stay under Kite's 3 req/s historical limit

    logger.info(f"collect-candles: wrote {written}/{len(targets)} contracts to {fname.name}")
    return {"status": "ok", "contracts": written, "file": fname.name}


@celery_app.task(name="workers.collect_option_candles")
def collect_option_candles():
    """Nightly: archive today's 30-min option candles before contracts expire."""
    try:
        result = _run_async(_do_collect_option_candles())
        _stamp_task_run("workers.collect_option_candles")
        return result
    except Exception as exc:
        logger.error(f"collect-candles failed: {exc}")
        return {"status": "error", "error": str(exc)}


# â”€â”€ Condorize mitigation (adopted 2026-07-04) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

MITIGATION_BUDGET = 200_000.0   # Rs2L reserve carved from the single Rs10L corpus (user 2026-07-04)


async def _condorize_group(group_id: str, group_trades: list, db) -> None:
    """
    Defense for a threatened 2-leg spread: sell an opposite-side spread in the
    same expiry at current ATM (real LTP + slippage). Legs join the same group
    so the managed exits operate on the combined credit. Margin comes from the
    mitigation budget (Redis mitigation_deployed), not the heat cap.
    """
    import redis as _r
    from datetime import datetime as _dtm
    from sqlalchemy import select as _sel
    from app.config import settings as _st
    from app.models.kite_config import KiteConfig
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.core.charges import charges_for_entry_only
    from app.models.portfolio import Portfolio

    r = _r.from_url(_st.redis_url, decode_responses=True)
    used = float(r.get("mitigation_deployed") or 0)
    if used >= MITIGATION_BUDGET * 0.9:
        logger.warning(f"condorize skipped for {group_id[:8]}: mitigation budget nearly exhausted ({used:,.0f})")
        return

    lead = group_trades[0]
    ul, expiry_iso = lead.underlying, lead.expiry_date
    qty = lead.quantity or lead.lot_size or 1
    step = 50 if ul == "NIFTY" else 100
    threatened_type = next((t.option_type for t in group_trades if t.action == "SELL"), "PE")
    new_ot = "CE" if threatened_type == "PE" else "PE"

    spot = float(r.get(f"spot:{ul}") or 0)
    if spot <= 0:
        return
    atm = round(spot / step) * step
    sk = float(atm)
    wk = sk + 2 * step if new_ot == "CE" else sk - 2 * step

    cfg = (await db.execute(_sel(KiteConfig).limit(1))).scalar_one_or_none()
    prem = {}
    for strike in (sk, wk):
        p, src, tok = await _fetch_option_ltp_global(cfg, ul, expiry_iso, strike, new_ot)
        if not p:
            logger.warning(f"condorize {group_id[:8]}: no real LTP for {strike}{new_ot} â€” aborting (never mitigate on estimates)")
            return
        prem[strike] = (p, src, tok)

    s_p, s_src, s_tok = prem[sk]
    w_p, w_src, w_tok = prem[wk]
    # slippage: SELL receives less, BUY pays more
    s_fill = round(max(0.05, s_p - max(0.25, s_p * 0.005)), 2)
    w_fill = round(w_p + max(0.25, w_p * 0.005), 2)
    credit2 = s_fill - w_fill
    width = 2 * step
    if not (width * 0.15 <= credit2 <= width * 0.85):
        logger.info(f"condorize {group_id[:8]}: new-side credit {credit2:.1f} fails sanity vs width {width} â€” skipped")
        return

    margin2 = (width - credit2) * qty
    r.incrbyfloat("mitigation_deployed", margin2)

    from app.core.strategies.composite import _build_symbol
    now = _dtm.utcnow()
    legs = [(sk, "SELL", s_fill, s_src, s_tok, "mitigation_sell"),
            (wk, "BUY", w_fill, w_src, w_tok, "mitigation_wing")]
    cash = 0.0
    for strike, action, fill, src, tok, role in legs:
        ch = charges_for_entry_only(fill, qty, action)
        cash += (fill * qty if action == "SELL" else -(fill * qty)) - ch
        db.add(Trade(
            mode=TradeMode.PAPER,
            symbol=_build_symbol(ul, expiry_iso, strike, new_ot),
            underlying=ul, option_type=new_ot, strike=strike,
            lot_size=lead.lot_size, expiry_date=expiry_iso,
            expiry_display=lead.expiry_display,
            action=action, direction=lead.direction, quantity=qty,
            entry_price=fill, current_price=fill,
            target_price=0.0, stop_loss=0.0,
            charges_entry=ch, unrealized_pnl=0.0,
            status=TradeStatus.OPEN, entry_time=now,
            entry_price_source=src, instrument_token=tok,
            margin_blocked=round(margin2 / 2, 2),
            trade_group_id=group_id, leg_role=role,
            notes=(f"STRATEGY:Condorized (mitigation)|MITIGATION: original {threatened_type}-side "
                   f"spread hit -1x credit; sold opposite {new_ot} spread to finance recovery. "
                   f"Tested 2026-07: net 3x vs stop-only baseline."),
        ))
    result = await db.execute(_sel(Portfolio).where(Portfolio.mode == "paper"))
    pf = result.scalar_one_or_none()
    if pf:
        pf.capital_current += cash          # credit received (margin tracked in mitigation pool)
    logger.info(f"CONDORIZED {group_id[:8]}: sold {sk:.0f}{new_ot}/{wk:.0f}{new_ot} "
                f"credit {credit2:.1f}/unit, mitigation margin {margin2:,.0f} "
                f"(pool used {used + margin2:,.0f}/{MITIGATION_BUDGET:,.0f})")


async def _fetch_option_ltp_global(cfg, ul, expiry_iso, strike, ot):
    """Standalone real-LTP fetch (Kite then Upstox) usable outside _auto_paper_trade."""
    from datetime import date as _d2
    from app.core.encryption import decrypt as _dec
    if cfg and cfg.access_token_enc and cfg.token_date == _d2.today():
        try:
            from kiteconnect import KiteConnect as _KC
            import calendar as _cal
            exp = _d2.fromisoformat(str(expiry_iso)[:10])
            yy = str(exp.year)[2:]
            last_tue = max(_d2(exp.year, exp.month, dd)
                           for dd in range(1, _cal.monthrange(exp.year, exp.month)[1] + 1)
                           if _d2(exp.year, exp.month, dd).weekday() == 1)
            base = f"{int(strike)}{ot}"
            mon3 = exp.strftime("%b").upper()
            sym = (f"{ul}{yy}{mon3}{base}" if exp == last_tue
                   else f"{ul}{yy}{exp.month}{exp.day:02d}{base}")
            k = _KC(api_key=cfg.api_key)
            k.set_access_token(_dec(cfg.access_token_enc))
            res = k.ltp([f"NFO:{sym}"])
            for v in res.values():
                if v.get("last_price", 0) > 0:
                    return float(v["last_price"]), "kite", v.get("instrument_token")
        except Exception as e:
            logger.debug(f"ltp_global kite failed: {e}")
    if cfg and cfg.upstox_access_token_enc and cfg.upstox_token_date == _d2.today():
        try:
            from app.core.data.upstox_ltp import get_ltp as _up
            p = _up(_dec(cfg.upstox_access_token_enc), ul, str(expiry_iso)[:10], strike, ot)
            if p and p > 0:
                return p, "upstox", None
        except Exception:
            pass
    return None, "none", None


# â”€â”€ 0DTE expiry-day straddle (experiment, 1 lot) â€” adopted 2026-07-04 â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _do_zero_dte_straddle():
    """
    Tuesday 09:45 IST: sell ATM straddle on the expiring NIFTY weekly, 1 lot.
    Tested (90 real expiry days): 56.7% win, PF 1.26, +40.6k. Intraday only:
    SL at 40% of credit / TP at 60% (group loop), hard square-off at EOD task.
    """
    from datetime import date as _d, datetime as _dtm
    import uuid
    import redis as _r
    from sqlalchemy import select as _sel
    from app.config import settings as _st
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.models.portfolio import Portfolio
    from app.core.charges import charges_for_entry_only
    from app.core.instruments import get_lot_size
    from app.core.options.expiry import available_expiries
    from app.core.strategies.composite import _build_symbol

    today = _d.today()
    exps = available_expiries("NIFTY", today)
    if not exps or exps[0]["dte"] != 0:
        logger.info("0DTE: today is not a NIFTY expiry day â€” skipped")
        return {"status": "skipped"}

    expiry_iso = exps[0]["date"]
    r = _r.from_url(_st.redis_url, decode_responses=True)
    spot = float(r.get("spot:NIFTY") or 0)
    if spot <= 0 or not r.get("ticker:last_real_tick"):
        logger.warning("0DTE: no real spot ticks â€” skipped (never trade on synthetic)")
        return {"status": "skipped", "reason": "no real ticks"}
    atm = float(round(spot / 50) * 50)
    lot = get_lot_size("NIFTY")

    async with AsyncSessionLocal() as db:
        cfg = (await db.execute(_sel(KiteConfig).limit(1))).scalar_one_or_none()
        legs = []
        for ot in ("CE", "PE"):
            p, src, tok = await _fetch_option_ltp_global(cfg, "NIFTY", expiry_iso, atm, ot)
            if not p:
                logger.warning(f"0DTE: no real LTP for {atm}{ot} â€” aborted")
                return {"status": "aborted"}
            fill = round(max(0.05, p - max(0.25, p * 0.005)), 2)
            legs.append((ot, fill, src, tok))

        gid = str(uuid.uuid4())
        now = _dtm.utcnow()
        credit = sum(f for _, f, _, _ in legs)
        margin = spot * lot * 0.12          # SPAN approx for short straddle
        cash = 0.0
        for ot, fill, src, tok in legs:
            ch = charges_for_entry_only(fill, lot, "SELL")
            cash += fill * lot - ch
            db.add(Trade(
                mode=TradeMode.PAPER,
                symbol=_build_symbol("NIFTY", expiry_iso, atm, ot),
                underlying="NIFTY", option_type=ot, strike=atm,
                lot_size=lot, expiry_date=expiry_iso, expiry_display=expiry_iso,
                action="SELL", direction="short", quantity=lot,
                entry_price=fill, current_price=fill,
                target_price=0.0, stop_loss=0.0,
                charges_entry=ch, unrealized_pnl=0.0,
                status=TradeStatus.OPEN, entry_time=now,
                entry_price_source=src, instrument_token=tok,
                margin_blocked=round(margin / 2, 2),
                trade_group_id=gid, leg_role="zdte",
                notes=("STRATEGY:0DTE Straddle (exp)|Expiry-day ATM straddle sell, 1 lot. "
                       "Tested 90 real expiry days: PF 1.26. SL 40pct credit / TP 60pct / EOD square-off."),
            ))
        pf = (await db.execute(_sel(Portfolio).where(Portfolio.mode == "paper"))).scalar_one_or_none()
        if pf:
            pf.capital_deployed += margin
            pf.capital_current += cash - margin
        await db.commit()
        try:
            from app.core.risk.gate import record_deployed
            record_deployed(margin)
        except Exception:
            pass
        logger.info(f"0DTE straddle OPENED: {atm} CE+PE credit {credit:.1f}/unit, group {gid[:8]}")
        return {"status": "opened", "credit": credit}


@celery_app.task(name="workers.zero_dte_straddle")
def zero_dte_straddle():
    """Expiry-day (Tuesday) 09:45 IST: 0DTE ATM straddle experiment, 1 lot."""
    try:
        result = _run_async(_do_zero_dte_straddle())
        _stamp_task_run("workers.zero_dte_straddle")
        return result
    except Exception as exc:
        logger.error(f"0DTE straddle failed: {exc}")
        return {"status": "error", "error": str(exc)}


# ── Post-fall bear call (experiment, 1 lot) — adopted 2026-07-08 ─────────────

async def _do_postfall_bearcall():
    """
    09:45 IST after a >=1.25% down day: sell NIFTY weekly bear call spread,
    short S+200 / wing S+300, 1 lot. Tested on 27 real post-fall mornings:
    81% win, PF 1.54, avg +419/trade (vs PF 1.27 on normal days; the same
    structure is PF 0.72 after big UP days, so it only trades post-fall).
    Managed by standard group exits (TP 50% credit / SL 2x / half-DTE).
    """
    import json as _json
    import uuid
    from datetime import date as _d, datetime as _dtm
    from pathlib import Path
    import redis as _r
    from sqlalchemy import select as _sel
    from app.config import settings as _st
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.models.trades import Trade, TradeStatus, TradeMode
    from app.models.portfolio import Portfolio
    from app.core.charges import charges_for_entry_only
    from app.core.instruments import get_lot_size
    from app.core.options.expiry import available_expiries
    from app.core.strategies.composite import _build_symbol

    if not _is_market_hours():
        return {"status": "skipped", "reason": "outside market hours"}

    # Trigger: previous session fell >= 1.25% (from the EOD digest archive)
    snaps = sorted(Path("/app/market_data/daily_snapshots").glob("*.json"))[-2:]
    if len(snaps) < 2:
        return {"status": "skipped", "reason": "not enough digest history"}
    d0 = _json.loads(snaps[0].read_text()).get("nifty") or {}
    d1 = _json.loads(snaps[1].read_text()).get("nifty") or {}
    if not d0.get("close") or not d1.get("close"):
        return {"status": "skipped", "reason": "digest missing closes"}
    prev_ret = d1["close"] / d0["close"] - 1
    if prev_ret > -0.0125:
        return {"status": "skipped", "reason": f"no trigger (prev day {prev_ret*100:+.2f}%)"}

    r = _r.from_url(_st.redis_url, decode_responses=True)
    spot = float(r.get("spot:NIFTY") or 0)
    if spot <= 0 or not r.get("ticker:last_real_tick"):
        logger.warning("postfall_bc: no real spot ticks — skipped (never trade on synthetic)")
        return {"status": "skipped", "reason": "no real ticks"}

    exps = available_expiries("NIFTY", _d.today())
    exp = next((e for e in exps if 2 <= e["dte"] <= 9), None)
    if not exp:
        return {"status": "skipped", "reason": "no weekly expiry in 2-9 DTE"}
    expiry_iso = exp["date"]
    lot = get_lot_size("NIFTY")
    k_short = float(round((spot + 200) / 50) * 50)
    k_wing = k_short + 100.0

    async with AsyncSessionLocal() as db:
        # one per day
        existing = (await db.execute(_sel(Trade).where(
            Trade.status == TradeStatus.OPEN, Trade.leg_role == "postfall_bc_short"))).scalars().first()
        if existing:
            return {"status": "skipped", "reason": "already open"}
        cfg = (await db.execute(_sel(KiteConfig).limit(1))).scalar_one_or_none()
        ps, src_s, tok_s = await _fetch_option_ltp_global(cfg, "NIFTY", expiry_iso, k_short, "CE")
        pw, src_w, tok_w = await _fetch_option_ltp_global(cfg, "NIFTY", expiry_iso, k_wing, "CE")
        if not ps or not pw:
            return {"status": "aborted", "reason": "no real LTP for legs"}
        fill_s = round(max(0.05, ps - max(0.25, ps * 0.005)), 2)   # sell slippage-adverse
        fill_w = round(pw + max(0.25, pw * 0.005), 2)              # buy slippage-adverse
        credit = fill_s - fill_w
        width = k_wing - k_short
        if not (0.15 * width <= credit <= 0.85 * width):
            logger.warning(f"postfall_bc: credit {credit:.1f} outside 15-85% of width {width} — skipped")
            return {"status": "skipped", "reason": "credit gate"}

        gid = str(uuid.uuid4())
        now = _dtm.utcnow()
        margin = (width - credit) * lot
        cash = 0.0
        legs = [("SELL", k_short, fill_s, src_s, tok_s, "postfall_bc_short"),
                ("BUY", k_wing, fill_w, src_w, tok_w, "postfall_bc_wing")]
        for action, k, fill, src, tok, role in legs:
            ch = charges_for_entry_only(fill, lot, action)
            cash += (fill * lot - ch) if action == "SELL" else (-(fill * lot) - ch)
            db.add(Trade(
                mode=TradeMode.PAPER,
                symbol=_build_symbol("NIFTY", expiry_iso, k, "CE"),
                underlying="NIFTY", option_type="CE", strike=k,
                lot_size=lot, expiry_date=expiry_iso, expiry_display=expiry_iso,
                action=action, direction="short" if action == "SELL" else "long",
                quantity=lot, entry_price=fill, current_price=fill,
                target_price=0.0, stop_loss=0.0,
                charges_entry=ch, unrealized_pnl=0.0,
                status=TradeStatus.OPEN, entry_time=now,
                entry_price_source=src, instrument_token=tok,
                margin_blocked=round(margin / 2, 2),
                trade_group_id=gid, leg_role=role,
                notes=("STRATEGY:Post-fall Bear Call (exp)|Prev session fell "
                       f"{prev_ret*100:.2f}%; tested 27 post-fall mornings: 81% win, PF 1.54 "
                       "(vs 0.72 after up days). Short S+200/wing S+300, TP50/SL2x/half-DTE."),
            ))
        pf = (await db.execute(_sel(Portfolio).where(Portfolio.mode == "paper"))).scalar_one_or_none()
        if pf:
            pf.capital_deployed += margin
            pf.capital_current += cash - margin
        await db.commit()
        try:
            from app.core.risk.gate import record_deployed
            record_deployed(margin)
        except Exception:
            pass
        logger.info(f"postfall_bc OPENED: {k_short}/{k_wing} CE credit {credit:.1f}/unit, group {gid[:8]}")
        return {"status": "opened", "credit": credit, "short": k_short, "wing": k_wing}


@celery_app.task(name="workers.postfall_bearcall")
def postfall_bearcall():
    """09:45 IST Mon-Fri: bear call spread the morning after a >=1.25% fall."""
    try:
        result = _run_async(_do_postfall_bearcall())
        _stamp_task_run("workers.postfall_bearcall")
        return result
    except Exception as exc:
        logger.error(f"postfall bearcall failed: {exc}")
        return {"status": "error", "error": str(exc)}



# â”€â”€ Pre-market readiness check â€” 08:50 IST Mon-Fri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _do_premarket_readiness():
    """
    Verify everything is GO before the 09:15 open. Each check exists because
    it actually failed at least once this week. Result cached in Redis
    (premarket_readiness) and served at GET /api/v1/system/readiness.
    """
    import json as _json
    from datetime import date as _d, datetime as _dtm, timedelta as _tdl, timezone as _tz
    from pathlib import Path
    import redis as _r
    from sqlalchemy import select as _sel, text as _text
    from app.config import settings as _st
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig

    checks = []          # (name, ok, detail)
    today = _d.today()

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # 1. Redis + DB reachable
    try:
        r = _r.from_url(_st.redis_url, decode_responses=True)
        r.ping()
        add("redis", True)
    except Exception as e:
        add("redis", False, str(e)[:80])
        r = None
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(_text("SELECT 1"))
            cfg = (await db.execute(_sel(KiteConfig).limit(1))).scalar_one_or_none()
        add("database", True)
    except Exception as e:
        add("database", False, str(e)[:80])
        cfg = None

    # 2. Broker tokens fresh TODAY (they expire daily â€” bit us twice).
    # Date check alone is NOT enough: 2026-07-08 a same-morning token was
    # still rejected by Kite ("Incorrect api_key or access_token").
    # So validate LIVE with a real API call.
    kite_ok = bool(cfg and cfg.access_token_enc and cfg.token_date == today)
    kite_detail = "" if kite_ok else "REGENERATE Kite token before open â€” entries fall back to estimates without it"
    if kite_ok:
        try:
            from kiteconnect import KiteConnect
            from app.core.encryption import decrypt as _dec
            _kc = KiteConnect(api_key=cfg.api_key)
            _kc.set_access_token(_dec(cfg.access_token_enc))
            _q = _kc.quote(["NSE:NIFTY 50"])
            _ltp = list(_q.values())[0].get("last_price") if _q else None
            kite_ok = bool(_ltp and _ltp > 0)
            kite_detail = f"live-validated, NIFTY={_ltp}" if kite_ok else "quote returned no price"
        except Exception as _ke:
            kite_ok = False
            kite_detail = f"token date is today but API REJECTS it â€” regenerate: {str(_ke)[:60]}"
    add("kite_token_fresh", kite_ok, kite_detail)
    up_ok = bool(cfg and cfg.upstox_access_token_enc and cfg.upstox_token_date == today)
    add("upstox_token_fresh", up_ok,
        "" if up_ok else "regenerate Upstox token (backtests + LTP fallback need it)")

    # 3. Spot keys present (ticker seeded) â€” freshness is checked in-hours by heartbeat
    if r:
        sn, sb = r.get("spot:NIFTY"), r.get("spot:BANKNIFTY")
        add("spot_keys", bool(sn and sb), f"NIFTY={sn} BANKNIFTY={sb}")

    # 4. Trading not unexpectedly halted; risk params sane
    if r:
        halted = bool(r.get("trading_halted")) or bool(r.get("kill_switch"))
        add("not_halted", not halted, "trading_halted/kill_switch set!" if halted else "")
        try:
            from app.core.risk.gate import get_risk_params
            rp = get_risk_params()
            add("risk_params", rp.get("paper_capital", 0) > 0,
                f"heat {rp.get('max_portfolio_heat')}% cap {rp.get('paper_capital')}")
        except Exception as e:
            add("risk_params", False, str(e)[:80])

    # 5. Celery beat alive: key tasks stamped within their expected windows
    if r:
        hs = r.get("task_last_run:workers.health_scan")
        ok_beat = False
        if hs:
            try:
                age = (_dtm.utcnow() - _dtm.fromisoformat(hs)).total_seconds()
                ok_beat = age < 900
            except Exception:
                pass
        add("celery_beat", ok_beat, f"health_scan last run {hs}" if hs else "no health_scan stamp")

    # 6. Trade integrity clean
    try:
        from app.workers.tasks import _verify_trade_integrity
        v = await _verify_trade_integrity()
        add("trade_integrity", len(v) == 0, "; ".join(v[:2]) if v else "")
    except Exception as e:
        add("trade_integrity", False, str(e)[:80])

    # 7. Data freshness: candle archive collected last session; VIX file recent
    arch = Path("/app/market_data/intraday")
    recent = sorted(arch.glob("candles_*.csv"))[-1].name if arch.exists() and list(arch.glob("candles_*.csv")) else None
    add("candle_archive", recent is not None, f"latest: {recent}")
    vix = Path("/app/market_data/india_vix.csv")
    add("vix_cache", vix.exists() and (today - _d.fromtimestamp(vix.stat().st_mtime)).days <= 7,
        "stale/missing india_vix.csv" if not vix.exists() else "")

    passed = sum(1 for c in checks if c["ok"])
    status = "GO" if passed == len(checks) else ("DEGRADED" if passed >= len(checks) - 2 else "NO-GO")
    result = {"status": status, "passed": f"{passed}/{len(checks)}", "checks": checks,
              "ts_ist": (_dtm.now(_tz.utc) + _tdl(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M IST")}
    if r:
        r.setex("premarket_readiness", 86400, _json.dumps(result))
    log = logger.warning if status != "GO" else logger.info
    log(f"PRE-MARKET READINESS: {status} ({passed}/{len(checks)}) â€” "
        + "; ".join(f"{c['check']}:{'OK' if c['ok'] else 'FAIL ' + c['detail']}" for c in checks if not c["ok"]))
    return result


@celery_app.task(name="workers.premarket_readiness")
def premarket_readiness():
    """08:50 IST Mon-Fri: verify the system is GO before market open."""
    try:
        result = _run_async(_do_premarket_readiness())
        _stamp_task_run("workers.premarket_readiness")
        return result
    except Exception as exc:
        logger.error(f"premarket readiness failed: {exc}")
        return {"status": "ERROR", "error": str(exc)}


# ── EOD market digest — durable daily snapshot to disk ────────────────────────

async def _do_eod_market_digest():
    """
    15:40 IST: fold the day's 15-min market_watch snapshots + closed trades +
    VIX into one JSON file at /app/market_data/daily_snapshots/YYYY-MM-DD.json.
    Redis snapshots expire in 7 days; this file is permanent — it is both the
    post-close discussion brief (read one small file, zero tokens intraday)
    and raw material for future analysis.
    """
    import json as _json
    from datetime import datetime as _dt2, timedelta as _td2, timezone as _tz2
    from pathlib import Path
    import redis as _r
    from sqlalchemy import text as _text
    from app.config import settings as _st
    from app.database import AsyncSessionLocal

    now_ist = _dt2.now(_tz2.utc) + _td2(hours=5, minutes=30)
    if now_ist.weekday() >= 5:
        return None
    day = now_ist.strftime("%Y-%m-%d")
    r = _r.from_url(_st.redis_url, decode_responses=True)

    # intraday series from the 15-min snapshots
    snaps = [_json.loads(x) for x in r.lrange(f"market_watch:{day}", 0, -1)]
    series = [{"t": s["ts_ist"],
               "nifty": float(s["nifty"]) if s.get("nifty") else None,
               "banknifty": float(s["banknifty"]) if s.get("banknifty") else None,
               "open_pnl": round(sum(s.get("open_groups", {}).values()))}
              for s in snaps]
    nvals = [p["nifty"] for p in series if p["nifty"]]
    bvals = [p["banknifty"] for p in series if p["banknifty"]]

    digest = {
        "date": day,
        "generated_ist": now_ist.strftime("%H:%M IST"),
        "nifty": {"open": nvals[0], "close": nvals[-1], "high": max(nvals), "low": min(nvals),
                  "chg_pct": round((nvals[-1] / nvals[0] - 1) * 100, 2)} if nvals else None,
        "banknifty": {"open": bvals[0], "close": bvals[-1], "high": max(bvals), "low": min(bvals),
                      "chg_pct": round((bvals[-1] / bvals[0] - 1) * 100, 2)} if bvals else None,
        "series": series,
        "real_ticks_all_day": all(s.get("real_ticks") for s in snaps) if snaps else False,
    }

    # VIX close (nightly-updated cache)
    try:
        vix = Path("/app/market_data/india_vix.csv").read_text().strip().splitlines()[-1]
        digest["vix_last"] = float(vix.split(",")[1])
    except Exception:
        digest["vix_last"] = None

    async with AsyncSessionLocal() as db:
        closed = (await db.execute(_text(
            "SELECT trade_group_id, underlying, string_agg(DISTINCT exit_reason, ','), "
            "ROUND(SUM(pnl)::numeric,0), min(entry_time), max(exit_time) "
            "FROM trades WHERE status='CLOSED' AND exit_time >= CURRENT_DATE AND mode='PAPER' "
            "GROUP BY trade_group_id, underlying"))).all()
        digest["closed_groups"] = [
            {"group": (g or "?")[:8], "ul": ul, "exit_reason": reas, "net_pnl": float(p or 0)}
            for g, ul, reas, p, _e, _x in closed]
        digest["closed_net"] = round(sum(c["net_pnl"] for c in digest["closed_groups"]))
        open_rows = (await db.execute(_text(
            "SELECT trade_group_id, underlying, ROUND(SUM(unrealized_pnl)::numeric,0) "
            "FROM trades WHERE status='OPEN' AND mode='PAPER' GROUP BY trade_group_id, underlying"))).all()
        digest["open_groups"] = [{"group": (g or "?")[:8], "ul": ul, "unrealized": float(p or 0)}
                                 for g, ul, p in open_rows]
        digest["open_unrealized"] = round(sum(o["unrealized"] for o in digest["open_groups"]))
        sigs = (await db.execute(_text(
            "SELECT pattern_name, count(*) FROM signals WHERE created_at >= CURRENT_DATE "
            "GROUP BY pattern_name"))).all()
        digest["signals_today"] = {p: int(n) for p, n in sigs}
        try:
            anom = (await db.execute(_text(
                "SELECT source, kind, severity, auto_fixed, count(*), max(detail->>'msg') "
                "FROM anomalies WHERE ts >= CURRENT_DATE GROUP BY 1,2,3,4 ORDER BY 3"))).all()
            digest["anomalies_today"] = [
                {"source": s, "kind": k, "severity": sev, "auto_fixed": fx,
                 "count": int(n), "example": ex}
                for s, k, sev, fx, n, ex in anom]
        except Exception:
            digest["anomalies_today"] = []

    try:
        integ = r.get("trade_integrity:last")
        digest["integrity_violations"] = len(_json.loads(integ)["violations"]) if integ else None
    except Exception:
        digest["integrity_violations"] = None

    out_dir = Path("/app/market_data/daily_snapshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{day}.json"
    out.write_text(_json.dumps(digest, indent=1, default=str))
    r.setex("eod_digest:last", 86400 * 3, _json.dumps(digest, default=str))
    logger.info(f"EOD digest written: {out} closed_net={digest['closed_net']} "
                f"open_unrl={digest['open_unrealized']} snaps={len(series)}")
    return digest


@celery_app.task(name="workers.eod_market_digest")
def eod_market_digest():
    """15:40 IST Mon-Fri: durable end-of-day market + book digest to disk."""
    try:
        result = _run_async(_do_eod_market_digest())
        _stamp_task_run("workers.eod_market_digest")
        return result
    except Exception as exc:
        logger.error(f"EOD digest failed: {exc}")
        return {"status": "ERROR", "error": str(exc)}

