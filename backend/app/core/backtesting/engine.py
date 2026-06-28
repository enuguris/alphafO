"""
AlphaFO Backtesting Engine — event-driven simulation over historical data.
"""
from __future__ import annotations
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from app.core.patterns.base import PatternSignal
from app.core.signals.generator import SignalGenerator
from app.core.risk.manager import RiskManager
from app.core.backtesting.metrics import compute_metrics


@dataclass
class BacktestTrade:
    signal: PatternSignal
    entry_date: datetime
    entry_price: float
    exit_date: datetime | None = None
    exit_price: float | None = None
    quantity: int = 1
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    status: str = "open"   # open | closed


@dataclass
class BacktestResult:
    strategy_name: str
    underlying: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class BacktestEngine:
    """
    Walk-forward event-driven backtester.
    Iterates day by day, runs patterns on available history, simulates execution.
    Includes realistic slippage (0.1%) and commission (₹20/trade).
    """

    SLIPPAGE_PCT = 0.001     # 0.1% slippage
    COMMISSION = 20.0        # ₹20 per trade (flat)

    def __init__(self, initial_capital: float = 500_000):
        self.initial_capital = initial_capital
        self.signal_gen = SignalGenerator()
        self.risk_mgr = RiskManager(capital=initial_capital)

    def run(
        self,
        ohlcv: pd.DataFrame,
        underlying: str,
        start_date: str,
        end_date: str,
        pattern_filter: list[str] | None = None,
        options_chain_map: dict | None = None,   # date_str → DataFrame
        lot_size: int = 1,
        strategy_name: str = "AlphaFO",
    ) -> BacktestResult:
        """
        Run backtest. ohlcv must have all history up to start_date for warm-up.
        """
        df = ohlcv.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)

        dates = df[start_date:end_date].index.unique()
        capital = self.initial_capital
        open_trades: list[BacktestTrade] = []
        closed_trades: list[BacktestTrade] = []
        equity_curve = []

        for dt in dates:
            date_str = str(dt.date())
            # Data available up to and including current day
            history = df[:dt]
            if len(history) < 30:
                continue

            options_chain = options_chain_map.get(date_str) if options_chain_map else None
            current_price = history["close"].iloc[-1]

            # --- Exit open trades ---
            still_open = []
            for trade in open_trades:
                closed, trade = self._check_exit(trade, current_price, history)
                if closed:
                    # Apply commission and slippage
                    slippage = trade.exit_price * self.SLIPPAGE_PCT
                    effective_exit = trade.exit_price - slippage if trade.signal.direction == "long" else trade.exit_price + slippage
                    raw_pnl = (effective_exit - trade.entry_price) * trade.quantity
                    if trade.signal.direction == "short":
                        raw_pnl = (trade.entry_price - effective_exit) * trade.quantity
                    trade.pnl = raw_pnl - self.COMMISSION
                    trade.pnl_pct = trade.pnl / (trade.entry_price * trade.quantity)
                    capital += trade.pnl
                    closed_trades.append(trade)
                else:
                    still_open.append(trade)
            open_trades = still_open

            # --- Generate new signals ---
            portfolio_heat = sum(t.signal.entry_price * t.quantity / capital for t in open_trades)
            if portfolio_heat < 0.03 and len(open_trades) < 3:
                signals = self.signal_gen.run(history.reset_index(), options_chain, underlying, pattern_filter)
                for signal in signals[:2]:  # max 2 new signals per day
                    size = self.risk_mgr.calculate_position_size(
                        signal.entry_price, signal.stop_loss, lot_size, portfolio_heat
                    )
                    if size.is_allowed and size.quantity > 0:
                        slippage = signal.entry_price * self.SLIPPAGE_PCT
                        entry = signal.entry_price + slippage if signal.direction == "long" else signal.entry_price - slippage
                        capital -= self.COMMISSION
                        open_trades.append(BacktestTrade(
                            signal=signal, entry_date=dt, entry_price=entry, quantity=size.quantity,
                        ))
                        break  # one new trade per day max

            equity_curve.append({"date": date_str, "capital": round(capital, 2), "open_trades": len(open_trades)})

        result = BacktestResult(
            strategy_name=strategy_name, underlying=underlying,
            start_date=pd.to_datetime(start_date), end_date=pd.to_datetime(end_date),
            initial_capital=self.initial_capital, final_capital=round(capital, 2),
            trades=closed_trades, equity_curve=equity_curve,
        )
        result.metrics = compute_metrics(result)
        return result

    def _check_exit(self, trade: BacktestTrade, current_price: float, history: pd.DataFrame) -> tuple[bool, BacktestTrade]:
        """Check if trade should be exited on this bar."""
        signal = trade.signal

        # Stop loss hit
        if signal.direction == "long" and current_price <= signal.stop_loss:
            trade.exit_price = signal.stop_loss
            trade.exit_reason = "stop_hit"
            trade.status = "closed"
            trade.exit_date = history.index[-1]
            return True, trade

        if signal.direction == "short" and current_price >= signal.stop_loss:
            trade.exit_price = signal.stop_loss
            trade.exit_reason = "stop_hit"
            trade.status = "closed"
            trade.exit_date = history.index[-1]
            return True, trade

        # Target hit
        if signal.direction == "long" and current_price >= signal.target_price:
            trade.exit_price = signal.target_price
            trade.exit_reason = "target_hit"
            trade.status = "closed"
            trade.exit_date = history.index[-1]
            return True, trade

        if signal.direction == "short" and current_price <= signal.target_price:
            trade.exit_price = signal.target_price
            trade.exit_reason = "target_hit"
            trade.status = "closed"
            trade.exit_date = history.index[-1]
            return True, trade

        # Intraday: force exit at EOD
        if signal.trading_style == "intraday":
            trade.exit_price = current_price
            trade.exit_reason = "eod_exit"
            trade.status = "closed"
            trade.exit_date = history.index[-1]
            return True, trade

        # Positional: max 5 day hold
        days_held = (history.index[-1] - trade.entry_date).days
        if days_held >= 5:
            trade.exit_price = current_price
            trade.exit_reason = "max_hold_exit"
            trade.status = "closed"
            trade.exit_date = history.index[-1]
            return True, trade

        return False, trade
