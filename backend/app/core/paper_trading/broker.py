"""
Paper Trading Broker — simulates order execution with virtual capital.
"""
from datetime import datetime
from loguru import logger
from app.core.patterns.base import PatternSignal
from app.core.risk.manager import RiskManager
from app.core.risk.guardrails import pre_trade_check
from app.config import settings


class PaperBroker:
    """Executes simulated trades, maintains virtual portfolio state."""

    def __init__(self, initial_capital: float = None):
        self.capital = initial_capital or settings.initial_capital
        self.initial_capital = self.capital
        self.positions: list[dict] = []
        self.trade_log: list[dict] = []
        self.daily_pnl: float = 0.0
        self.weekly_pnl: float = 0.0
        self.risk_mgr = RiskManager(capital=self.capital)

    def execute_signal(self, signal: PatternSignal, lot_size: int = 1, current_price: float = None) -> dict:
        """Try to execute a signal as a paper trade."""
        portfolio_heat = self._portfolio_heat()
        daily_pnl_pct = self.daily_pnl / self.initial_capital
        weekly_pnl_pct = self.weekly_pnl / self.initial_capital

        allowed, reason = pre_trade_check(
            mode="paper",
            signal_confidence=signal.confidence_score,
            capital_at_risk_pct=settings.max_capital_risk_per_trade,
            portfolio_heat=portfolio_heat,
            daily_pnl_pct=daily_pnl_pct,
        )
        if not allowed:
            logger.warning(f"Paper trade rejected: {reason}")
            return {"success": False, "reason": reason}

        size = self.risk_mgr.calculate_position_size(
            signal.entry_price, signal.stop_loss, lot_size, portfolio_heat,
            daily_pnl_pct, weekly_pnl_pct,
        )
        if not size.is_allowed:
            return {"success": False, "reason": size.rejection_reason}

        entry_price = current_price or signal.entry_price
        trade = {
            "id": len(self.trade_log) + 1,
            "signal_id": id(signal),
            "symbol": signal.symbol,
            "instrument": signal.instrument,
            "direction": signal.direction,
            "quantity": size.quantity,
            "entry_price": entry_price,
            "stop_loss": signal.stop_loss,
            "target": signal.target_price,
            "capital_at_risk_pct": size.capital_at_risk_pct,
            "capital_at_risk": size.capital_at_risk,
            "entry_time": datetime.utcnow().isoformat(),
            "status": "open",
            "pnl": 0.0,
            "pattern": signal.pattern_name,
        }
        self.positions.append(trade)
        self.trade_log.append(trade)
        logger.info(f"Paper trade opened: {trade['instrument']} {trade['direction']} x{trade['quantity']} @ {entry_price}")
        return {"success": True, "trade": trade}

    def update_positions(self, market_prices: dict[str, float]) -> list[dict]:
        """Mark positions to market. Close any that hit target or stop."""
        closed = []
        still_open = []
        for pos in self.positions:
            current = market_prices.get(pos["instrument"], pos["entry_price"])
            if pos["direction"] == "long":
                unrealised_pnl = (current - pos["entry_price"]) * pos["quantity"]
                hit_stop = current <= pos["stop_loss"]
                hit_target = current >= pos["target"]
            else:
                unrealised_pnl = (pos["entry_price"] - current) * pos["quantity"]
                hit_stop = current >= pos["stop_loss"]
                hit_target = current <= pos["target"]

            pos["unrealised_pnl"] = round(unrealised_pnl, 2)
            pos["current_price"] = current

            if hit_stop or hit_target:
                exit_price = pos["stop_loss"] if hit_stop else pos["target"]
                pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
                if pos["direction"] == "short":
                    pnl = (pos["entry_price"] - exit_price) * pos["quantity"]
                pos["pnl"] = round(pnl, 2)
                pos["exit_price"] = exit_price
                pos["exit_time"] = datetime.utcnow().isoformat()
                pos["exit_reason"] = "stop_hit" if hit_stop else "target_hit"
                pos["status"] = "closed"
                self.capital += pnl
                self.daily_pnl += pnl
                self.weekly_pnl += pnl
                closed.append(pos)
            else:
                still_open.append(pos)

        self.positions = still_open
        return closed

    def portfolio_state(self) -> dict:
        total_unrealised = sum(p.get("unrealised_pnl", 0) for p in self.positions)
        return {
            "capital": round(self.capital, 2),
            "capital_deployed": round(self._deployed_capital(), 2),
            "unrealised_pnl": round(total_unrealised, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "weekly_pnl": round(self.weekly_pnl, 2),
            "open_positions": len(self.positions),
            "portfolio_heat_pct": round(self._portfolio_heat() * 100, 2),
            "total_trades": len(self.trade_log),
            "win_rate": self._win_rate(),
        }

    def _portfolio_heat(self) -> float:
        return sum(p["capital_at_risk_pct"] for p in self.positions)

    def _deployed_capital(self) -> float:
        return sum(p["entry_price"] * p["quantity"] for p in self.positions)

    def _win_rate(self) -> float:
        closed = [t for t in self.trade_log if t["status"] == "closed"]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t["pnl"] > 0)
        return round(wins / len(closed), 3)

    def meets_live_promotion_criteria(self) -> tuple[bool, str]:
        """Check if paper trading results qualify for live trading."""
        closed = [t for t in self.trade_log if t["status"] == "closed"]
        if len(closed) < settings.paper_min_trades:
            return False, f"Need {settings.paper_min_trades} trades. Have {len(closed)}."
        if self._win_rate() < settings.paper_min_win_rate:
            return False, f"Win rate {self._win_rate()*100:.1f}% < {settings.paper_min_win_rate*100:.0f}% required."
        return True, "Criteria met. Ready for live trading."
