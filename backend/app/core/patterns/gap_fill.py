"""Pattern: Statistical Gap Fill"""
import pandas as pd
from app.core.patterns.base import AbstractPattern, PatternSignal


class GapFillPattern(AbstractPattern):
    name = "gap_fill"
    version = "1.0"
    description = "Fade opening gaps that are not driven by fundamental news (65-75% fill rate)"
    min_data_rows = 10

    MIN_GAP_PCT = 0.8
    MAX_GAP_PCT = 2.5   # larger gaps may be news-driven

    def detect(self, ohlcv: pd.DataFrame, options_chain=None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if not self.validate_data(ohlcv):
            return signals

        prev_close = ohlcv["close"].iloc[-2]
        current_open = ohlcv["open"].iloc[-1]
        gap_pct = (current_open - prev_close) / prev_close * 100

        if abs(gap_pct) < self.MIN_GAP_PCT or abs(gap_pct) > self.MAX_GAP_PCT:
            return signals

        atr = self._atr(ohlcv)
        if gap_pct > 0:  # gap up — fade it (short)
            entry = current_open
            target = prev_close
            stop = current_open + 0.5 * atr
            direction = "short"
        else:            # gap down — fade it (long)
            entry = current_open
            target = prev_close
            stop = current_open - 0.5 * atr
            direction = "long"

        exp_return = abs(target - entry) / entry * 100

        signals.append(PatternSignal(
            pattern_name=self.name, pattern_version=self.version,
            symbol=underlying, underlying=underlying,
            instrument=underlying,
            direction=direction, entry_price=entry, target_price=target, stop_loss=stop,
            expected_return_pct=round(exp_return, 2),
            confidence_score=self._regime_adj(0.65, context),
            explanation=self._explain(underlying, gap_pct, prev_close, current_open, direction),
            trading_style="intraday",
            metadata={"gap_pct": round(gap_pct, 2), "prev_close": prev_close},
        ))
        return signals

    def _regime_adj(self, score: float, context: dict) -> float:
        regime = context.get("regime", {})
        suitable = regime.get("suitable_patterns", [])
        if suitable:
            if self.name in suitable:
                return min(1.0, score * 1.2)
            return score * 0.85
        return score

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift()).abs(),
                        (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]

    def _explain(self, underlying, gap_pct, prev_close, curr_open, direction):
        gap_dir = "up" if gap_pct > 0 else "down"
        action = "Sell" if direction == "short" else "Buy"
        return (
            f"{underlying} opened {abs(gap_pct):.1f}% {gap_dir} at ₹{curr_open:.0f} vs yesterday's close of ₹{prev_close:.0f}. "
            f"65–75% of gaps this size fill the same day. {action} the gap, target ₹{prev_close:.0f}. Exit by 3:20 PM if it doesn't fill."
        )

    def why_it_works(self) -> str:
        return (
            "Gap Fill works because overnight price gaps create a liquidity vacuum. "
            "Market makers and institutional traders need to fill large orders at fair value (near previous close). "
            "Their activity gradually brings price back to the gap area. "
            "Statistically, gaps under 2.5% without catalysing news fill 65–75% of the time on NSE indices."
        )
