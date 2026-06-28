"""
Hard guardrails enforced before any trade execution.
These are never bypassable — they run in code before order placement.
"""
from app.config import settings, AppMode


def pre_trade_check(
    mode: str,
    signal_confidence: float,
    capital_at_risk_pct: float,
    portfolio_heat: float,
    daily_pnl_pct: float,
    paper_stats: dict | None = None,
) -> tuple[bool, str]:
    """
    Run all guardrails. Returns (is_allowed, reason).
    """
    # 1. Live trading gate
    if mode == AppMode.LIVE:
        if not paper_stats:
            return False, "Paper trading stats required before live trading."
        if paper_stats.get("total_trades", 0) < settings.paper_min_trades:
            return False, f"Need {settings.paper_min_trades} paper trades. Current: {paper_stats['total_trades']}"
        if paper_stats.get("win_rate", 0) < settings.paper_min_win_rate:
            return False, f"Win rate {paper_stats['win_rate']*100:.1f}% below minimum {settings.paper_min_win_rate*100:.0f}%"
        if paper_stats.get("max_drawdown", 1) > settings.paper_max_drawdown:
            return False, f"Drawdown {paper_stats['max_drawdown']*100:.1f}% exceeds maximum {settings.paper_max_drawdown*100:.0f}%"

    # 2. Daily loss limit
    if daily_pnl_pct <= -settings.daily_loss_limit:
        return False, f"Daily loss limit of {settings.daily_loss_limit*100:.0f}% hit. Trading paused."

    # 3. Portfolio heat
    if portfolio_heat >= settings.max_portfolio_heat:
        return False, f"Portfolio heat {portfolio_heat*100:.1f}% at maximum. Wait for positions to close."

    # 4. Per-trade risk
    if capital_at_risk_pct > settings.max_capital_risk_per_trade:
        return False, f"Trade risk {capital_at_risk_pct*100:.2f}% exceeds 1% limit."

    # 5. Minimum confidence
    if signal_confidence < 0.5:
        return False, f"Signal confidence {signal_confidence:.2f} too low (minimum 0.5)."

    return True, "OK"
