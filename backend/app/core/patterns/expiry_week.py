"""Pattern: Expiry Week Theta Acceleration — sell OTM options."""
import pandas as pd
from datetime import datetime, date, timedelta
from app.core.patterns.base import AbstractPattern, PatternSignal


class ExpiryWeekPattern(AbstractPattern):
    name = "expiry_week"
    version = "1.0"
    description = "Sell OTM options in expiry week to capture accelerated theta decay"
    min_data_rows = 5

    OTM_DELTA_TARGET = 0.2    # sell ~0.2 delta options
    TARGET_PREMIUM_PCT = 0.6  # collect 60% of premium

    def detect(self, ohlcv: pd.DataFrame, options_chain: pd.DataFrame | None = None, underlying: str = "", context: dict = {}) -> list[PatternSignal]:
        signals = []
        if options_chain is None or options_chain.empty:
            return signals

        # Check if we are within 2 days BEFORE this underlying's expiry weekday (IST)
        from datetime import timezone, timedelta as _td
        from app.core.options.expiry import _expiry_weekday
        ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        exp_wd = _expiry_weekday(underlying)   # 1=Tue for NSE, 3=Thu for BSE/SENSEX
        today_wd = ist_now.weekday()
        # Fire on expiry day itself AND the trading day before
        # For Tuesday expiry: fire Mon + Tue
        # For Thursday expiry (SENSEX): fire Wed + Thu
        # Clamp to weekdays only (no Sunday = 6)
        prev_wd = (exp_wd - 1) % 7
        if prev_wd == 6:   # skip Sunday
            prev_wd = (exp_wd - 2) % 7
        fire_days = {prev_wd, exp_wd}
        if today_wd not in fire_days:
            return signals

        # Use chain ATM as anchor (chain is built from live spot, not OHLCV close)
        chain = options_chain.copy()
        if chain.empty:
            return signals
        from app.core.options.strike_selector import STRIKE_STEPS, DEFAULT_STRIKE_STEP
        step = STRIKE_STEPS.get(underlying.upper(), DEFAULT_STRIKE_STEP)
        # Infer spot from chain mid-strike
        chain_mid_idx = len(chain) // 2
        current_price = float(chain.iloc[chain_mid_idx]["strike"])

        otm_pct = 0.02
        call_strike = round(current_price * (1 + otm_pct) / step) * step
        put_strike = round(current_price * (1 - otm_pct) / step) * step

        # Find closest available strikes if exact ones are missing
        def closest_strike(target):
            row = chain.iloc[(chain["strike"] - target).abs().argsort()[:1]]
            return row.iloc[0] if not row.empty else None

        ce_data = closest_strike(call_strike)
        pe_data = closest_strike(put_strike)
        if ce_data is None or pe_data is None:
            return signals

        ce_premium = float(ce_data.get("ce_ltp", 0) or 0)
        pe_premium = float(pe_data.get("pe_ltp", 0) or 0)
        total_premium = ce_premium + pe_premium

        if total_premium < 10:  # too little premium
            return signals

        target = total_premium * (1 - self.TARGET_PREMIUM_PCT)

        signals.append(PatternSignal(
            pattern_name=self.name, pattern_version=self.version,
            symbol=underlying, underlying=underlying,
            instrument=f"{underlying}_{int(call_strike)}CE_{int(put_strike)}PE_STRANGLE",
            direction="short",
            entry_price=total_premium,
            target_price=target,
            stop_loss=total_premium * 1.5,
            expected_return_pct=round(total_premium * self.TARGET_PREMIUM_PCT / current_price * 100, 2),
            confidence_score=self._regime_adj(0.72, context),
            explanation=self._explain(underlying, call_strike, put_strike, ce_premium, pe_premium, total_premium),
            trading_style="intraday",
            metadata={"call_strike": call_strike, "put_strike": put_strike, "total_premium": total_premium},
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

    def _explain(self, underlying, cs, ps, ce, pe, total):
        return (
            f"Expiry week: sell {underlying} {int(cs)} CE (₹{ce:.0f}) + {int(ps)} PE (₹{pe:.0f}) = ₹{total:.0f} collected. "
            f"Both strikes are ~2% away — 80%+ chance they expire worthless. "
            f"Time decay is 3–5x faster this week than earlier in the month. Exit if spot breaches either strike."
        )

    def why_it_works(self) -> str:
        return (
            "Expiry Week strategy works because time decay (theta) is not linear — it accelerates exponentially "
            "as expiry approaches. An option losing ₹10/day in week 3 may lose ₹40–50/day in expiry week. "
            "Selling far OTM options (~0.2 delta, ~80% probability of expiry) in Monday/Tuesday of expiry week "
            "maximizes theta capture in the shortest window. The short duration also limits exposure to "
            "direction risk and vega risk."
        )
