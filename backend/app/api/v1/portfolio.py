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
    return data


@router.get("/pnl")
async def get_pnl_history(mode: str = "paper", days: int = 30, db: AsyncSession = Depends(get_db)):
    """Return daily P&L for equity curve chart."""
    from app.models.trades import Trade
    from sqlalchemy import and_
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(days=days)
    q = select(Trade).where(and_(Trade.mode == mode, Trade.exit_time >= since, Trade.status == "closed"))
    result = await db.execute(q)
    trades = result.scalars().all()
    return {"pnl_series": [{"date": str(t.exit_time.date()), "pnl": t.pnl} for t in trades if t.exit_time]}
