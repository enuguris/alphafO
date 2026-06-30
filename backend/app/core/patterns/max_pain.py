"""Pattern: Max Pain Gravity (Expiry Week)"""
import pandas as pd
import numpy as np
from app.core.patterns.base import AbstractPattern, PatternSignal


class MaxPainPattern(AbstractPattern):
    name = "max_pain"
    version = "1.0"
    description = "Spot price gravitates toward Max Pain strike in expiry week"
    min_data_rows = 5

    DEVIATION_TRIGGER_PCT = 1.5   # trigger when spot deviates >1.5% from max pain

    def detect(self, ohlcv: pd.DataFrame, options_chain: pd.DataFrame | None = None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if options_chain is None or options_chain.empty or not self.validate_data(ohlcv):
            return signals

        max_pain_strike = self._calculate_max_pain(options_chain)
        if max_pain_strike is None:
            return signals

        current_price = ohlcv["close"].iloc[-1]
        deviation_pct = (current_price - max_pain_strike) / max_pain_strike * 100

        if abs(deviation_pct) < self.DEVIATION_TRIGGER_PCT:
            return signals

        atr = self._atr(ohlcv)
        direction = "short" if deviation_pct > 0 else "long"
        entry = current_price
        stop_dist = 0.8 * atr

        # Max pain is a gravitational pull — cap expected move at 5% to stay realistic
        # Never target more than 5% away; if max_pain is further, use 50% of the gap
        raw_gap_pct = abs(deviation_pct)
        if raw_gap_pct > 5.0:
            move_pct = min(raw_gap_pct * 0.5, 5.0)
            target = (entry * (1 - move_pct / 100)) if direction == "short" else (entry * (1 + move_pct / 100))
        else:
            target = max_pain_strike

        if direction == "long":
            stop = entry - stop_dist
        else:
            stop = entry + stop_dist

        exp_return = abs(target - entry) / entry * 100
        # Confidence: starts at 0.55, scales with deviation up to 0.80 max (never 1.0)
        raw_conf = min(0.80, 0.55 + abs(deviation_pct) / 20)

        signals.append(PatternSignal(
            pattern_name=self.name, pattern_version=self.version,
            symbol=underlying, underlying=underlying,
            instrument=underlying,
            direction=direction, entry_price=entry, target_price=round(target, 2), stop_loss=stop,
            expected_return_pct=round(exp_return, 2),
            confidence_score=self._regime_adj(raw_conf, context),
            explanation=self._explain(underlying, current_price, max_pain_strike, deviation_pct, direction),
            trading_style="intraday",
            metadata={"max_pain_strike": max_pain_strike, "deviation_pct": round(deviation_pct, 2)},
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

    def _calculate_max_pain(self, chain: pd.DataFrame) -> float | None:
        """Max pain = strike where total option premium expiring worthless is maximized."""
        strikes = sorted(chain["strike"].unique())
        if len(strikes) < 3:
            return None
        min_pain = None
        max_pain_strike = None
        for s in strikes:
            # Pain for call writers: sum of (strike - S)+ × CE_OI for all strikes below s
            call_pain = chain[chain["strike"] < s].apply(
                lambda r: max(0, s - r["strike"]) * r["ce_oi"], axis=1).sum()
            # Pain for put writers: sum of (S - strike)+ × PE_OI for all strikes above s
            put_pain = chain[chain["strike"] > s].apply(
                lambda r: max(0, r["strike"] - s) * r["pe_oi"], axis=1).sum()
            total = call_pain + put_pain
            if min_pain is None or total < min_pain:
                min_pain = total
                max_pain_strike = s
        return max_pain_strike

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift()).abs(),
                        (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]

    def _explain(self, underlying, price, mp, dev, direction):
        action = "Sell" if direction == "short" else "Buy"
        side = "above" if dev > 0 else "below"
        return (
            f"{underlying} at ₹{price:.0f} is {abs(dev):.1f}% {side} Max Pain (₹{mp:.0f}). "
            f"Option writers delta-hedge in a way that pulls price toward Max Pain near expiry. "
            f"{action} — target Max Pain level. Works best in the 48–72 hours before expiry."
        )

    def why_it_works(self) -> str:
        return (
            "Max Pain works because of delta hedging mechanics of large option writers. "
            "Option writers (typically institutions) are net short options and profit from premium decay. "
            "Their delta-hedging activity — buying when price falls, selling when price rises — "
            "acts as a gravitational pull toward the strike where total outstanding premium is minimized. "
            "This is not manipulation but a natural consequence of how large players manage their books."
        )
