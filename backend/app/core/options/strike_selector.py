"""Strike selector — picks the right option contract given a signal."""
from datetime import date, timedelta


# Lot sizes for common underlyings
LOT_SIZES = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 75,
}
DEFAULT_LOT_SIZE = 50

# Strike step sizes
STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
}
DEFAULT_STRIKE_STEP = 50

# Patterns that prefer buy strategies
BUY_PATTERNS = {"gap_fill", "oi_buildup", "expiry_week", "vwap_oi", "pcr_divergence"}
# Patterns that prefer sell strategies
SELL_PATTERNS = {"iv_crush", "mean_reversion", "max_pain"}


def _nearest_thursday(from_date: date) -> date:
    """Return next (or current) Thursday."""
    days_ahead = 3 - from_date.weekday()  # Thursday = 3
    if days_ahead < 0:
        days_ahead += 7
    return from_date + timedelta(days=days_ahead)


def _expiry_label(from_date: date) -> str:
    """Format expiry as e.g. '25JUL'."""
    exp = _nearest_thursday(from_date)
    return exp.strftime("%d%b").upper()


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
        dte: int,
        pattern_name: str,
    ) -> dict:
        """
        Select the best option contract for a given signal.

        Args:
            underlying: e.g. "NIFTY"
            spot_price: current spot price
            direction: "long" | "short"
            iv_rank: 0.0 to 1.0
            dte: days to expiry
            pattern_name: name of triggering pattern

        Returns:
            dict with instrument, option_type, strategy, strike, reasoning, lot_size
        """
        step = STRIKE_STEPS.get(underlying.upper(), DEFAULT_STRIKE_STEP)
        lot_size = LOT_SIZES.get(underlying.upper(), DEFAULT_LOT_SIZE)
        atm = _round_to_step(spot_price, step)
        high_ivr = iv_rank >= 0.6
        low_ivr = iv_rank <= 0.4

        pname = pattern_name.lower()

        # ── Determine option_type and strategy ────────────────────────────────
        if direction == "long":
            if high_ivr:
                # Sell PE (premium income, high IV is better for sellers)
                option_type = "PE"
                strategy = "sell"
                strike = atm - step  # OTM PE
                reasoning = (
                    f"IV rank {iv_rank:.0%} is high — selling OTM PE at {strike} "
                    f"captures elevated premium while maintaining bullish bias."
                )
            else:
                # Buy CE
                option_type = "CE"
                strategy = "buy"
                strike = atm  # ATM CE for maximum delta sensitivity
                reasoning = (
                    f"IV rank {iv_rank:.0%} is low — buying ATM CE at {strike} "
                    f"is cost-effective with good delta exposure."
                )
        else:  # direction == "short"
            if high_ivr:
                # Sell CE
                option_type = "CE"
                strategy = "sell"
                strike = atm + step  # OTM CE
                reasoning = (
                    f"IV rank {iv_rank:.0%} is high — selling OTM CE at {strike} "
                    f"captures elevated premium with bearish bias."
                )
            else:
                # Buy PE
                option_type = "PE"
                strategy = "buy"
                strike = atm  # ATM PE
                reasoning = (
                    f"IV rank {iv_rank:.0%} is low — buying ATM PE at {strike} "
                    f"is cost-effective with good delta exposure."
                )

        # ── Pattern override ──────────────────────────────────────────────────
        if pname in SELL_PATTERNS:
            strategy = "sell"
            if option_type == "CE":
                strike = atm + step
            else:
                strike = atm - step
            reasoning += f" {pattern_name} favours premium selling."
        elif pname in BUY_PATTERNS:
            strategy = "buy"
            strike = atm  # ATM for buys
            reasoning += f" {pattern_name} favours directional option buys."

        # ── Format expiry label ───────────────────────────────────────────────
        expiry_label = _expiry_label(date.today())
        instrument = f"{underlying.upper()}{expiry_label}{strike}{option_type}"

        return {
            "instrument": instrument,
            "option_type": option_type,
            "strategy": strategy,
            "strike": strike,
            "expiry_date_str": expiry_label,
            "lot_size": lot_size,
            "reasoning": reasoning,
        }
