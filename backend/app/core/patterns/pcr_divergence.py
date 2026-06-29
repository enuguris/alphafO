"""Pattern: Put-Call Ratio Divergence"""
import pandas as pd
import numpy as np
from app.core.patterns.base import AbstractPattern, PatternSignal


class PCRDivergencePattern(AbstractPattern):
    name = "pcr_divergence"
    version = "1.0"
    description = "Detects extreme PCR readings that diverge from price action, signalling reversal"
    min_data_rows = 20

    PCR_BULLISH_THRESHOLD = 1.3   # PCR above this = too many puts = bullish contrarian
    PCR_BEARISH_THRESHOLD = 0.7   # PCR below this = too many calls = bearish contrarian
    PRICE_DIVERGENCE_PCT = 0.5    # price must have moved at least 0.5% in opposite direction

    def detect(self, ohlcv: pd.DataFrame, options_chain: pd.DataFrame | None = None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if not self.validate_data(ohlcv) or options_chain is None or options_chain.empty:
            return signals

        # Aggregate PCR from options chain
        chain = options_chain.copy()
        total_ce_oi = chain["ce_oi"].sum()
        total_pe_oi = chain["pe_oi"].sum()
        if total_ce_oi == 0:
            return signals
        pcr = total_pe_oi / total_ce_oi

        current_close = ohlcv["close"].iloc[-1]
        prev_close = ohlcv["close"].iloc[-2]
        price_chg_pct = (current_close - prev_close) / prev_close * 100

        # Bullish signal: PCR high + price falling
        if pcr >= self.PCR_BULLISH_THRESHOLD and price_chg_pct <= -self.PRICE_DIVERGENCE_PCT:
            confidence = min(1.0, (pcr - self.PCR_BULLISH_THRESHOLD) / 0.5 + 0.6)
            atr = self._atr(ohlcv)
            entry = current_close
            stop = entry - 1.5 * atr
            target = entry + 3.0 * atr
            signals.append(PatternSignal(
                pattern_name=self.name,
                pattern_version=self.version,
                symbol=underlying,
                underlying=underlying,
                instrument=f"{underlying}_FUT",
                direction="long",
                entry_price=entry,
                target_price=target,
                stop_loss=stop,
                expected_return_pct=round((target - entry) / entry * 100, 2),
                confidence_score=round(self._regime_adj(confidence, context), 2),
                explanation=self._explain_bullish(pcr, price_chg_pct),
                trading_style="intraday",
                metadata={"pcr": round(pcr, 2), "price_chg_pct": round(price_chg_pct, 2)},
            ))

        # Bearish signal: PCR low + price rising
        elif pcr <= self.PCR_BEARISH_THRESHOLD and price_chg_pct >= self.PRICE_DIVERGENCE_PCT:
            confidence = min(1.0, (self.PCR_BEARISH_THRESHOLD - pcr) / 0.3 + 0.6)
            atr = self._atr(ohlcv)
            entry = current_close
            stop = entry + 1.5 * atr
            target = entry - 3.0 * atr
            signals.append(PatternSignal(
                pattern_name=self.name,
                pattern_version=self.version,
                symbol=underlying,
                underlying=underlying,
                instrument=f"{underlying}_FUT",
                direction="short",
                entry_price=entry,
                target_price=target,
                stop_loss=stop,
                expected_return_pct=round((entry - target) / entry * 100, 2),
                confidence_score=round(self._regime_adj(confidence, context), 2),
                explanation=self._explain_bearish(pcr, price_chg_pct),
                trading_style="intraday",
                metadata={"pcr": round(pcr, 2), "price_chg_pct": round(price_chg_pct, 2)},
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

    def _atr(self, ohlcv: pd.DataFrame, period: int = 14) -> float:
        high = ohlcv["high"]
        low = ohlcv["low"]
        close = ohlcv["close"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]

    def _explain_bullish(self, pcr: float, price_chg: float) -> str:
        return (
            f"PCR Divergence — Bullish Reversal Signal. "
            f"Current PCR is {pcr:.2f} (above threshold of {self.PCR_BULLISH_THRESHOLD}), indicating extreme put-buying. "
            f"Price has fallen {abs(price_chg):.1f}% but sentiment is too fearful. "
            f"Market makers who sold these puts are now heavily delta-hedged short — as price stabilises, "
            f"they will mechanically buy back the underlying, creating a reversal squeeze. "
            f"Target: 3–4% upside. Stop: 1.5× ATR below entry."
        )

    def _explain_bearish(self, pcr: float, price_chg: float) -> str:
        return (
            f"PCR Divergence — Bearish Reversal Signal. "
            f"Current PCR is {pcr:.2f} (below threshold of {self.PCR_BEARISH_THRESHOLD}), indicating extreme call-buying (complacency). "
            f"Price has risen {price_chg:.1f}% but too many retail traders are piling into calls. "
            f"Dealer hedging dynamics favour a pullback as call writers delta-hedge by selling the underlying. "
            f"Target: 3–4% downside. Stop: 1.5× ATR above entry."
        )

    def why_it_works(self) -> str:
        return (
            "PCR Divergence works because it captures sentiment extremes driven by hedging mechanics. "
            "When PCR is very high, institutional option writers who are net short puts must buy the underlying "
            "as a delta hedge. This buying accelerates when price rises, creating a structural short squeeze. "
            "The edge comes not from predicting direction but from reading the forced flow of dealer hedging."
        )
