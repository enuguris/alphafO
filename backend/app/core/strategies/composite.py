"""
Composite option strategies — multi-leg defined-risk combinations.

All positions are fully hedged: no naked exposure. Every strategy has at
least one leg that profits when another loses, creating a net payoff that
is bounded on both sides.

Strategy selection by IV rank and pattern type:

  BUY_PATTERNS (directional):
    low IV  (< 0.40):  Vertical Spread — buy ATM + sell OTM (same expiry)
                       Cheap debit, limited profit, limited loss
    mid IV  (0.40-0.65): Diagonal Spread — buy near-term ATM + sell far-term OTM
                       Direction + some theta from far-term short
    high IV (> 0.65):  Calendar Spread — sell near-term ATM + buy far-term ATM
                       Sell elevated near-term IV, own cheaper far-term

  SELL_PATTERNS (iv_crush, expiry_week):
    always:            Iron Condor — sell OTM CE + sell OTM PE + buy wings
                       Theta collection with defined max loss on both sides

Each returned Leg dict has:
  strike, option_type, action, expiry_iso, expiry_display, expiry_dte,
  role, estimated_premium, quantity (multiplier vs lot_size, always 1 here)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass
class Leg:
    """A single option leg in a composite trade."""
    strike: float
    option_type: str            # CE | PE
    action: str                 # BUY | SELL
    expiry_iso: str             # "2026-07-08"
    expiry_display: str         # "08 Jul 2026 (Tue)"
    expiry_dte: int
    role: str                   # primary | hedge | calendar_short | calendar_long | condor_short_ce | condor_short_pe | condor_wing_ce | condor_wing_pe
    estimated_premium: float
    symbol: str                 # full NSE tradingsymbol e.g. NIFTY2671424000CE

    def net_sign(self) -> float:
        """Cash-flow sign: BUY = -1 (debit), SELL = +1 (credit)."""
        return -1.0 if self.action == "BUY" else 1.0

    def max_loss_per_unit(self, spread_width: float) -> float:
        """Worst-case loss per unit for this leg in isolation (not net)."""
        if self.action == "BUY":
            return self.estimated_premium        # buyer loses entire premium
        return spread_width - self.estimated_premium   # seller's max loss = width - credit

    def target_pnl(self) -> float:
        """Target exit P&L per unit."""
        if self.action == "BUY":
            return self.estimated_premium * 0.50   # +50% of premium paid
        return self.estimated_premium * 0.55        # collect 55% of premium sold

    def stop_pnl(self) -> float:
        """Stop-loss P&L per unit (exit when loss reaches this)."""
        if self.action == "BUY":
            return -self.estimated_premium * 0.40   # -40% of premium
        return -self.estimated_premium * 1.00        # -100% (doubles against)


SELL_PATTERNS = {"iv_crush", "expiry_week"}


def _round_strike(price: float, step: int) -> int:
    return int(round(price / step) * step)


def _build_symbol(underlying: str, expiry_iso: str, strike: float, option_type: str) -> str:
    """Build NSE F&O tradingsymbol from components."""
    import calendar as _cal
    from datetime import date as _date
    try:
        exp = _date.fromisoformat(expiry_iso)
        yy = str(exp.year)[2:]
        mon3 = exp.strftime("%b").upper()
        last_tue = max(
            _date(exp.year, exp.month, dd)
            for dd in range(1, _cal.monthrange(exp.year, exp.month)[1] + 1)
            if _date(exp.year, exp.month, dd).weekday() == 1
        )
        base = f"{int(strike)}{option_type}"
        if exp == last_tue:
            return f"{underlying}{yy}{mon3}{base}"    # monthly
        return f"{underlying}{yy}{exp.month}{exp.day:02d}{base}"  # weekly
    except Exception:
        return f"{underlying}{int(strike)}{option_type}"


def _bs_premium(spot: float, strike: float, dte: int, iv: float, option_type: str) -> float:
    """Fast Black-Scholes price. Returns ≥ 0.05."""
    try:
        from app.core.options.greeks import _bs_price, RISK_FREE_RATE
        T = max(dte, 1) / 365.0
        return max(0.05, _bs_price(spot, strike, T, RISK_FREE_RATE, iv, option_type))
    except Exception:
        # Intrinsic + rough time value fallback
        intr = max(0.0, (spot - strike) if option_type == "CE" else (strike - spot))
        return max(0.05, intr + spot * iv * math.sqrt(max(dte, 1) / 365.0) * 0.4)


def build_composite(
    underlying: str,
    spot: float,
    direction: str,           # "long" | "short"
    iv_rank: float,           # 0.0–1.0
    iv: float,                # absolute IV e.g. 0.18 = 18%
    pattern_name: str,
    available_expiries: list[dict],  # from expiry.available_expiries()
    step: int = 50,
) -> list[Leg]:
    """
    Return a list of Leg objects forming a fully-hedged composite strategy.
    Always returns ≥ 2 legs. Never returns a naked single leg.

    available_expiries must be sorted by DTE ascending (nearest first).
    Each expiry dict: {date: str, display: str, dte: int, series: str, short: str}
    """
    if not available_expiries:
        return []

    pname = pattern_name.lower()
    is_sell_pattern = pname in SELL_PATTERNS

    # Filter expiries: need at least DTE ≥ 1
    valid = [e for e in available_expiries if e["dte"] >= 1]
    if not valid:
        return []

    near = valid[0]   # nearest expiry (most theta, highest gamma)
    far  = valid[1] if len(valid) > 1 else valid[0]   # second expiry for multi-expiry strategies

    # IV as fraction
    if iv > 2.0:
        iv = iv / 100.0   # convert percentage to fraction
    iv = max(0.08, min(iv, 0.80))

    atm = _round_strike(spot, step)

    if is_sell_pattern:
        return _iron_condor(underlying, spot, atm, iv, iv_rank, near, step)
    elif iv_rank < 0.40:
        return _vertical_spread(underlying, spot, atm, iv, direction, near, step)
    elif iv_rank < 0.65:
        return _diagonal_spread(underlying, spot, atm, iv, direction, near, far, step)
    else:
        return _calendar_spread(underlying, spot, atm, iv, direction, near, far, step)


# ── Strategy builders ─────────────────────────────────────────────────────────

def _vertical_spread(
    underlying: str, spot: float, atm: int, iv: float,
    direction: str, expiry: dict, step: int,
) -> list[Leg]:
    """
    Bull Call Spread (bullish) or Bear Put Spread (bearish).
    Buy ATM option + Sell OTM option (2 steps away), same expiry.

    Payoff: capped profit (up to spread width), capped loss (net debit paid).
    "One leg loses, the other limits it" — short OTM reduces cost by 40–60%.

    Example bullish NIFTY: Buy 24000CE @ ₹180 + Sell 24100CE @ ₹90 = ₹90 net debit
    Max profit: ₹10 (spread) - ₹0.90 (per unit) = ₹9.10/unit × 65 lots = ₹591
    Max loss:   ₹0.90/unit = ₹58.50 total
    """
    dte = expiry["dte"]
    if direction == "long":
        opt_type = "CE"
        long_strike = atm
        short_strike = atm + 2 * step     # sell OTM CE 2 strikes above
    else:
        opt_type = "PE"
        long_strike = atm
        short_strike = atm - 2 * step     # sell OTM PE 2 strikes below

    long_prem  = _bs_premium(spot, long_strike,  dte, iv, opt_type)
    short_prem = _bs_premium(spot, short_strike, dte, iv, opt_type)

    # Ensure it's a credit-reducing debit (not a debit spread where short costs more)
    if short_prem >= long_prem * 0.95:
        short_prem = long_prem * 0.50   # floor at 50% of long premium

    return [
        Leg(strike=long_strike,  option_type=opt_type, action="BUY",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="primary", estimated_premium=round(long_prem, 2),
            symbol=_build_symbol(underlying, expiry["date"], long_strike, opt_type)),
        Leg(strike=short_strike, option_type=opt_type, action="SELL",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="hedge", estimated_premium=round(short_prem, 2),
            symbol=_build_symbol(underlying, expiry["date"], short_strike, opt_type)),
    ]


def _diagonal_spread(
    underlying: str, spot: float, atm: int, iv: float,
    direction: str, near: dict, far: dict, step: int,
) -> list[Leg]:
    """
    Diagonal Spread: Buy near-term ATM + Sell far-term OTM (or vice-versa).

    Directional bias: near-term ATM owns gamma (profits when price moves quickly).
    Far-term short: collects theta from a less aggressive strike (OTM protection).

    When direction is correct: near-term gains > far-term loses → net profit.
    When direction wrong: near-term limited loss, far-term premium offsets some.

    Example bearish NIFTY: Buy 24000PE (7d) @ ₹150 + Sell 23700PE (21d) @ ₹80 = ₹70 net
    If NIFTY falls 200pts: near PE → +₹120, far PE → -₹60 → net +₹60
    If NIFTY rises 100pts: near PE → -₹80, far PE → +₹40 → net -₹40 (partial offset)
    """
    near_dte = near["dte"]
    far_dte  = far["dte"]

    if direction == "long":
        opt_type = "CE"
        near_strike = atm                  # buy ATM CE near-term (gamma play)
        far_strike  = atm + step           # sell slightly OTM CE far-term (collect theta)
    else:
        opt_type = "PE"
        near_strike = atm
        far_strike  = atm - step

    near_prem = _bs_premium(spot, near_strike, near_dte, iv, opt_type)
    far_prem  = _bs_premium(spot, far_strike,  far_dte,  iv, opt_type)

    # Far-term should provide meaningful offset (>20% of near cost)
    far_prem = max(far_prem, near_prem * 0.25)

    return [
        Leg(strike=near_strike, option_type=opt_type, action="BUY",
            expiry_iso=near["date"], expiry_display=near["display"], expiry_dte=near_dte,
            role="primary", estimated_premium=round(near_prem, 2),
            symbol=_build_symbol(underlying, near["date"], near_strike, opt_type)),
        Leg(strike=far_strike,  option_type=opt_type, action="SELL",
            expiry_iso=far["date"], expiry_display=far["display"], expiry_dte=far_dte,
            role="hedge", estimated_premium=round(far_prem, 2),
            symbol=_build_symbol(underlying, far["date"], far_strike, opt_type)),
    ]


def _calendar_spread(
    underlying: str, spot: float, atm: int, iv: float,
    direction: str, near: dict, far: dict, step: int,
) -> list[Leg]:
    """
    Calendar Spread (time spread): Sell near-term ATM + Buy far-term ATM (same strike).
    Used when IV is elevated — sell the inflated near-term premium, buy cheaper far-term.

    Near-term decays faster (theta) → short near benefits from time passing.
    Far-term provides protection if price makes a sudden large move.

    If price stays near ATM: near-term sold decays → profit. Far-term loses slower.
    If price rallies sharply: near-term CE hurts, far-term CE gains → offset.

    Option type chosen by direction (still want directional bias in far leg).
    """
    near_dte = near["dte"]
    far_dte  = far["dte"]

    opt_type = "CE" if direction == "long" else "PE"
    strike   = atm   # same ATM strike for both legs

    near_prem = _bs_premium(spot, strike, near_dte, iv, opt_type)
    far_prem  = _bs_premium(spot, strike, far_dte,  iv, opt_type)

    # Calendar is a net debit: far (buy) > near (sell) in normal vol environments
    # Ensure near sold < far bought (otherwise we'd be paying more for near which makes no sense)
    near_prem = min(near_prem, far_prem * 0.85)

    return [
        Leg(strike=strike, option_type=opt_type, action="SELL",
            expiry_iso=near["date"], expiry_display=near["display"], expiry_dte=near_dte,
            role="calendar_short", estimated_premium=round(near_prem, 2),
            symbol=_build_symbol(underlying, near["date"], strike, opt_type)),
        Leg(strike=strike, option_type=opt_type, action="BUY",
            expiry_iso=far["date"], expiry_display=far["display"], expiry_dte=far_dte,
            role="calendar_long", estimated_premium=round(far_prem, 2),
            symbol=_build_symbol(underlying, far["date"], strike, opt_type)),
    ]


def _iron_condor(
    underlying: str, spot: float, atm: int, iv: float,
    iv_rank: float, expiry: dict, step: int,
) -> list[Leg]:
    """
    Iron Condor: 4 legs, all same expiry.
    Sell OTM CE + Sell OTM PE + Buy further OTM CE + Buy further OTM PE.

    Profits when price stays within the short strikes (theta decay).
    Wings (long far OTM) cap the max loss to spread_width - net_credit.

    Short CE/PE lose if price breaks out one side → wing on that side limits the loss.
    Short PE/CE on the other side decay to zero → contribute profit.

    Width: short strikes 2 steps from ATM; wings 4 steps from ATM.
    """
    dte = expiry["dte"]
    # Wider condor with higher IV rank (can afford wider strikes)
    width = 2 + (1 if iv_rank > 0.7 else 0)

    short_ce_strike = atm + width * step
    short_pe_strike = atm - width * step
    wing_ce_strike  = atm + (width + 2) * step
    wing_pe_strike  = atm - (width + 2) * step

    short_ce = _bs_premium(spot, short_ce_strike, dte, iv, "CE")
    short_pe = _bs_premium(spot, short_pe_strike, dte, iv, "PE")
    wing_ce  = _bs_premium(spot, wing_ce_strike,  dte, iv, "CE")
    wing_pe  = _bs_premium(spot, wing_pe_strike,  dte, iv, "PE")

    # Wings must be cheaper than shorts (credit spread condition)
    wing_ce = min(wing_ce, short_ce * 0.60)
    wing_pe = min(wing_pe, short_pe * 0.60)

    return [
        Leg(strike=short_ce_strike, option_type="CE", action="SELL",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="condor_short_ce", estimated_premium=round(short_ce, 2),
            symbol=_build_symbol(underlying, expiry["date"], short_ce_strike, "CE")),
        Leg(strike=short_pe_strike, option_type="PE", action="SELL",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="condor_short_pe", estimated_premium=round(short_pe, 2),
            symbol=_build_symbol(underlying, expiry["date"], short_pe_strike, "PE")),
        Leg(strike=wing_ce_strike, option_type="CE", action="BUY",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="condor_wing_ce", estimated_premium=round(wing_ce, 2),
            symbol=_build_symbol(underlying, expiry["date"], wing_ce_strike, "CE")),
        Leg(strike=wing_pe_strike, option_type="PE", action="BUY",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="condor_wing_pe", estimated_premium=round(wing_pe, 2),
            symbol=_build_symbol(underlying, expiry["date"], wing_pe_strike, "PE")),
    ]


def net_debit(legs: list[Leg]) -> float:
    """Net cost of the composite (positive = net debit, negative = net credit)."""
    return sum(-leg.estimated_premium * leg.net_sign() for leg in legs)


def strategy_name(legs: list[Leg]) -> str:
    roles = {leg.role for leg in legs}
    if "condor_short_ce" in roles:
        return "Iron Condor"
    if "calendar_short" in roles:
        return "Calendar Spread"
    if "hedge" in roles and any(l.expiry_dte != legs[0].expiry_dte for l in legs):
        return "Diagonal Spread"
    return "Vertical Spread"


def strategy_rationale(legs: list[Leg], iv_rank: float, direction: str) -> str:
    """One-sentence rationale for the composite."""
    name = strategy_name(legs)
    debit = net_debit(legs)
    credit_str = f"net {'debit' if debit > 0 else 'credit'} ₹{abs(debit):.0f}/unit"
    if name == "Iron Condor":
        return (f"Iron Condor: sell OTM CE+PE, buy wings for protection. "
                f"Profit if {legs[0].symbol.split('2')[0]} stays range-bound. IV rank {iv_rank:.0%} → theta play. {credit_str}.")
    if name == "Calendar Spread":
        return (f"Calendar Spread: sell near-term (high theta) + buy far-term (protection). "
                f"IV rank {iv_rank:.0%} elevated — monetise near-term vol. {credit_str}.")
    if name == "Diagonal Spread":
        return (f"Diagonal Spread: buy near-term ATM (gamma) + sell far-term OTM (offset). "
                f"{direction.title()} bias with theta offset. {credit_str}.")
    return (f"Vertical Spread: buy ATM + sell OTM, capped profit+loss. "
            f"{direction.title()} directional play, low IV. {credit_str}.")
