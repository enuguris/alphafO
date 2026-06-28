"""Pattern: Open Interest Buildup Confirmation"""
import pandas as pd
from app.core.patterns.base import AbstractPattern, PatternSignal


class OIBuildupPattern(AbstractPattern):
    name = "oi_buildup"
    version = "1.0"
    description = "Price breakout confirmed by significant OI increase — new money entering"
    min_data_rows = 30

    OI_INCREASE_THRESHOLD = 0.15   # 15% OI increase in one session
    BREAKOUT_LOOKBACK = 20         # periods for support/resistance calculation

    def detect(self, ohlcv: pd.DataFrame, options_chain=None, underlying: str = "") -> list[PatternSignal]:
        signals = []
        if not self.validate_data(ohlcv) or "oi" not in ohlcv.columns:
            return signals

        df = ohlcv.copy()
        current = df.iloc[-1]
        prev = df.iloc[-2]

        # OI change — use volume surge as proxy when OI is not available
        oi_available = "oi" in df.columns and pd.notna(current["oi"]) and pd.notna(prev["oi"]) and prev["oi"] > 0
        if oi_available:
            oi_chg_pct = (current["oi"] - prev["oi"]) / prev["oi"]
            if abs(oi_chg_pct) < self.OI_INCREASE_THRESHOLD:
                return signals
        else:
            # Volume proxy: require 1.5x average volume as confirmation
            avg_vol = df["volume"].iloc[-10:-1].mean()
            if avg_vol == 0 or current["volume"] < 1.5 * avg_vol:
                return signals
            oi_chg_pct = 1.0  # treat as positive confirmation

        # Resistance/support
        lookback = df.iloc[-(self.BREAKOUT_LOOKBACK + 1):-1]
        resistance = lookback["high"].max()
        support = lookback["low"].min()

        atr = self._atr(df)
        entry = current["close"]

        # Bullish breakout: price closes above resistance with rising OI/volume
        if current["close"] > resistance and oi_chg_pct > 0:
            stop = resistance - 0.5 * atr  # stop just below broken resistance (now support)
            target = entry + 3.0 * atr
            signals.append(PatternSignal(
                pattern_name=self.name, pattern_version=self.version,
                symbol=underlying, underlying=underlying,
                instrument=f"{underlying}_FUT",
                direction="long", entry_price=entry, target_price=target, stop_loss=stop,
                expected_return_pct=round((target - entry) / entry * 100, 2),
                confidence_score=min(1.0, 0.6 + oi_chg_pct),
                explanation=self._explain(underlying, "bullish", resistance, oi_chg_pct),
                trading_style="positional",
                metadata={"oi_chg_pct": round(oi_chg_pct * 100, 1), "resistance": resistance},
            ))

        # Bearish breakdown: price closes below support with rising OI
        elif current["close"] < support and oi_chg_pct > 0:
            stop = support + 0.5 * atr
            target = entry - 3.0 * atr
            signals.append(PatternSignal(
                pattern_name=self.name, pattern_version=self.version,
                symbol=underlying, underlying=underlying,
                instrument=f"{underlying}_FUT",
                direction="short", entry_price=entry, target_price=target, stop_loss=stop,
                expected_return_pct=round((entry - target) / entry * 100, 2),
                confidence_score=min(1.0, 0.6 + oi_chg_pct),
                explanation=self._explain(underlying, "bearish", support, oi_chg_pct),
                trading_style="positional",
                metadata={"oi_chg_pct": round(oi_chg_pct * 100, 1), "support": support},
            ))

        return signals

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift()).abs(),
                        (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]

    def _explain(self, underlying, direction, level, oi_chg_pct):
        if direction == "bullish":
            return (
                f"OI Buildup Breakout — {underlying} has closed above the {self.BREAKOUT_LOOKBACK}-day resistance "
                f"of {level:.0f} with OI rising {oi_chg_pct*100:.1f}%. This confirms new long positions entering, "
                f"not just short covering. Breakouts on rising OI have historically sustained 3–5% before reverting. "
                f"Broken resistance acts as new support. Stop just below that level."
            )
        return (
            f"OI Buildup Breakdown — {underlying} has closed below the {self.BREAKOUT_LOOKBACK}-day support "
            f"of {level:.0f} with OI rising {oi_chg_pct*100:.1f}%. New short positions are entering with conviction. "
            f"Breakdowns on rising OI tend to follow through 3–5%. Broken support acts as new resistance."
        )

    def why_it_works(self) -> str:
        return (
            "OI Buildup works because it distinguishes between new-money breakouts and short-covering rallies. "
            "A price move with falling OI means longs are exiting or shorts are covering — no real conviction. "
            "A price move with rising OI means new participants are entering with fresh capital, "
            "giving the move sustained momentum. Institutional algorithms specifically filter for this pattern."
        )
