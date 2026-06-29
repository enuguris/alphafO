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

TIMEFRAME_ROWS: dict[Timeframe, int] = {
    "15m": 96,   # 1.5 trading days of 15-min bars
    "1h":  120,  # ~30 trading days of 1h bars
    "4h":  100,  # ~2 months of 4h bars
    "daily": 120,
}

TIMEFRAME_DTE: dict[Timeframe, int] = {
    "15m":  1,
    "1h":   3,
    "4h":   7,
    "daily": 14,
}

TIMEFRAME_STYLE: dict[Timeframe, str] = {
    "15m": "intraday",
    "1h":  "intraday",
    "4h":  "positional",
    "daily": "positional",
}


def synthetic_ohlcv(underlying: str, timeframe: Timeframe = "daily") -> pd.DataFrame:
    """
    Generate deterministic synthetic OHLCV that reliably triggers patterns.
    Each timeframe gets a different seed so signals vary across TFs.
    """
    rows = TIMEFRAME_ROWS[timeframe]
    seed = abs(hash(f"{underlying}_{timeframe}")) % (2**31)
    rng = np.random.default_rng(seed)

    base = BASE_PRICES.get(underlying.upper(), 1500)

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

    # Force 1.2% gap on last bar (triggers gap_fill)
    open_arr[-1] = close_arr[-2] * 1.012

    # Rising OI in last 5 bars (triggers oi_buildup)
    oi_base = float(rng.integers(5_000_000, 15_000_000))
    oi_arr = np.full(rows, oi_base)
    for i in range(rows - 5, rows):
        oi_arr[i] = oi_arr[i - 1] * rng.uniform(1.02, 1.06)

    # IV: gently trending
    iv_arr = 18.0 + np.cumsum(rng.uniform(-0.3, 0.3, rows))
    iv_arr = np.clip(iv_arr, 10, 45)

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
        # 1. Data
        ohlcv = synthetic_ohlcv(underlying, timeframe)
        spot = float(ohlcv["close"].iloc[-1])

        # 2. Regime
        try:
            regime = RegimeDetector().detect(ohlcv)
        except Exception:
            regime = {"trend": "ranging", "volatility": "normal", "adx": 20.0,
                      "india_vix_proxy": 15.0, "suitable_patterns": []}

        # 3. IV rank
        chain_svc = ChainService()
        iv_history = chain_svc.get_iv_history(underlying)
        current_iv = float(ohlcv["iv"].iloc[-1])
        iv_rank = IVRankService.iv_rank(current_iv, iv_history)
        strategy_bias = IVRankService.strategy_bias(iv_rank)

        # 4. Options chain
        chain_df = chain_svc.get_chain(underlying)
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

        # 7. Run patterns
        registry = PatternRegistry.get()
        all_signals = []
        for pattern in registry.all():
            try:
                sigs = pattern.detect(ohlcv, options_chain=chain_df, underlying=underlying, context=context)
                all_signals.extend(sigs)
            except Exception as e:
                logger.debug(f"Pattern {pattern.name} skipped for {underlying}/{timeframe}: {e}")

        # Filter
        valid = [s for s in all_signals if s.confidence_score >= 0.5 and s.risk_reward_ratio >= 1.5]
        valid.sort(key=lambda s: s.confidence_score, reverse=True)

        if not valid:
            return []

        # 8. Options enrichment
        selector = StrikeSelector()
        dte = TIMEFRAME_DTE[timeframe]
        enriched = []

        for s in valid:
            try:
                opt = selector.select(underlying, spot, s.direction, iv_rank, dte, s.pattern_name)
            except Exception:
                opt = {"instrument": underlying, "option_type": None, "strategy": None,
                       "strike": None, "expiry_date_str": None, "lot_size": LOT_SIZES.get(underlying, 50)}

            greeks_data = {}
            if opt.get("strike") and opt.get("option_type"):
                try:
                    g = compute_greeks(spot, opt["strike"], dte / 365.0, current_iv / 100.0, opt["option_type"], RISK_FREE_RATE)
                    greeks_data = {"delta": round(g.delta, 4), "gamma": round(g.gamma, 6),
                                   "theta": round(g.theta, 4), "vega": round(g.vega, 4)}
                    estimated_premium = abs(g.delta) * spot * 0.02
                    max_loss = estimated_premium * (opt.get("lot_size") or 25)
                except Exception:
                    estimated_premium = max_loss = None
            else:
                estimated_premium = max_loss = None

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
                "confidence_score":   round(s.confidence_score, 4),
                "explanation":        s.explanation,
                "trading_style":      TIMEFRAME_STYLE[timeframe],
                "timeframe":          timeframe,
                "option_type":        opt.get("option_type"),
                "strike":             opt.get("strike"),
                "expiry_date_str":    opt.get("expiry_date_str"),
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
                "estimated_premium":  round(estimated_premium, 2) if estimated_premium else None,
                "max_loss":           round(max_loss, 2) if max_loss else None,
                "event_risk":         event_risk,
                "max_pain_strike":    max_pain_result.get("max_pain_strike"),
                "pcr":                max_pain_result.get("pcr"),
            })

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
