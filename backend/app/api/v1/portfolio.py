"""Portfolio API endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.portfolio import Portfolio

router = APIRouter()


@router.get("/")
async def get_portfolio(mode: str = "paper", db: AsyncSession = Depends(get_db)):
    q = select(Portfolio).where(Portfolio.mode == mode)
    result = await db.execute(q)
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return {"message": f"No {mode} portfolio found. Start paper trading to create one."}
    data = {k: v for k, v in portfolio.__dict__.items() if not k.startswith("_")}
    data["capital"] = data.get("capital_current")  # frontend alias
    total = data.get("total_trades") or 0
    wins  = data.get("winning_trades") or 0
    data["win_rate"] = round(wins / total, 4) if total > 0 else None
    return data


@router.get("/pnl")
async def get_pnl_history(mode: str = "paper", days: int = 30, db: AsyncSession = Depends(get_db)):
    """Return daily P&L for equity curve chart."""
    from app.models.trades import Trade, TradeStatus, TradeMode
    from sqlalchemy import and_
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(days=days)
    trade_mode = TradeMode.LIVE if mode == "live" else TradeMode.PAPER
    q = select(Trade).where(and_(
        Trade.mode == trade_mode,
        Trade.exit_time >= since,
        Trade.status == TradeStatus.CLOSED,
    ))
    result = await db.execute(q)
    trades = result.scalars().all()
    return {"pnl_series": [{"date": str(t.exit_time.date()), "pnl": t.pnl} for t in trades if t.exit_time]}
