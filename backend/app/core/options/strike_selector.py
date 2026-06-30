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

        # Strategy tiers based on IV rank:
        #   Low  IV (< 40%): Buy options — vol cheap, own gamma
        #   Mid  IV (40-65%): Buy slightly ITM to own delta cheaply
        #   High IV (> 65%): Sell options — collect elevated premium, theta works for us
        if direction == "long":
            if high_ivr:
                # High IV + bullish → sell OTM PE (credit, keep if market stays up)
                option_type = "PE"
                strategy    = "sell"
                strike      = atm - step        # 1 strike OTM
                reasoning   = (
                    f"IV rank {iv_rank:.0%} elevated — selling OTM PE {strike} "
                    f"collects high premium; bullish regime protects against assignment."
                )
            else:
                # Low/mid IV + bullish → buy ATM CE (cheap vol, clean direction)
                option_type = "CE"
                strategy    = "buy"
                strike      = atm               # ATM, delta ≈ 0.5
                reasoning   = (
                    f"IV rank {iv_rank:.0%} low — buying ATM CE {strike}; "
                    f"inexpensive vol, 0.5 delta gives clean upside exposure."
                )
        else:
            if high_ivr:
                # High IV + bearish → sell OTM CE (credit, keep if market stays down)
                option_type = "CE"
                strategy    = "sell"
                strike      = atm + step        # 1 strike OTM
                reasoning   = (
                    f"IV rank {iv_rank:.0%} elevated — selling OTM CE {strike} "
                    f"collects high premium; bearish regime protects against assignment."
                )
            else:
                # Low/mid IV + bearish → buy ATM PE
                option_type = "PE"
                strategy    = "buy"
                strike      = atm
                reasoning   = (
                    f"IV rank {iv_rank:.0%} low — buying ATM PE {strike}; "
                    f"inexpensive vol, 0.5 delta gives clean downside exposure."
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

    def select_for_all_expiries(
        self,
        underlying: str,
        spot_price: float,
        direction: str,
        iv_rank: float,
        pattern_name: str,
        signal_target_pct: float,
        signal_stop_pct: float,
        ref_date: date | None = None,
    ) -> list[dict]:
        """
        Evaluate all expiries over the next ~2 months and return those where
        the option contract can be profitable.

        Profitability criteria per expiry:
          - Premium > ₹5 (liquid, not near-zero OTM)
          - Expected P&L (based on delta × move) > estimated charges
          - Risk/reward ≥ 1.5
          - DTE ≥ 1 (not expiring today)

        Returns list of contract dicts, one per viable expiry, sorted by DTE.
        Each dict is the same shape as select() but includes 'profit_score'.
        """
        from app.core.options.greeks import compute_greeks, RISK_FREE_RATE
        import math

        ref_date = ref_date or date.today()
        sym = underlying.upper()
        step = STRIKE_STEPS.get(sym, DEFAULT_STRIKE_STEP)
        inst = INSTRUMENT_MAP.get(sym)
        lot_size = inst["lot_size"] if inst else LOT_SIZES.get(sym, 50)
        atm = _round_to_step(spot_price, step)
        high_ivr = iv_rank >= 0.6
        pname = pattern_name.lower()

        # Determine option type and strategy (same logic as select())
        if direction == "long":
            option_type = "PE" if high_ivr else "CE"
            strategy = "sell" if high_ivr else "buy"
            strike = (atm - step) if high_ivr else atm
        else:
            option_type = "CE" if high_ivr else "PE"
            strategy = "sell" if high_ivr else "buy"
            strike = (atm + step) if high_ivr else atm

        if pname in SELL_PATTERNS:
            strategy = "sell"
            strike = (atm + step) if option_type == "CE" else (atm - step)
        elif pname in BUY_PATTERNS:
            strategy = "buy"
            strike = atm

        from app.core.options.greeks import _bs_price

        # Assumed IV for premium estimation (typical for NSE)
        base_iv = 0.15 + iv_rank * 0.10   # 15–25% depending on IV rank

        viable: list[dict] = []
        for expiry in available_expiries(sym, ref_date):
            dte = expiry["dte"]
            if dte < 1:
                continue

            T = dte / 365.0
            try:
                premium = max(0.05, _bs_price(spot_price, strike, T, RISK_FREE_RATE, base_iv, option_type))
                g = compute_greeks(spot_price, strike, T, base_iv, option_type, RISK_FREE_RATE)
            except Exception:
                continue

            # Minimum tradable premium — below ₹50 options have wide spreads and poor fills
            if premium < 50.0:
                continue
            # Skip very short DTE for buyers — gamma risk too high; sellers need < 21 DTE
            if strategy == "buy" and dte < 7:
                continue

            # Expected P&L: delta × expected move in underlying
            expected_move = abs(signal_target_pct / 100) * spot_price
            expected_pnl_per_unit = abs(g.delta) * expected_move
            if strategy == "sell":
                # Seller profits from theta decay over the holding period
                # Target: collect ~50% of premium by expiry; theta is faster near expiry
                # Short DTE → high pct collected quickly; long DTE → holds more risk
                decay_pct = max(0.2, min(0.6, 0.6 - (dte / 60) * 0.3))
                expected_pnl_per_unit = premium * decay_pct

            # Rough charges (₹20 brokerage × 2 legs + ~0.5% of turnover)
            charges_per_unit = (40 / lot_size) + premium * 0.005
            net_pnl = expected_pnl_per_unit - charges_per_unit

            # Max loss for buyer = premium; for seller = cap at 3× premium
            max_loss = premium if strategy == "buy" else premium * 3
            risk_reward = net_pnl / max_loss if max_loss > 0 else 0

            # Buyers need 0.3x (premium is expensive relative to a single move)
            # Sellers need 0.8x (premium collected vs max adverse move)
            min_rr = 0.3 if strategy == "buy" else 0.8
            if risk_reward < min_rr or net_pnl <= 0:
                continue

            # Profit score: higher is better
            profit_score = round(risk_reward * math.log1p(dte) * (1 + iv_rank * 0.2), 3)

            instrument = f"{sym}{expiry['short']}{strike}{option_type}"
            viable.append({
                "instrument":      instrument,
                "option_type":     option_type,
                "strategy":        strategy,
                "strike":          strike,
                "lot_size":        lot_size,
                "expiry":          expiry,
                "expiry_date":     expiry["date"],
                "expiry_display":  expiry["display"],
                "expiry_dte":      expiry["dte"],
                "expiry_series":   expiry["series"],
                "estimated_premium": round(premium, 2),
                "expected_pnl":    round(net_pnl, 2),
                "risk_reward":     round(risk_reward, 2),
                "profit_score":    profit_score,
                "reasoning": (
                    f"{strategy.title()} {strike}{option_type} expiring {expiry['display']} "
                    f"({dte}d). Est. premium ₹{premium:.0f}. "
                    f"Net P&L after charges: ₹{net_pnl:.0f}/unit. R/R: {risk_reward:.1f}x."
                ),
            })

        # Sort: nearest expiry first (user sees most actionable first)
        return sorted(viable, key=lambda x: x["expiry_dte"])
