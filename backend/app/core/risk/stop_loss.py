"""ATR-based and time-based stop loss calculators."""
import pandas as pd


def atr_stop(ohlcv: pd.DataFrame, entry_price: float, direction: str,
             atr_multiplier: float = 1.5, period: int = 14) -> float:
    """Calculate ATR-based stop loss."""
    high, low, close = ohlcv["high"], ohlcv["low"], ohlcv["close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]

    if direction == "long":
        return entry_price - (atr_multiplier * atr)
    return entry_price + (atr_multiplier * atr)


def trailing_stop(current_price: float, peak_price: float, direction: str,
                  trail_pct: float = 0.015) -> float:
    """Trailing stop: move stop up (long) or down (short) as trade profits."""
    if direction == "long":
        return peak_price * (1 - trail_pct)
    return peak_price * (1 + trail_pct)


def eod_exit_required(current_time: pd.Timestamp, style: str) -> bool:
    """Return True if position must be exited at EOD (intraday only)."""
    if style != "intraday":
        return False
    market_close = current_time.replace(hour=15, minute=25, second=0)
    return current_time >= market_close
