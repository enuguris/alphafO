"""
Risk gate — enforces hard circuit breakers before any order reaches the broker.

Checks (in order):
  1. Kill switch  — Redis flag TRADING_HALTED=1
  2. Daily P&L    — if daily loss exceeds max_daily_loss_pct, halt
  3. Portfolio heat — if capital_deployed > max_portfolio_heat_pct, reject
  4. Position size — size signal to stay within per-trade risk limit

All checks are synchronous so they can be called from sync or async contexts.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Literal

import redis
from loguru import logger

from app.config import settings


KILL_SWITCH_KEY   = "TRADING_HALTED"
DAILY_PNL_KEY     = "daily_pnl"           # float, updated after each fill
DAILY_DEPLOYED_KEY = "daily_deployed"      # total capital in open positions


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    recommended_qty: int = 0
    capital_at_risk: float = 0.0


def _r() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


# ── Kill switch ────────────────────────────────────────────────────────────────

def is_halted() -> bool:
    return _r().get(KILL_SWITCH_KEY) == "1"


def halt_trading(reason: str = "manual") -> None:
    r = _r()
    r.set(KILL_SWITCH_KEY, "1")
    r.set("TRADING_HALT_REASON", reason)
    r.set("TRADING_HALT_TS", str(int(time.time())))
    logger.warning(f"TRADING HALTED: {reason}")


def resume_trading() -> None:
    r = _r()
    r.delete(KILL_SWITCH_KEY)
    r.delete("TRADING_HALT_REASON")
    logger.info("Trading resumed")


def halt_status() -> dict:
    r = _r()
    halted = r.get(KILL_SWITCH_KEY) == "1"
    return {
        "halted":    halted,
        "reason":    r.get("TRADING_HALT_REASON") or "",
        "halted_at": r.get("TRADING_HALT_TS") or "",
    }


# ── Daily P&L tracker ─────────────────────────────────────────────────────────

def record_pnl(realized_pnl: float) -> None:
    _r().incrbyfloat(DAILY_PNL_KEY, realized_pnl)


def record_deployed(amount: float) -> None:
    """Track capital deployed; call +amount on entry, -amount on close."""
    _r().incrbyfloat(DAILY_DEPLOYED_KEY, amount)


def get_daily_pnl() -> float:
    val = _r().get(DAILY_PNL_KEY)
    return float(val) if val else 0.0


def reset_daily_pnl() -> None:
    """Call at start of each trading day."""
    _r().set(DAILY_PNL_KEY, "0")
    _r().set(DAILY_DEPLOYED_KEY, "0")
    logger.info("Daily P&L and deployed capital reset")


# ── Main gate ─────────────────────────────────────────────────────────────────

def check(
    underlying: str,
    entry_price: float,
    stop_loss: float,
    lot_size: int,
    strategy: Literal["buy", "sell"],
    capital: float | None = None,
) -> RiskDecision:
    """
    Run all risk checks for a proposed trade.
    Returns RiskDecision with approved flag and recommended qty.
    """
    capital = capital or settings.paper_capital

    # 1. Kill switch
    if is_halted():
        r = _r()
        reason = r.get("TRADING_HALT_REASON") or "kill switch active"
        return RiskDecision(approved=False, reason=f"HALTED: {reason}")

    # 2. Daily loss limit
    daily_pnl = get_daily_pnl()
    max_daily_loss = capital * (settings.max_daily_loss_pct / 100)
    if daily_pnl < -max_daily_loss:
        halt_trading(f"Daily loss limit hit: ₹{abs(daily_pnl):.0f}")
        return RiskDecision(
            approved=False,
            reason=f"Daily loss limit ₹{max_daily_loss:.0f} breached. Trading halted."
        )

    # 3. Portfolio heat
    deployed = float(_r().get(DAILY_DEPLOYED_KEY) or 0)
    max_heat = capital * (settings.max_portfolio_heat / 100)
    if deployed >= max_heat:
        return RiskDecision(
            approved=False,
            reason=f"Portfolio heat limit reached: ₹{deployed:.0f} deployed of ₹{max_heat:.0f} max."
        )

    # 4. Position sizing
    risk_per_trade = capital * (settings.max_risk_per_trade / 100)
    if strategy == "buy":
        # Risk = (entry - stop) × qty × lot_size, cap at risk_per_trade
        per_unit_risk = abs(entry_price - stop_loss)
        if per_unit_risk <= 0:
            per_unit_risk = entry_price * 0.02  # default 2% stop
        max_qty_lots = int(risk_per_trade / (per_unit_risk * lot_size))
        max_qty_lots = max(1, max_qty_lots)
    else:
        # For option sells, margin-based sizing: 1 lot default
        max_qty_lots = 1

    capital_at_risk = max_qty_lots * lot_size * abs(entry_price - stop_loss)

    return RiskDecision(
        approved=True,
        reason="All risk checks passed",
        recommended_qty=max_qty_lots,
        capital_at_risk=round(capital_at_risk, 2),
    )
