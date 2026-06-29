"""Pattern: Mean Reversion via Bollinger Band Squeeze."""
import pandas as pd
import numpy as np
from app.core.patterns.base import AbstractPattern, PatternSignal


class MeanReversionPattern(AbstractPattern):
    name = "mean_reversion"
    version = "1.0"
    description = "Bollinger Band squeeze signals volatility breakout; OI confirms direction"
    min_data_rows = 50

    SQUEEZE_PERCENTILE = 20  # BB width in bottom 20% of last 30 days = squeeze

    def detect(self, ohlcv: pd.DataFrame, options_chain=None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if not self.validate_data(ohlcv):
            return signals

        df = ohlcv.copy()
        sma20 = df["close"].rolling(20).mean()
        std20 = df["close"].rolling(20).std()
        bb_width = (2 * std20 / sma20)  # normalized band width

        current_width = bb_width.iloc[-1]
        historical_widths = bb_width.dropna().iloc[-30:]
        if len(historical_widths) < 20:
            return signals

        threshold = historical_widths.quantile(self.SQUEEZE_PERCENTILE / 100)
        if current_width > threshold:
            return signals  # not in a squeeze

        # Detect direction from OI if available
        oi_direction = None
        if "oi" in df.columns:
            oi_chg = df["oi"].diff().iloc[-1]
            price_chg = df["close"].diff().iloc[-1]
            if oi_chg > 0 and price_chg > 0:
                oi_direction = "long"
            elif oi_chg > 0 and price_chg < 0:
                oi_direction = "short"

        entry = df["close"].iloc[-1]
        atr = self._atr(df)
        midband = sma20.iloc[-1]

        if oi_direction == "long":
            target = entry + 2 * current_width * entry
            stop = midband
            direction = "long"
        elif oi_direction == "short":
            target = entry - 2 * current_width * entry
            stop = midband
            direction = "short"
        else:
            return signals  # need OI confirmation for direction

        exp_ret = abs(target - entry) / entry * 100

        signals.append(PatternSignal(
            pattern_name=self.name, pattern_version=self.version,
            symbol=underlying, underlying=underlying,
            instrument=f"{underlying}_FUT",
            direction=direction, entry_price=entry, target_price=target, stop_loss=stop,
            expected_return_pct=round(exp_ret, 2),
            confidence_score=self._regime_adj(0.68, context),
            explanation=self._explain(underlying, current_width, threshold, direction),
            trading_style="positional",
            metadata={"bb_width": round(current_width, 4), "squeeze_threshold": round(threshold, 4)},
        ))
        return signals

    def _regime_adj(self, score: float, context: dict) -> float:
        iv_rank = context.get("iv_rank", None)
        regime = context.get("regime", {})
        suitable = regime.get("suitable_patterns", [])
        # mean_reversion benefits from low IV (potential to buy options cheap)
        if iv_rank is not None and iv_rank < 0.3:
            score = min(1.0, score * 1.1)
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

    def _explain(self, underlying, width, threshold, direction):
        return (
            f"BB Squeeze Breakout — {underlying} Bollinger Band width ({width:.4f}) is in the bottom "
            f"{self.SQUEEZE_PERCENTILE}th percentile of the last 30 days (threshold: {threshold:.4f}). "
            f"This tight consolidation precedes a volatility expansion. OI confirms {direction} direction. "
            f"Target: 2x the band width from entry. Stop: midband (SMA-20). "
            f"Hold for 2–4 sessions as volatility expands."
        )

    def why_it_works(self) -> str:
        return (
            "Mean Reversion / BB Squeeze works because volatility is mean-reverting. "
            "Extended periods of low volatility (the squeeze) always resolve with expansion. "
            "Option market makers price this into their models — when realized volatility drops well below "
            "implied volatility for extended periods, IV eventually compresses, then explosively re-expands. "
            "The OI filter adds directional edge to what would otherwise be a symmetric setup."
        )
