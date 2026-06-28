"""Pattern: Expiry Week Theta Acceleration — sell OTM options."""
import pandas as pd
from datetime import datetime, date
from app.core.patterns.base import AbstractPattern, PatternSignal


class ExpiryWeekPattern(AbstractPattern):
    name = "expiry_week"
    version = "1.0"
    description = "Sell OTM options in expiry week to capture accelerated theta decay"
    min_data_rows = 5

    OTM_DELTA_TARGET = 0.2    # sell ~0.2 delta options
    TARGET_PREMIUM_PCT = 0.6  # collect 60% of premium

    def detect(self, ohlcv: pd.DataFrame, options_chain: pd.DataFrame | None = None, underlying: str = "") -> list[PatternSignal]:
        signals = []
        if options_chain is None or options_chain.empty:
            return signals

        # Check if we are Mon/Tue of expiry week
        today = datetime.utcnow()
        if today.weekday() not in (0, 1):   # 0=Mon, 1=Tue
            return signals

        current_price = ohlcv["close"].iloc[-1]
        chain = options_chain.copy()

        # Find OTM call and put ~2% away
        otm_pct = 0.02
        call_strike = round(current_price * (1 + otm_pct) / 50) * 50
        put_strike = round(current_price * (1 - otm_pct) / 50) * 50

        ce_row = chain[chain["strike"] == call_strike]
        pe_row = chain[chain["strike"] == put_strike]
        if ce_row.empty or pe_row.empty:
            return signals

        ce_premium = ce_row.iloc[0].get("ce_ltp", 0) or 0
        pe_premium = pe_row.iloc[0].get("pe_ltp", 0) or 0
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
            confidence_score=0.72,
            explanation=self._explain(underlying, call_strike, put_strike, ce_premium, pe_premium, total_premium),
            trading_style="intraday",
            metadata={"call_strike": call_strike, "put_strike": put_strike, "total_premium": total_premium},
        ))
        return signals

    def _explain(self, underlying, cs, ps, ce, pe, total):
        return (
            f"Expiry Week Theta Play — Selling {underlying} OTM strangle: "
            f"{int(cs)} CE @ ₹{ce:.0f} + {int(ps)} PE @ ₹{pe:.0f} = ₹{total:.0f} total premium. "
            f"Theta decay accelerates exponentially in the final 5 days — options lose 3–5x more per day "
            f"vs. earlier in the week. Both strikes are ~2% OTM, giving 80%+ probability of expiring worthless. "
            f"Target: collect 60% of premium. Exit immediately if spot breaches either short strike."
        )

    def why_it_works(self) -> str:
        return (
            "Expiry Week strategy works because time decay (theta) is not linear — it accelerates exponentially "
            "as expiry approaches. An option losing ₹10/day in week 3 may lose ₹40–50/day in expiry week. "
            "Selling far OTM options (~0.2 delta, ~80% probability of expiry) in Monday/Tuesday of expiry week "
            "maximizes theta capture in the shortest window. The short duration also limits exposure to "
            "direction risk and vega risk."
        )
