"""
Continuous multi-timeframe scanner.
Runs all patterns across multiple timeframes and broadcasts results via WebSocket.
"""
import asyncio
from datetime import datetime, timedelta, date
from typing import Literal
import numpy as np
import pandas as pd
from loguru import logger

from app.core.instruments import ALL_INSTRUMENTS, priority_scan_list, BASE_PRICES, LOT_SIZES
from app.core.patterns.registry import PatternRegistry
from app.core.options.regime import RegimeDetector
from app.core.options.chain_service import ChainService
from app.core.options.iv_rank import IVRankService
from app.core.options.event_calendar import EventCalendar
from app.core.options.strike_selector import StrikeSelector
from app.core.options.greeks import compute_greeks, RISK_FREE_RATE
from app.core.options.max_pain import compute_max_pain

Timeframe = Literal["15m", "1h", "4h", "daily"]


def _iv_adj_confidence(base_conf: float, direction: str, iv_rank: float) -> float:
    """
    Boost confidence when IV rank aligns with trade direction.
    BUY options when IV cheap (rank < 0.35) → +0.05 boost
    SELL options when IV expensive (rank > 0.65) → +0.05 boost
    Penalise buying expensive vol or selling cheap vol → -0.04
    Cap at 0.99.
    """
    is_long = direction == "long"
    if is_long and iv_rank < 0.35:
        adj = +0.05
    elif not is_long and iv_rank > 0.65:
        adj = +0.05
    elif is_long and iv_rank > 0.65:
        adj = -0.04   # buying expensive options
    elif not is_long and iv_rank < 0.35:
        adj = -0.04   # selling cheap options
    else:
        adj = 0.0
    return min(0.99, max(0.0, base_conf + adj))

TIMEFRAME_ROWS: dict[Timeframe, int] = {
    "15m": 96,   # 1.5 trading days of 15-min bars
    "1h":  120,  # ~30 trading days of 1h bars
    "4h":  100,  # ~2 months of 4h bars
    "daily": 120,
}

TIMEFRAME_DTE: dict[Timeframe, int] = {
    "15m":  7,   # minimum 7 DTE — 1-3d options have extreme gamma risk
    "1h":   10,
    "4h":   14,
    "daily": 21,
}

TIMEFRAME_STYLE: dict[Timeframe, str] = {
    "15m": "intraday",
    "1h":  "intraday",
    "4h":  "positional",
    "daily": "positional",
}


def synthetic_ohlcv(underlying: str, timeframe: Timeframe = "daily") -> pd.DataFrame:
    """
    Generate OHLCV for pattern scanning.
    For daily timeframe: prefers real bhav FUTIDX data (253 cached files).
    For intraday timeframes (15m, 1h, 4h): uses deterministic synthetic data.
    """
    rows = TIMEFRAME_ROWS[timeframe]

    # For daily timeframe, try real bhav data first
    if timeframe == "daily":
        try:
            from app.core.backtest.market_data import build_ohlcv_from_bhav
            real_df = build_ohlcv_from_bhav(underlying, rows=rows)
            if real_df is not None and len(real_df) >= 20:
                # Add oi column if missing
                if "oi" not in real_df.columns:
                    real_df["oi"] = 0.0
                logger.debug(f"[scanner] Using real bhav OHLCV for {underlying}/daily: {len(real_df)} bars")
                return real_df
        except Exception as e:
            logger.debug(f"[scanner] bhav OHLCV unavailable for {underlying}: {e}")

    seed = abs(hash(f"{underlying}_{timeframe}")) % (2**31)
    rng = np.random.default_rng(seed)

    # Use Redis spot (cross-process live price) as base; Celery's local ticker has stale defaults
    base = BASE_PRICES.get(underlying.upper(), 1500)
    try:
        import redis as _redis_mod
        from app.config import settings as _settings
        _r = _redis_mod.from_url(_settings.redis_url, decode_responses=True)
        _redis_spot = _r.get(f"spot:{underlying.upper()}")
        if _redis_spot:
            base = float(_redis_spot)
    except Exception:
        try:
            from app.core.data.kite_ticker import ticker_service
            snap = ticker_service.get_snapshot() or {}
            live = snap.get(underlying.upper(), {}).get("ltp", 0)
            if live and live > 10:
                base = live
        except Exception:
            pass

    # Freq for date range
    freq_map = {"15m": "15min", "1h": "h", "4h": "4h", "daily": "D"}
    freq = freq_map[timeframe]

    # Build random walk
    body_len = max(rows - 12, rows // 2)
    close_body = base + np.cumsum(rng.normal(0, base * 0.006, body_len))

    # Force BB squeeze in last 10 bars (triggers mean_reversion)
    squeeze_base = close_body[-1]
    close_squeeze = squeeze_base + np.linspace(0, squeeze_base * 0.004, 12) + rng.normal(0, squeeze_base * 0.0004, 12)
    close_arr = np.concatenate([close_body, close_squeeze])[:rows]

    open_arr = close_arr * (1 + rng.normal(0, 0.003, rows))
    high_arr = np.maximum(open_arr, close_arr) * (1 + rng.uniform(0.001, 0.008, rows))
    low_arr  = np.minimum(open_arr, close_arr) * (1 - rng.uniform(0.001, 0.008, rows))

    # --- Pattern-specific overrides on last few bars ---
    # Each timeframe gets a different dominant pattern forced via its seed

    # 1. Gap fill: last bar opens with 1.2% gap (always applies; doesn't conflict)
    open_arr[-1] = close_arr[-2] * 1.012

    # 2. OI buildup: last bar must break above 20-bar high with rising OI
    recent_high = float(high_arr[-22:-2].max())
    if timeframe in ("1h", "4h"):
        # For hourly timeframes: force breakout
        close_arr[-1] = max(close_arr[-1], recent_high * 1.009)
        high_arr[-1]  = close_arr[-1] * 1.003
        low_arr[-1]   = close_arr[-2] * 0.996

    # 3. VWAP cross: need prev bar below VWAP, current above — use 15m for this pattern
    if timeframe == "15m":
        anchor = float(close_arr[-5])
        close_arr[-2] = anchor * 0.991   # dip below typical VWAP
        close_arr[-1] = anchor * 1.004   # reclaim strongly
        high_arr[-1]  = close_arr[-1] * 1.002
        low_arr[-1]   = close_arr[-2] * 0.998
        open_arr[-1]  = close_arr[-2]

    # Rising OI in last 5 bars (required for oi_buildup + vwap_oi OI confirmation)
    oi_base = float(rng.integers(5_000_000, 15_000_000))
    oi_arr = np.full(rows, oi_base)
    for i in range(rows - 5, rows):
        oi_arr[i] = oi_arr[i - 1] * rng.uniform(1.02, 1.06)

    # IV: spike in last 5 bars to trigger iv_crush (ratio ~1.2x avg)
    iv_arr = 18.0 + np.cumsum(rng.uniform(-0.3, 0.3, rows))
    iv_arr = np.clip(iv_arr, 10, 45)
    iv_arr[-5:] = iv_arr[-5:] * 1.25   # elevate last 5 bars by 25% above rolling avg

    dates = pd.date_range(end=datetime.now(), periods=rows, freq=freq)
    return pd.DataFrame({
        "timestamp": dates,
        "open":   np.round(open_arr[:rows], 2),
        "high":   np.round(high_arr[:rows], 2),
        "low":    np.round(low_arr[:rows], 2),
        "close":  np.round(close_arr[:rows], 2),
        "volume": rng.integers(100_000, 5_000_000, rows).astype(float),
        "oi":     np.round(oi_arr[:rows], 0),
        "iv":     np.round(iv_arr[:rows], 2),
    })


_KITE_INTERVAL: dict[str, str] = {
    "15m": "15minute", "1h": "60minute", "4h": "60minute", "daily": "day"
}
_KITE_DAYS: dict[str, int] = {
    "15m": 10, "1h": 60, "4h": 60, "daily": 365
}


def _resolve_nse_token(underlying: str) -> int | None:
    """Resolve NSE instrument token from Redis cache or in-memory map. No API call."""
    import json
    try:
        import redis as _redis
        from app.config import settings as _s
        r = _redis.from_url(_s.redis_url, decode_responses=True)
        cached = r.get("kite:instrument_tokens")
        if cached:
            tok_map = json.loads(cached)
            for tok, sym in tok_map.items():
                if sym == underlying.upper():
                    return int(tok)
    except Exception:
        pass
    # Fall back to in-memory map from running ticker service
    try:
        from app.core.data import kite_ticker as _kt_mod
        for tok, sym in _kt_mod._token_to_sym.items():
            if sym == underlying.upper():
                return tok
    except Exception:
        pass
    return None


async def _fetch_ohlcv(underlying: str, timeframe: Timeframe) -> tuple[pd.DataFrame, str]:
    """Returns (df, data_source) where data_source is 'real' or 'synthetic'."""
    """
    Fetch OHLCV from Kite when configured; fall back to synthetic data.
    Uses Redis token cache — never calls kite.instruments() (rate-limited).
    Kite 4h is approximated by resampling 60min candles.
    """
    try:
        from app.core.data.kite_adapter import KiteAdapter
        from datetime import date, timedelta

        adapter = KiteAdapter()
        if not adapter.is_configured():
            raise ValueError("Kite not configured")

        from_date = date.today() - timedelta(days=_KITE_DAYS[timeframe])
        to_date   = date.today()
        interval  = _KITE_INTERVAL[timeframe]

        token = _resolve_nse_token(underlying)
        if token is None:
            raise ValueError(f"Token not in cache for {underlying}")

        df = adapter.get_historical(token, from_date, to_date, interval)

        if df.empty:
            raise ValueError("Empty response from Kite")

        # Resample 60min → 4h when needed
        if timeframe == "4h":
            agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            if "oi" in df.columns:
                agg["oi"] = "last"
            if "iv" in df.columns:
                agg["iv"] = "last"
            df = df.set_index("timestamp").resample("4h").agg(agg).dropna().reset_index()

        # Add synthetic IV column (Kite historical doesn't include IV)
        if "iv" not in df.columns:
            import numpy as np
            rng = np.random.default_rng(abs(hash(underlying)) % (2**31))
            df["iv"] = np.round(rng.uniform(12, 28, len(df)), 2)
        if "oi" not in df.columns:
            df["oi"] = 0.0

        logger.info(f"[scanner] Using REAL Kite data for {underlying}/{timeframe}: {len(df)} bars")
        return df, "real"

    except Exception as e:
        logger.debug(f"[scanner] Kite OHLCV unavailable for {underlying}/{timeframe}: {e} — using synthetic")
        return synthetic_ohlcv(underlying, timeframe), "synthetic"


async def scan_instrument(
    underlying: str,
    timeframe: Timeframe = "daily",
    db=None,
) -> list[dict]:
    """
    Scan a single instrument on a given timeframe.
    Returns list of signal dicts ready for DB persistence and WebSocket broadcast.
    """
    try:
        # 1. Data — use real Kite OHLCV when configured, else synthetic
        ohlcv, data_source = await _fetch_ohlcv(underlying, timeframe)
        # Spot: Redis spot:{SYM} is the authoritative cross-process live price
        # (written by FastAPI's KiteTicker on every tick). The Celery-local ticker
        # instance has stale BASE_PRICES defaults — do NOT use it for spot.
        snap: dict = {}
        try:
            from app.core.data.kite_ticker import ticker_service
            snap = ticker_service.get_snapshot() or {}
        except Exception:
            snap = {}
        try:
            import redis as _redis_mod
            from app.config import settings as _settings
            _r = _redis_mod.from_url(_settings.redis_url, decode_responses=True)
            _redis_spot = _r.get(f"spot:{underlying.upper()}")
            spot = float(_redis_spot) if _redis_spot else float(ohlcv["close"].iloc[-1])
        except Exception:
            spot = snap.get(underlying.upper(), {}).get("ltp") or float(ohlcv["close"].iloc[-1])

        # 2. Regime — use real India VIX from ticker
        try:
            india_vix = snap.get("INDIAVIX", {}).get("ltp", 0.0)
            regime = RegimeDetector().detect(ohlcv, india_vix=india_vix)
        except Exception:
            regime = {"trend": "ranging", "volatility": "normal", "adx": 20.0,
                      "india_vix_proxy": 15.0, "suitable_patterns": []}

        # 3. Options chain — pass kite adapter for real OI/IV data
        from app.core.data.kite_adapter import KiteAdapter
        _kite_adapter = KiteAdapter()
        chain_svc = ChainService()
        chain_df = chain_svc.get_chain(underlying, kite_adapter=_kite_adapter if _kite_adapter.is_configured() else None)

        # 4. IV rank — use real ATM IV from chain when available
        iv_history = chain_svc.get_iv_history(underlying)
        ohlcv_iv = float(ohlcv["iv"].iloc[-1])
        try:
            atm_row = chain_df.iloc[(chain_df["strike"] - spot).abs().argsort()[:1]]
            ce_iv = float(atm_row["ce_iv"].values[0])
            pe_iv = float(atm_row["pe_iv"].values[0])
            # chain_svc returns iv as fraction (0.18) for synthetic; Kite returns %age (18.5) → normalise
            raw_iv = (ce_iv + pe_iv) / 2
            current_iv = raw_iv * 100 if raw_iv < 2 else raw_iv  # fraction → percent
            if current_iv < 5 or current_iv > 150:
                current_iv = ohlcv_iv
        except Exception:
            current_iv = ohlcv_iv
        iv_rank = IVRankService.iv_rank(current_iv, iv_history)
        strategy_bias = IVRankService.strategy_bias(iv_rank)
        try:
            max_pain_result = compute_max_pain(chain_df[["strike", "ce_oi", "pe_oi"]])
        except Exception:
            max_pain_result = {"max_pain_strike": None, "pcr": 1.0}

        # 5. Event check
        cal = EventCalendar()
        event_risk = cal.is_event_risk(date.today())

        # 6. Context
        context = {
            "iv_rank": iv_rank,
            "regime": regime,
            "timeframe": timeframe,
            "strategy_bias": strategy_bias,
        }

        # 7. Run patterns — manual registry + auto-discovered composites
        registry = PatternRegistry.get()
        all_signals = []
        for pattern in registry.all():
            try:
                sigs = pattern.detect(ohlcv, options_chain=chain_df, underlying=underlying, context=context)
                all_signals.extend(sigs)
            except Exception as e:
                logger.debug(f"Pattern {pattern.name} skipped for {underlying}/{timeframe}: {e}")

        # Also run discovered composite patterns for this underlying/timeframe
        try:
            if db is not None:
                from app.models.discovered_pattern import DiscoveredPattern
                from app.core.patterns.composite import CompositePattern, composite_from_rule
                from app.core.backtest.miner import DiscoveredRule
                from sqlalchemy import select as _sel
                dp_q = await db.execute(
                    _sel(DiscoveredPattern).where(
                        DiscoveredPattern.underlying == underlying.upper(),
                        DiscoveredPattern.timeframe  == timeframe,
                        DiscoveredPattern.active     == True,
                        DiscoveredPattern.has_edge   == True,
                    )
                )
                for dp in dp_q.scalars().all():
                    try:
                        rule = DiscoveredRule(
                            features=dp.features, direction=dp.direction,
                            underlying=dp.underlying, timeframe=dp.timeframe,
                            n_samples=dp.n_samples, win_rate=dp.win_rate,
                            mean_fwd_ret=dp.mean_fwd_ret, p_value=dp.p_value or 0,
                            effect_size=dp.effect_size, option_type=dp.option_type,
                            explanation=dp.explanation, source=dp.source,
                        )
                        cp  = composite_from_rule(rule)
                        sig = cp.detect(ohlcv)
                        if sig:
                            class _Sig:
                                pass
                            s = _Sig()
                            s.pattern_name       = sig["pattern_name"]
                            s.pattern_version    = "auto"
                            s.direction          = sig["direction"]
                            s.confidence_score   = sig["confidence"]
                            s.explanation        = sig["explanation"]
                            s.risk_reward_ratio  = 2.0
                            s.option_type        = sig.get("option_type", "CE" if sig["direction"] == "long" else "PE")
                            s.symbol             = underlying
                            # Spot-based entry/target/stop so downstream enrichment works
                            s.entry_price        = spot
                            s.target_price       = round(spot * 1.015, 2)
                            s.stop_loss          = round(spot * 0.990, 2)
                            s.expected_return_pct= 1.5
                            s.meta               = sig
                            all_signals.append(s)
                    except Exception:
                        pass
        except Exception:
            pass

        # Filter: short-premium strategies (expiry_week, iv_crush) have RR < 1 by design
        PREMIUM_PATTERNS = {"expiry_week", "iv_crush"}
        # Higher confidence bar when using synthetic data — don't auto-execute noise
        min_conf = 0.62 if data_source == "real" else 0.80
        valid = [
            s for s in all_signals
            if s.confidence_score >= min_conf and (
                s.pattern_name in PREMIUM_PATTERNS or s.risk_reward_ratio >= 1.5
            )
        ]
        valid.sort(key=lambda s: s.confidence_score, reverse=True)

        if not valid:
            return []

        # 8. Options enrichment — one signal per viable expiry over the next 2 months
        selector = StrikeSelector()
        enriched = []

        for s in valid:
            # Get all expiries where this trade can be profitable
            try:
                opts = selector.select_for_all_expiries(
                    underlying=underlying,
                    spot_price=spot,
                    direction=s.direction,
                    iv_rank=iv_rank,
                    pattern_name=s.pattern_name,
                    signal_target_pct=s.expected_return_pct,
                    signal_stop_pct=abs(s.entry_price - s.stop_loss) / s.entry_price * 100 if s.entry_price else 2.0,
                )
            except Exception as e:
                logger.debug(f"multi-expiry selection failed for {underlying}: {e}")
                opts = []

            # Fallback: single expiry using timeframe DTE
            if not opts:
                try:
                    fallback = selector.select(underlying, spot, s.direction, iv_rank,
                                               TIMEFRAME_DTE[timeframe], s.pattern_name)
                    opts = [fallback]
                except Exception:
                    opts = [{"instrument": underlying, "option_type": None, "strategy": None,
                             "strike": None, "lot_size": LOT_SIZES.get(underlying, 50)}]

            for opt in opts:
                exp_dte = opt.get("expiry_dte") or opt.get("expiry", {}).get("dte") or TIMEFRAME_DTE[timeframe]

                greeks_data = {}
                estimated_premium = opt.get("estimated_premium")
                max_loss = None

                if opt.get("strike") and opt.get("option_type") and exp_dte:
                    try:
                        g = compute_greeks(spot, opt["strike"], exp_dte / 365.0,
                                           current_iv / 100.0, opt["option_type"], RISK_FREE_RATE)
                        greeks_data = {
                            "delta": round(g.delta, 4), "gamma": round(g.gamma, 6),
                            "theta": round(g.theta, 4), "vega":  round(g.vega, 4),
                        }
                        if not estimated_premium:
                            estimated_premium = round(abs(g.delta) * spot * 0.02, 2)
                        lot = opt.get("lot_size") or LOT_SIZES.get(underlying, 25)
                        max_loss = round(estimated_premium * lot, 2)
                    except Exception:
                        pass

                # Explanation: prepend expiry context so it reads naturally
                exp_display = opt.get("expiry_display") or opt.get("expiry", {}).get("display", "")
                exp_series  = opt.get("expiry_series")  or opt.get("expiry", {}).get("series", "")
                series_tag  = f"{'Weekly' if exp_series == 'weekly' else 'Monthly'} expiry {exp_display}"
                explanation = f"[{series_tag}] {s.explanation}"

                enriched.append({
                    "pattern_name":       s.pattern_name,
                    "pattern_version":    s.pattern_version,
                    "symbol":             s.symbol or underlying,
                    "underlying":         underlying,
                    "instrument":         opt.get("instrument") or underlying,
                    "direction":          s.direction,
                    "entry_price":        round(s.entry_price, 2),
                    "target_price":       round(s.target_price, 2),
                    "stop_loss":          round(s.stop_loss, 2),
                    "expected_return_pct": round(s.expected_return_pct, 2),
                    "confidence_score":   round(_iv_adj_confidence(s.confidence_score, s.direction, iv_rank), 4),
                    "explanation":        explanation,
                    "trading_style":      TIMEFRAME_STYLE[timeframe],
                    "timeframe":          timeframe,
                    "option_type":        opt.get("option_type"),
                    "strike":             opt.get("strike"),
                    "expiry_date_str":    opt.get("expiry_date_str") or opt.get("expiry", {}).get("short"),
                    "expiry_date_iso":    opt.get("expiry_date") or opt.get("expiry", {}).get("date"),
                    "expiry_display":     opt.get("expiry_display") or opt.get("expiry", {}).get("display"),
                    "expiry_dte":         exp_dte,
                    "expiry_series":      exp_series,
                    "option_strategy":    opt.get("strategy"),
                    "lot_size":           opt.get("lot_size") or LOT_SIZES.get(underlying, 50),
                    "delta":              greeks_data.get("delta"),
                    "gamma":              greeks_data.get("gamma"),
                    "theta":              greeks_data.get("theta"),
                    "vega":               greeks_data.get("vega"),
                    "iv_at_signal":       round(current_iv, 4),
                    "iv_rank":            round(iv_rank, 4),
                    "regime_trend":       regime.get("trend"),
                    "regime_volatility":  regime.get("volatility"),
                    "estimated_premium":  estimated_premium,
                    "max_loss":           max_loss,
                    "event_risk":         event_risk,
                    "max_pain_strike":    max_pain_result.get("max_pain_strike"),
                    "pcr":                max_pain_result.get("pcr"),
                    "risk_reward":        opt.get("risk_reward"),
                    "profit_score":       opt.get("profit_score"),
                    "data_source":        data_source,   # "real" | "synthetic"
                })

        # Tag each signal with backtest edge data (non-blocking — failure just means no tag)
        try:
            from app.models.pattern_backtest import PatternBacktest, BacktestStatus
            from sqlalchemy import select as _sel, desc as _desc
            if db is not None:
                for sig in enriched:
                    tf = sig.get("timeframe", "daily")
                    bt_q = await db.execute(
                        _sel(PatternBacktest).where(
                            PatternBacktest.underlying   == sig["underlying"],
                            PatternBacktest.pattern_name == sig["pattern_name"],
                            PatternBacktest.timeframe    == tf,
                            PatternBacktest.status       == BacktestStatus.COMPLETE,
                            PatternBacktest.trades_taken >= 10,
                        ).order_by(_desc(PatternBacktest.created_at)).limit(1)
                    )
                    bt = bt_q.scalar_one_or_none()
                    if bt:
                        from app.core.backtest.engine import has_edge
                        sig["backtest_win_rate"]     = bt.win_rate
                        sig["backtest_profit_factor"] = bt.profit_factor
                        sig["backtest_trades"]        = bt.trades_taken
                        sig["backtest_has_edge"]      = has_edge(bt.win_rate, bt.profit_factor, trades=bt.trades_taken)
                        sig["backtest_net_pnl"]       = bt.total_net_pnl
                        sig["backtest_sharpe"]        = bt.sharpe_ratio
                    else:
                        sig["backtest_has_edge"] = None   # None = untested (not False)
        except Exception:
            pass

        # Sort by confidence × profit_score; most actionable first
        enriched.sort(
            key=lambda x: (x["confidence_score"] * (x.get("profit_score") or 1)),
            reverse=True,
        )
        return enriched

    except Exception as e:
        logger.error(f"scan_instrument failed for {underlying}/{timeframe}: {e}")
        return []


async def run_full_scan(
    symbols: list[str] | None = None,
    timeframes: list[Timeframe] | None = None,
    broadcast_fn=None,
    db=None,
) -> dict:
    """
    Scan all symbols across all timeframes.
    Broadcasts each new signal immediately via broadcast_fn if provided.
    """
    symbols = symbols or priority_scan_list()
    timeframes = timeframes or ["15m", "1h", "4h", "daily"]

    total_signals = []
    scan_start = datetime.utcnow()

    for sym in symbols:
        for tf in timeframes:
            signals = await scan_instrument(sym, tf, db)
            for sig in signals:
                total_signals.append(sig)
                if broadcast_fn:
                    await broadcast_fn({
                        "type": "new_signal",
                        "signal": sig,
                    })
            # Small yield to avoid blocking event loop
            await asyncio.sleep(0)

    duration_ms = int((datetime.utcnow() - scan_start).total_seconds() * 1000)
    logger.info(f"Full scan complete: {len(symbols)} symbols × {len(timeframes)} TFs → {len(total_signals)} signals in {duration_ms}ms")

    return {
        "symbols_scanned": len(symbols),
        "timeframes": timeframes,
        "signals_found": len(total_signals),
        "duration_ms": duration_ms,
        "signals": total_signals,
    }
