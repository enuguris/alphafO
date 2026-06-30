"""
Walk-forward pattern backtesting engine.

Algorithm for each (underlying, pattern, timeframe):
  1. Fetch 1 year of OHLCV (Kite if available, else synthetic)
  2. Slide a window bar-by-bar through the data
  3. At each bar, run pattern.detect() on the history up to that bar
  4. If signal fires → BS-price an ATM option (same DTE as timeframe default)
  5. Roll forward up to DTE bars, re-pricing the option each day
  6. Exit when: target (+50% premium) hit | stop (-40% premium) hit | expiry
  7. Record outcome, accumulate metrics
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


# ── Option pricer (same BS as the rest of the app) ───────────────────────────

def _bs(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    if T <= 0:
        return max(0.0, S - K) if opt == "CE" else max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def _N(x: float) -> float:
        a1, a2, a3, a4, a5, p = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429, 0.3275911
        sign = 1 if x >= 0 else -1
        t = 1 / (1 + p * abs(x))
        poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
        return 0.5 * (1 + sign * (1 - poly * math.exp(-x * x / 2)))

    if opt == "CE":
        return max(0.05, S * _N(d1) - K * math.exp(-r * T) * _N(d2))
    return max(0.05, K * math.exp(-r * T) * _N(-d2) - S * _N(-d1))


RF = 0.07   # risk-free rate


# ── Charges estimate (round-trip, simplified) ─────────────────────────────────

def _charges(entry: float, exit_p: float, qty: int, action: str) -> float:
    entry_t, exit_t = entry * qty, exit_p * qty
    brok = min(20, entry_t * 0.0003) + min(20, exit_t * 0.0003)
    stt  = (exit_t if action == "BUY" else entry_t) * 0.000125
    txn  = (entry_t + exit_t) * 0.00053
    gst  = (brok + txn) * 0.18
    sebi = (entry_t + exit_t) / 1e7 * 10
    stamp = (entry_t if action == "BUY" else exit_t) * 0.00003
    return round(brok + stt + txn + gst + sebi + stamp, 2)


# ── Timeframe defaults ────────────────────────────────────────────────────────

_TF_DTE = {"15m": 7, "1h": 10, "4h": 14, "daily": 21}
_TF_KITE = {"15m": "15minute", "1h": "60minute", "4h": "60minute", "daily": "day"}
_TF_DAYS = {"15m": 60, "1h": 365, "4h": 730, "daily": 1825}


# ── Step sizes ────────────────────────────────────────────────────────────────

_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25}


@dataclass
class BacktestResult:
    bars_tested:     int = 0
    total_signals:   int = 0
    trades_taken:    int = 0
    winning_trades:  int = 0
    losing_trades:   int = 0
    win_rate:        float = 0.0
    profit_factor:   float = 0.0
    avg_winner:      float = 0.0
    avg_loser:       float = 0.0
    total_net_pnl:   float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio:    float = 0.0
    avg_holding_bars: float = 0.0
    data_source:     str = "synthetic"
    trades:          list = field(default_factory=list)   # list of trade dicts


async def run_backtest(
    underlying: str,
    pattern_name: str,
    timeframe: str = "daily",
    lookback_days: int | None = None,
    pattern_override=None,    # CompositePattern instance — bypasses registry lookup
) -> BacktestResult:
    """
    Run a walk-forward backtest for one (underlying, pattern, timeframe) combo.
    Returns a BacktestResult with full trade-level detail.

    pattern_override: pass a CompositePattern directly (for auto-discovered patterns)
                      without needing it registered in PatternRegistry.
    """
    from app.core.patterns.registry import PatternRegistry
    from app.core.instruments import LOT_SIZES

    if pattern_override is not None:
        pattern = pattern_override
    else:
        registry = PatternRegistry.get()
        pattern = next((p for p in registry.all() if p.name == pattern_name), None)
        if pattern is None:
            raise ValueError(f"Pattern '{pattern_name}' not found")

    sym = underlying.upper()
    lot_size = LOT_SIZES.get(sym, 25)
    step = _STEPS.get(sym, 50)
    days = lookback_days or _TF_DAYS[timeframe]
    target_dte = _TF_DTE[timeframe]

    # ── Fetch OHLCV ──────────────────────────────────────────────────────────
    ohlcv, data_source = await _fetch_historical(sym, timeframe, days)
    if ohlcv.empty or len(ohlcv) < 30:
        logger.warning(f"Backtest {sym}/{pattern_name}/{timeframe}: not enough data ({len(ohlcv)} bars)")
        return BacktestResult(data_source=data_source)

    result = BacktestResult(data_source=data_source)
    result.bars_tested = len(ohlcv)

    trade_pnls: list[float] = []
    equity_curve: list[float] = [0.0]

    min_bars = max(getattr(pattern, "min_data_rows", 20), 30)

    # ── Walk-forward loop ────────────────────────────────────────────────────
    i = min_bars
    while i < len(ohlcv) - target_dte:
        window = ohlcv.iloc[:i].copy()
        spot = float(window["close"].iloc[-1])
        bar_date = str(window["timestamp"].iloc[-1])[:10]

        # Estimate IV from rolling HV
        log_ret = np.log(window["close"] / window["close"].shift(1)).dropna()
        iv = max(0.10, min(0.45, float(log_ret.tail(20).std() * math.sqrt(252)) if len(log_ret) >= 20 else 0.18))

        try:
            # CompositePattern has a simpler detect(df) signature
            from app.core.patterns.composite import CompositePattern
            if isinstance(pattern, CompositePattern):
                raw = pattern.detect(window)
                if raw is None:
                    i += 1
                    continue

                # IV rank gate: only enter when options are relatively cheap (rank < 45)
                try:
                    iv_history = (
                        np.log(window["close"] / window["close"].shift(1))
                        .dropna()
                        .rolling(20).std() * np.sqrt(252)
                    ).dropna()
                    if len(iv_history) >= 52:
                        iv_rank_val = float((iv_history < iv).mean() * 100)
                        if iv_rank_val > 45:
                            i += 1
                            continue
                except Exception:
                    pass

                # Wrap into a minimal signal-like namespace
                class _S:
                    pass
                sig_wrap = _S()
                sig_wrap.direction        = raw["direction"]
                sig_wrap.option_type      = raw.get("option_type", "CE")
                sig_wrap.confidence_score = raw.get("confidence", 0.65)
                signals = [sig_wrap]
            else:
                signals = pattern.detect(window, options_chain=None, underlying=sym, context={
                    "iv_rank": 0.5, "regime": {"trend": "ranging", "volatility": "normal"}, "timeframe": timeframe
                })
        except Exception:
            i += 1
            continue

        if not signals:
            i += 1
            continue

        sig = signals[0]  # take highest-confidence signal
        result.total_signals += 1

        # Build option contract
        action = "BUY" if sig.direction == "long" else "SELL"
        opt_type = "CE" if sig.direction == "long" else "PE"
        atm = int(round(spot / step) * step)
        T0 = target_dte / 365.0
        entry_prem = _bs(spot, atm, T0, RF, iv, opt_type)

        # Skip illiquid premiums
        if entry_prem < 50.0:
            i += 1
            continue

        # BUY: target +50%, stop -40% | SELL: target -55%, stop +100%
        if action == "BUY":
            target_prem = entry_prem * 1.50
            stop_prem   = entry_prem * 0.60
        else:
            target_prem = entry_prem * 0.45
            stop_prem   = entry_prem * 2.00

        result.trades_taken += 1

        # ── Simulate trade outcome ────────────────────────────────────────────
        exit_price  = None
        exit_reason = "expiry"
        holding_bars = 0

        for j in range(1, target_dte + 1):
            idx = i + j - 1
            if idx >= len(ohlcv):
                break
            future_spot = float(ohlcv["close"].iloc[idx])
            dte_remaining = max(0, target_dte - j)
            T_rem = dte_remaining / 365.0
            current_prem = _bs(future_spot, atm, T_rem, RF, iv, opt_type)
            holding_bars = j

            if action == "BUY":
                if current_prem >= target_prem:
                    exit_price, exit_reason = current_prem, "target"
                    break
                if current_prem <= stop_prem:
                    exit_price, exit_reason = current_prem, "stop"
                    break
            else:  # SELL
                if current_prem <= target_prem:
                    exit_price, exit_reason = current_prem, "target"
                    break
                if current_prem >= stop_prem:
                    exit_price, exit_reason = current_prem, "stop"
                    break

        if exit_price is None:
            # Expired — intrinsic value
            final_spot = float(ohlcv["close"].iloc[min(i + target_dte, len(ohlcv) - 1)])
            exit_price = max(0.05, final_spot - atm) if opt_type == "CE" else max(0.05, atm - final_spot)

        # P&L
        charges = _charges(entry_prem, exit_price, lot_size, action)
        if action == "BUY":
            gross = (exit_price - entry_prem) * lot_size
        else:
            gross = (entry_prem - exit_price) * lot_size
        net = gross - charges
        pnl_pct = net / (entry_prem * lot_size) * 100

        if net > 0:
            result.winning_trades += 1
        else:
            result.losing_trades += 1

        trade_pnls.append(net)
        equity_curve.append(equity_curve[-1] + net)

        result.trades.append({
            "signal_date":  bar_date,
            "direction":    sig.direction,
            "option_type":  opt_type,
            "strike":       atm,
            "expiry_dte":   target_dte,
            "spot_at_entry": round(spot, 2),
            "entry_price":  round(entry_prem, 2),
            "exit_price":   round(exit_price, 2),
            "exit_reason":  exit_reason,
            "holding_bars": holding_bars,
            "gross_pnl":    round(gross, 2),
            "charges":      round(charges, 2),
            "net_pnl":      round(net, 2),
            "pnl_pct":      round(pnl_pct, 2),
            "iv_at_entry":  round(iv * 100, 2),
            "confidence":   round(sig.confidence_score, 4),
        })

        # Skip forward past the holding period to avoid overlapping trades
        i += max(1, holding_bars)

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    if result.trades_taken > 0:
        result.win_rate = round(result.winning_trades / result.trades_taken, 4)

    winner_pnls = [p for p in trade_pnls if p > 0]
    loser_pnls  = [p for p in trade_pnls if p <= 0]

    result.avg_winner = round(sum(winner_pnls) / len(winner_pnls), 2) if winner_pnls else 0.0
    result.avg_loser  = round(sum(loser_pnls) / len(loser_pnls), 2) if loser_pnls else 0.0
    result.total_net_pnl = round(sum(trade_pnls), 2)

    gross_wins  = sum(winner_pnls)
    gross_losses = abs(sum(loser_pnls))
    result.profit_factor = round(gross_wins / gross_losses, 3) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

    # Max drawdown from equity curve — skip periods where peak ≤ 0
    # to avoid division-by-near-zero when the curve starts at 0 capital.
    if len(equity_curve) > 1:
        peak = equity_curve[0]
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        result.max_drawdown_pct = round(min(max_dd, 100.0), 2)

    # Simplified Sharpe (annualised)
    if len(trade_pnls) >= 5:
        returns = np.array(trade_pnls)
        mean_r, std_r = returns.mean(), returns.std()
        # Annualise: assume ~252 bars per year / avg holding bars
        avg_hold = sum(t["holding_bars"] for t in result.trades) / max(1, len(result.trades))
        result.avg_holding_bars = round(avg_hold, 1)
        annual_factor = math.sqrt(max(1, 252 / max(1, avg_hold)))
        result.sharpe_ratio = round((mean_r / (std_r + 1e-9)) * annual_factor, 3) if std_r > 0 else 0.0

    logger.info(
        f"Backtest {sym}/{pattern_name}/{timeframe}: "
        f"{result.trades_taken} trades | WR={result.win_rate:.0%} | "
        f"PF={result.profit_factor:.2f} | net ₹{result.total_net_pnl:.0f} | src={data_source}"
    )
    return result


async def _fetch_historical(sym: str, timeframe: str, days: int) -> tuple[pd.DataFrame, str]:
    """Fetch real Kite OHLCV or fall back to synthetic."""
    try:
        from app.core.data.kite_adapter import KiteAdapter
        from app.core.scanner import _resolve_nse_token

        adapter = KiteAdapter()
        if not adapter.is_configured():
            raise ValueError("Kite not configured")

        token = _resolve_nse_token(sym)
        if token is None:
            raise ValueError(f"No token for {sym}")

        from_dt = date.today() - timedelta(days=days)
        interval = _TF_KITE[timeframe]
        df = adapter.get_historical(token, from_dt, date.today(), interval)
        if df.empty or len(df) < 30:
            raise ValueError("Empty data")

        if timeframe == "4h":
            agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            if "oi" in df.columns:
                agg["oi"] = "last"
            df = df.set_index("timestamp").resample("4h").agg(agg).dropna().reset_index()

        if "oi" not in df.columns:
            df["oi"] = 0.0
        if "iv" not in df.columns:
            rng = np.random.default_rng(abs(hash(sym)) % (2**31))
            df["iv"] = np.round(rng.uniform(12, 28, len(df)), 2)

        return df, "real"

    except Exception as e:
        logger.debug(f"Kite historical unavailable for {sym}/{timeframe}: {e} — using synthetic")
        from app.core.scanner import synthetic_ohlcv
        return synthetic_ohlcv(sym, timeframe), "synthetic"


def has_edge(win_rate: float | None, profit_factor: float | None, min_trades: int = 10, trades: int = 0) -> bool:
    """Return True if the pattern has statistically meaningful edge."""
    if trades < min_trades:
        return False
    return (win_rate or 0) >= 0.52 and (profit_factor or 0) >= 1.3
