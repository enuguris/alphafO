"""Strike selector — picks the right option contract given a signal."""
from datetime import date
from app.core.instruments import INSTRUMENT_MAP, LOT_SIZES
from app.core.options.expiry import select_expiry, available_expiries


# Strike step sizes per underlying
STRIKE_STEPS = {
    "NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50,
    "MIDCPNIFTY": 25, "SENSEX": 100,
}
DEFAULT_STRIKE_STEP = 50

# Patterns that prefer premium selling vs directional buying
BUY_PATTERNS  = {"gap_fill", "oi_buildup", "expiry_week", "vwap_oi", "pcr_divergence"}
SELL_PATTERNS = {"iv_crush", "mean_reversion", "max_pain"}


def _round_to_step(price: float, step: int) -> int:
    return int(round(price / step) * step)


class StrikeSelector:
    """Select option contract based on signal parameters."""

    def select(
        self,
        underlying: str,
        spot_price: float,
        direction: str,
        iv_rank: float,
        dte_preference: int,
        pattern_name: str,
        ref_date: date | None = None,
    ) -> dict:
        """
        Returns full option contract details including exact expiry date.

        Args:
            underlying:    e.g. "NIFTY" or "TATAMOTORS"
            spot_price:    current spot price
            direction:     "long" | "short"
            iv_rank:       0.0 - 1.0
            dte_preference: minimum days to expiry desired
            pattern_name:  triggering pattern name
            ref_date:      reference date (defaults to today)

        Returns dict with:
            instrument, option_type, strategy, strike, lot_size,
            expiry (dict with date/display/dte/series), reasoning
        """
        ref_date = ref_date or date.today()
        sym = underlying.upper()

        step     = STRIKE_STEPS.get(sym, DEFAULT_STRIKE_STEP)
        inst     = INSTRUMENT_MAP.get(sym)
        lot_size = inst["lot_size"] if inst else LOT_SIZES.get(sym, 50)
        atm      = _round_to_step(spot_price, step)
        high_ivr = iv_rank >= 0.6
        pname    = pattern_name.lower()

        # Determine option_type and strategy
        if direction == "long":
            if high_ivr:
                option_type = "PE"
                strategy    = "sell"
                strike      = atm - step
                reasoning   = (
                    f"IV rank {iv_rank:.0%} is elevated — selling OTM PE {strike} "
                    f"captures high premium with bullish bias."
                )
            else:
                option_type = "CE"
                strategy    = "buy"
                strike      = atm
                reasoning   = (
                    f"IV rank {iv_rank:.0%} is low — buying ATM CE {strike} "
                    f"gives clean delta exposure at reasonable cost."
                )
        else:
            if high_ivr:
                option_type = "CE"
                strategy    = "sell"
                strike      = atm + step
                reasoning   = (
                    f"IV rank {iv_rank:.0%} is elevated — selling OTM CE {strike} "
                    f"captures high premium with bearish bias."
                )
            else:
                option_type = "PE"
                strategy    = "buy"
                strike      = atm
                reasoning   = (
                    f"IV rank {iv_rank:.0%} is low — buying ATM PE {strike} "
                    f"gives clean delta exposure at reasonable cost."
                )

        # Pattern override
        if pname in SELL_PATTERNS:
            strategy = "sell"
            strike   = (atm + step) if option_type == "CE" else (atm - step)
            reasoning += f" {pattern_name} pattern favours premium selling."
        elif pname in BUY_PATTERNS:
            strategy = "buy"
            strike   = atm
            reasoning += f" {pattern_name} pattern favours directional buys."

        # Expiry selection
        expiry = select_expiry(sym, dte_preference=dte_preference, from_date=ref_date)

        # NSE F&O symbol format: NIFTY26JUL2425000CE
        instrument = f"{sym}{expiry['short']}{strike}{option_type}"

        return {
            "instrument":     instrument,
            "option_type":    option_type,
            "strategy":       strategy,
            "strike":         strike,
            "lot_size":       lot_size,
            "expiry":         expiry,                # full dict
            "expiry_date":    expiry["date"],         # "2026-07-03"
            "expiry_display": expiry["display"],      # "03 Jul 2026 (Thu)"
            "expiry_dte":     expiry["dte"],          # 4
            "expiry_series":  expiry["series"],       # "weekly" | "monthly"
            "reasoning":      reasoning,
        }

    def all_expiries(self, underlying: str, ref_date: date | None = None) -> list[dict]:
        """Return all available expiry dates for an underlying."""
        return available_expiries(underlying, ref_date or date.today())
