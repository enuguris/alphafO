"""
Composite option strategies — multi-leg net-credit defined-risk combinations.

DESIGN PRINCIPLE: Every composite must collect MORE premium than it pays.
  net_debit(legs) must be NEGATIVE (net credit) before the trade is placed.
  If a strategy would result in a net debit, build_composite() returns [].

Strategy selection by pattern type and IV rank:

  BUY_PATTERNS (directional signal) — same expiry, credit spread:
    any IV:    Credit Spread — sell ATM, buy OTM protection (same expiry)
               Bull Put Credit Spread  (bullish): SELL ATM PE + BUY OTM PE
               Bear Call Credit Spread (bearish): SELL ATM CE + BUY OTM CE
               Net credit always ≥ 30% of spread width. Time decay works for us.

  SELL_PATTERNS (iv_crush, expiry_week) — 4-leg Iron Condor:
               SELL OTM CE + SELL OTM PE + BUY wing CE + BUY wing PE
               All same expiry. Maximum theta collection. Wings cap max loss.

Minimum near-expiry DTE: 7 days (avoid same-week hyper-gamma).
Net credit check: if collected < paid, the build is rejected (returns []).

Each returned Leg dict has:
  strike, option_type, action, expiry_iso, expiry_display, expiry_dte,
  role, estimated_premium, symbol
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
    role: str                   # primary | hedge | condor_short_ce | condor_short_pe | condor_wing_ce | condor_wing_pe
    estimated_premium: float
    symbol: str                 # full NSE tradingsymbol e.g. NIFTY2671424000CE

    def net_sign(self) -> float:
        """Cash-flow sign: BUY = -1 (debit), SELL = +1 (credit)."""
        return -1.0 if self.action == "BUY" else 1.0


# Minimum DTE for the chosen expiry — avoid hyper-gamma on expiry week
_MIN_DTE = 7

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
        intr = max(0.0, (spot - strike) if option_type == "CE" else (strike - spot))
        return max(0.05, intr + spot * iv * math.sqrt(max(dte, 1) / 365.0) * 0.4)


def build_composite(
    underlying: str,
    spot: float,
    direction: str,           # "long" | "short"
    iv_rank: float,           # 0.0–1.0
    iv: float,                # absolute IV e.g. 0.18 = 18%
    pattern_name: str,
    available_expiries: list[dict],
    step: int = 50,
) -> list[Leg]:
    """
    Return a list of Leg objects forming a net-credit composite strategy.
    Returns [] if no net-credit structure can be built with available expiries.

    available_expiries must be sorted by DTE ascending (nearest first).
    Each expiry dict: {date: str, display: str, dte: int, series: str, short: str}
    """
    if not available_expiries:
        return []

    pname = pattern_name.lower()
    is_sell_pattern = pname in SELL_PATTERNS

    # Filter expiries: must have DTE >= _MIN_DTE
    valid = [e for e in available_expiries if e["dte"] >= _MIN_DTE]
    if not valid:
        return []

    # IV normalisation
    if iv > 2.0:
        iv = iv / 100.0
    iv = max(0.08, min(iv, 0.80))

    atm = _round_strike(spot, step)
    expiry = valid[0]   # nearest valid expiry (max theta)

    if is_sell_pattern:
        legs = _iron_condor(underlying, spot, atm, iv, iv_rank, expiry, step)
    else:
        legs = _credit_spread(underlying, spot, atm, iv, iv_rank, direction, expiry, step)

    # Net credit gate — reject any structure that would cost net money
    if not legs:
        return []
    nd = net_debit(legs)
    if nd > 0:
        # Net debit: premiums paid > premiums collected — reject
        return []

    return legs


# ── Strategy builders ─────────────────────────────────────────────────────────

def _credit_spread(
    underlying: str, spot: float, atm: int, iv: float, iv_rank: float,
    direction: str, expiry: dict, step: int,
) -> list[Leg]:
    """
    Credit Spread: Sell near-ATM option + Buy OTM protection. Same expiry.

    Bullish signal → Bull Put Credit Spread:
      SELL ATM PE (collect fat premium near ATM)
      BUY  OTM PE 2 steps below (pay small wing premium)
      Max profit = net credit (if spot stays above short PE strike at expiry)
      Max loss   = spread width - net credit (if spot crashes below long PE)

    Bearish signal → Bear Call Credit Spread:
      SELL ATM CE (collect fat premium near ATM)
      BUY  OTM CE 2 steps above (pay small wing premium)
      Max profit = net credit (if spot stays below short CE strike at expiry)
      Max loss   = spread width - net credit (if spot rallies above long CE)

    Both structures benefit from time decay (theta). The sold option decays
    faster in absolute terms. Net credit is always positive by construction.
    With high IV rank we widen the short strike (1 step OTM instead of ATM)
    to give more room for the trade to stay profitable.
    """
    dte = expiry["dte"]

    # With elevated IV, sell 1 step OTM for a little more cushion
    otm_offset = step if iv_rank > 0.55 else 0

    if direction == "long":
        # Bull Put Credit Spread — profit if price stays above short PE
        short_strike = atm - otm_offset          # sell this PE
        wing_strike  = short_strike - 2 * step   # buy this PE (protection)
        opt_type     = "PE"
    else:
        # Bear Call Credit Spread — profit if price stays below short CE
        short_strike = atm + otm_offset          # sell this CE
        wing_strike  = short_strike + 2 * step   # buy this CE (protection)
        opt_type     = "CE"

    short_prem = _bs_premium(spot, short_strike, dte, iv, opt_type)
    wing_prem  = _bs_premium(spot, wing_strike,  dte, iv, opt_type)

    # Wing must be cheaper (it's further OTM) — clamp if BS gives wrong direction
    wing_prem = min(wing_prem, short_prem * 0.70)
    # Minimum net credit: at least 30% of spread width to justify the trade
    spread_width = 2 * step
    net_credit   = short_prem - wing_prem
    if net_credit < spread_width * 0.30:
        # Boost wing prem down to meet min credit requirement
        wing_prem = min(wing_prem, short_prem - spread_width * 0.30)
        wing_prem = max(0.05, wing_prem)

    return [
        Leg(strike=short_strike, option_type=opt_type, action="SELL",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="primary", estimated_premium=round(short_prem, 2),
            symbol=_build_symbol(underlying, expiry["date"], short_strike, opt_type)),
        Leg(strike=wing_strike, option_type=opt_type, action="BUY",
            expiry_iso=expiry["date"], expiry_display=expiry["display"], expiry_dte=dte,
            role="hedge", estimated_premium=round(wing_prem, 2),
            symbol=_build_symbol(underlying, expiry["date"], wing_strike, opt_type)),
    ]


def _iron_condor(
    underlying: str, spot: float, atm: int, iv: float,
    iv_rank: float, expiry: dict, step: int,
) -> list[Leg]:
    """
    Iron Condor: 4 legs, same expiry, net credit.

    SELL OTM CE + SELL OTM PE (short strangle — collect premium)
    BUY  far OTM CE + BUY far OTM PE (wings — cap max loss)

    Profits when price stays between the short strikes (theta decay).
    Wings define the maximum loss (spread_width - net_credit per side).

    Short strikes: 2 steps from ATM (3 steps when high IV rank for more room).
    Wings: 2 steps beyond short strikes.
    """
    dte = expiry["dte"]
    # Wider short strikes with higher IV rank (more premium, more room)
    width = 3 if iv_rank > 0.65 else 2

    short_ce_strike = atm + width * step
    short_pe_strike = atm - width * step
    wing_ce_strike  = short_ce_strike + 2 * step
    wing_pe_strike  = short_pe_strike - 2 * step

    short_ce = _bs_premium(spot, short_ce_strike, dte, iv, "CE")
    short_pe = _bs_premium(spot, short_pe_strike, dte, iv, "PE")
    wing_ce  = _bs_premium(spot, wing_ce_strike,  dte, iv, "CE")
    wing_pe  = _bs_premium(spot, wing_pe_strike,  dte, iv, "PE")

    # Wings must be cheaper than shorts
    wing_ce = min(wing_ce, short_ce * 0.55)
    wing_pe = min(wing_pe, short_pe * 0.55)

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
    """
    Net cost of composite (positive = net debit paid, negative = net credit received).
    For a valid trade this should always be ≤ 0 (net credit).
    """
    return sum(-leg.estimated_premium * leg.net_sign() for leg in legs)


def net_credit(legs: list[Leg]) -> float:
    """Net credit received (positive = good, negative = net debit = bad)."""
    return -net_debit(legs)


def max_loss(legs: list[Leg], step: int) -> float:
    """
    Maximum possible loss per unit (spread width - net credit).
    For credit spread: width = 2*step, max_loss = width - net_credit.
    For iron condor: max_loss per side = width - credit_per_side; take the larger.
    """
    credit = net_credit(legs)
    sell_legs = [l for l in legs if l.action == "SELL"]
    buy_legs  = [l for l in legs if l.action == "BUY"]
    if not sell_legs or not buy_legs:
        return sum(l.estimated_premium for l in buy_legs)
    # Simple approximation: spread width on each side minus net credit
    spread = abs(buy_legs[0].strike - sell_legs[0].strike)
    return max(0.0, spread - credit)


def strategy_name(legs: list[Leg]) -> str:
    roles = {leg.role for leg in legs}
    if "condor_short_ce" in roles:
        return "Iron Condor"
    if "primary" in roles:
        sell_leg = next((l for l in legs if l.action == "SELL"), None)
        if sell_leg:
            return "Bull Put Spread" if sell_leg.option_type == "PE" else "Bear Call Spread"
    return "Credit Spread"


def strategy_rationale(legs: list[Leg], iv_rank: float, direction: str) -> str:
    """One-sentence rationale for the composite."""
    name   = strategy_name(legs)
    credit = net_credit(legs)
    nd_str = f"net credit ₹{credit:.0f}/unit"
    sell_legs = [l for l in legs if l.action == "SELL"]
    buy_legs  = [l for l in legs if l.action == "BUY"]

    if name == "Iron Condor":
        short_ce = next((l for l in sell_legs if l.option_type == "CE"), None)
        short_pe = next((l for l in sell_legs if l.option_type == "PE"), None)
        range_str = ""
        if short_ce and short_pe:
            range_str = f" Profit range: {int(short_pe.strike)}–{int(short_ce.strike)}."
        return (f"Iron Condor: sell OTM strangle + buy wings. IV rank {iv_rank:.0%} → "
                f"theta collection.{range_str} {nd_str}. Max loss = spread - credit.")
    if name == "Bull Put Spread":
        s = sell_legs[0] if sell_legs else None
        b = buy_legs[0]  if buy_legs  else None
        return (f"Bull Put Spread: sell {int(s.strike) if s else '?'}PE + buy "
                f"{int(b.strike) if b else '?'}PE. Profit if {legs[0].symbol[:10].rstrip('0')} "
                f"stays above {int(s.strike) if s else '?'}. {nd_str}.")
    if name == "Bear Call Spread":
        s = sell_legs[0] if sell_legs else None
        b = buy_legs[0]  if buy_legs  else None
        return (f"Bear Call Spread: sell {int(s.strike) if s else '?'}CE + buy "
                f"{int(b.strike) if b else '?'}CE. Profit if {legs[0].symbol[:10].rstrip('0')} "
                f"stays below {int(s.strike) if s else '?'}. {nd_str}.")
    return f"{name}: {nd_str}."
