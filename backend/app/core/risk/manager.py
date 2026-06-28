"""
Risk Manager — capital protection, position sizing, portfolio heat checks.
AlphaFO's top priority: never lose more than 1% per trade, 3% portfolio.
"""
from dataclasses import dataclass
from loguru import logger
from app.config import settings


@dataclass
class PositionSize:
    quantity: int
    capital_at_risk: float
    capital_at_risk_pct: float
    is_allowed: bool
    rejection_reason: str = ""


class RiskManager:
    """Enforces all risk rules before any trade is sized or placed."""

    def __init__(self, capital: float = None):
        self.capital = capital or settings.initial_capital
        self.max_risk_per_trade = settings.max_capital_risk_per_trade
        self.max_portfolio_heat = settings.max_portfolio_heat
        self.daily_loss_limit = settings.daily_loss_limit
        self.weekly_loss_limit = settings.weekly_loss_limit

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        lot_size: int = 1,
        current_portfolio_heat: float = 0.0,
        daily_pnl_pct: float = 0.0,
        weekly_pnl_pct: float = 0.0,
    ) -> PositionSize:
        """
        Calculate safe position size.

        Formula: qty = (capital × max_risk) / (entry - stop_loss)
        Then round down to nearest lot_size.
        """
        # Hard circuit breakers
        if daily_pnl_pct <= -self.daily_loss_limit:
            return PositionSize(0, 0, 0, False,
                f"Daily loss limit hit ({daily_pnl_pct*100:.1f}%). No new trades today.")

        if weekly_pnl_pct <= -self.weekly_loss_limit:
            return PositionSize(0, 0, 0, False,
                f"Weekly loss limit hit ({weekly_pnl_pct*100:.1f}%). No new trades this week.")

        if current_portfolio_heat >= self.max_portfolio_heat:
            return PositionSize(0, 0, 0, False,
                f"Portfolio heat at {current_portfolio_heat*100:.1f}% (max {self.max_portfolio_heat*100:.0f}%). Wait for open positions to close.")

        risk_per_trade = self.capital * self.max_risk_per_trade
        price_risk = abs(entry_price - stop_loss)
        if price_risk == 0:
            return PositionSize(0, 0, 0, False, "Entry and stop loss are the same price.")

        raw_qty = risk_per_trade / price_risk
        quantity = max(1, int(raw_qty / lot_size) * lot_size)

        actual_risk = quantity * price_risk
        actual_risk_pct = actual_risk / self.capital

        # Ensure we don't exceed 1% even after rounding
        if actual_risk_pct > self.max_risk_per_trade * 1.1:
            quantity = max(1, quantity - lot_size)
            actual_risk = quantity * price_risk
            actual_risk_pct = actual_risk / self.capital

        logger.info(
            f"Position size: qty={quantity}, risk=₹{actual_risk:.0f} ({actual_risk_pct*100:.2f}% of capital)"
        )

        return PositionSize(
            quantity=quantity,
            capital_at_risk=round(actual_risk, 2),
            capital_at_risk_pct=round(actual_risk_pct, 4),
            is_allowed=True,
        )

    def check_portfolio_heat(self, open_trades: list[dict]) -> float:
        """Calculate current portfolio heat from list of open trade dicts."""
        total_risk = sum(t.get("capital_at_risk_pct", 0) for t in open_trades)
        return total_risk
