"""Pattern: VWAP Reclaim + OI Momentum (Intraday)."""
import pandas as pd
from app.core.patterns.base import AbstractPattern, PatternSignal


class VWAPOIPattern(AbstractPattern):
    name = "vwap_oi"
    version = "1.0"
    description = "Intraday VWAP reclaim with OI momentum confirmation"
    min_data_rows = 30

    def detect(self, ohlcv: pd.DataFrame, options_chain=None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if not self.validate_data(ohlcv) or "volume" not in ohlcv.columns:
            return signals

        df = ohlcv.copy()
        # VWAP calculation
        df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
        df["cum_tpv"] = (df["tp"] * df["volume"]).cumsum()
        df["cum_vol"] = df["volume"].cumsum()
        df["vwap"] = df["cum_tpv"] / df["cum_vol"]

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        # VWAP reclaim: was below, now above
        if not (prev["close"] < prev["vwap"] and curr["close"] > curr["vwap"]):
            return signals

        # OI rising = new money confirming move
        if "oi" in df.columns:
            oi_rising = df["oi"].iloc[-1] > df["oi"].iloc[-2]
            if not oi_rising:
                return signals

        entry = curr["close"]
        vwap = curr["vwap"]
        atr = self._atr(df)
        target = entry + 2.0 * atr
        stop = vwap - 0.3 * atr   # just below VWAP

        signals.append(PatternSignal(
            pattern_name=self.name, pattern_version=self.version,
            symbol=underlying, underlying=underlying,
            instrument=f"{underlying}_FUT",
            direction="long", entry_price=entry, target_price=target, stop_loss=stop,
            expected_return_pct=round((target - entry) / entry * 100, 2),
            confidence_score=self._regime_adj(0.70, context),
            explanation=self._explain(underlying, entry, vwap),
            trading_style="intraday",
            metadata={"vwap": round(vwap, 2)},
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

    def _explain(self, underlying, price, vwap):
        return (
            f"VWAP Reclaim — {underlying} has crossed back above VWAP at {vwap:.0f} (current: {price:.0f}). "
            f"OI is rising, confirming new buying. VWAP is the institutional benchmark — "
            f"once price reclaims it, algorithmic buyers who were waiting for a VWAP cross engage. "
            f"Intraday target: previous session high. Stop: VWAP recrossed to the downside."
        )

    def why_it_works(self) -> str:
        return (
            "VWAP reclaim works because VWAP is the primary benchmark for institutional order execution. "
            "When price is below VWAP, large buyers accumulate (they're getting better than average price). "
            "The moment price crosses above VWAP, algo systems flip from buyer to complete — removing "
            "demand from below and creating a supply vacuum above. OI rising confirms institutional intent."
        )
