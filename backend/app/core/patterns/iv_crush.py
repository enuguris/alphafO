"""Pattern: IV Crush — sell premium before events, buy back after."""
import pandas as pd
from datetime import datetime, timedelta
from app.core.patterns.base import AbstractPattern, PatternSignal


class IVCrushPattern(AbstractPattern):
    name = "iv_crush"
    version = "1.0"
    description = "Sell options straddle before known events to capture IV crush"
    min_data_rows = 10

    IV_ELEVATION_THRESHOLD = 1.3   # IV must be 30% above 20-day average
    DAYS_BEFORE_EVENT = 5

    def detect(self, ohlcv: pd.DataFrame, options_chain: pd.DataFrame | None = None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if options_chain is None or options_chain.empty or "iv" not in ohlcv.columns:
            return signals

        current_iv = ohlcv["iv"].iloc[-1]
        avg_iv = ohlcv["iv"].rolling(20).mean().iloc[-1]
        if pd.isna(avg_iv) or avg_iv == 0:
            return signals

        iv_ratio = current_iv / avg_iv
        if iv_ratio < self.IV_ELEVATION_THRESHOLD:
            return signals

        # Use ATM strike for straddle
        current_price = ohlcv["close"].iloc[-1]
        chain = options_chain.copy()
        chain["dist"] = (chain["strike"] - current_price).abs()
        atm = chain.nsmallest(1, "dist").iloc[0]
        atm_strike = atm["strike"]
        ce_premium = atm.get("ce_ltp", 0) or 0
        pe_premium = atm.get("pe_ltp", 0) or 0
        total_premium = ce_premium + pe_premium

        if total_premium == 0:
            return signals

        target_premium = total_premium * 0.45   # collect 45% of premium
        breakeven_up = atm_strike + total_premium
        breakeven_down = atm_strike - total_premium

        signals.append(PatternSignal(
            pattern_name=self.name, pattern_version=self.version,
            symbol=underlying, underlying=underlying,
            instrument=f"{underlying}_{int(atm_strike)}_STRADDLE",
            direction="short",
            entry_price=total_premium,
            target_price=target_premium,
            stop_loss=total_premium * 1.5,   # exit if premium doubles
            expected_return_pct=round((total_premium - target_premium) / current_price * 100, 2),
            confidence_score=self._regime_adj(min(1.0, 0.5 + (iv_ratio - 1.3) * 0.5), context),
            explanation=self._explain(underlying, current_iv, avg_iv, iv_ratio, atm_strike, total_premium, breakeven_up, breakeven_down),
            trading_style="positional",
            metadata={"iv_ratio": round(iv_ratio, 2), "atm_strike": atm_strike, "total_premium": total_premium},
        ))
        return signals

    def _regime_adj(self, score: float, context: dict) -> float:
        iv_rank = context.get("iv_rank", None)
        regime = context.get("regime", {})
        suitable = regime.get("suitable_patterns", [])
        # iv_crush benefits from high IV rank
        if iv_rank is not None and iv_rank > 0.7:
            score = min(1.0, score * 1.1)
        if suitable:
            if self.name in suitable:
                return min(1.0, score * 1.2)
            return score * 0.85
        return score

    def _explain(self, underlying, curr_iv, avg_iv, ratio, strike, premium, be_up, be_dn):
        return (
            f"IV Crush Setup — {underlying} IV is {curr_iv:.1f}% vs 20-day avg of {avg_iv:.1f}% ({ratio:.1f}x elevated). "
            f"Selling ATM straddle at strike {strike:.0f} collects ₹{premium:.0f} total premium. "
            f"Breakeven range: {be_dn:.0f} – {be_up:.0f}. "
            f"After the event, IV typically collapses 30–50% regardless of direction. "
            f"Target: collect 45% of premium as IV decays. Exit if premium exceeds 1.5x entry (risk control)."
        )

    def why_it_works(self) -> str:
        return (
            "IV Crush works because implied volatility systematically overprices uncertainty before scheduled events. "
            "Retail traders and institutions buy options as hedges before known events (budget, RBI policy, earnings), "
            "driving IV higher than what realized volatility will be. After the event, regardless of the outcome, "
            "uncertainty resolves and IV collapses — sometimes 40–60% in one day. "
            "Selling options before events and buying them back after captures this structural overpricing."
        )
