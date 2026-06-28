"""Performance metrics for backtest results."""
from __future__ import annotations
import numpy as np
import pandas as pd


def compute_metrics(result) -> dict:
    """Compute standard performance metrics from a BacktestResult."""
    trades = result.trades
    if not trades:
        return {"error": "No closed trades"}

    pnls = [t.pnl for t in trades]
    pnl_pcts = [t.pnl_pct for t in trades if t.pnl_pct is not None]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_return = (result.final_capital - result.initial_capital) / result.initial_capital

    # Sharpe ratio (annualised, assuming daily returns)
    equity = pd.Series([e["capital"] for e in result.equity_curve])
    daily_returns = equity.pct_change().dropna()
    sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0.0

    # Max drawdown
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    return {
        "total_return_pct": round(total_return * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(abs(max_drawdown) * 100, 2),
        "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "avg_profit": round(np.mean(wins), 2) if wins else 0,
        "avg_loss": round(np.mean(losses), 2) if losses else 0,
        "profit_factor": round(profit_factor, 2),
        "avg_trade_return_pct": round(np.mean(pnl_pcts) * 100, 2) if pnl_pcts else 0,
        "initial_capital": result.initial_capital,
        "final_capital": result.final_capital,
    }
