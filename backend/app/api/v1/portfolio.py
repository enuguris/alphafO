"""Portfolio API endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.portfolio import Portfolio
from app.config import settings

router = APIRouter()


def _serialize(p: Portfolio) -> dict:
    win_rate = (p.winning_trades / p.total_trades) if p.total_trades > 0 else 0.0
    portfolio_heat_pct = (p.capital_deployed / p.capital_current * 100) if p.capital_current > 0 else 0.0
    return {
        # raw fields
        **{k: v for k, v in p.__dict__.items() if not k.startswith("_")},
        # aliases expected by the frontend
        "capital": p.capital_current,
        "win_rate": round(win_rate, 4),
        "portfolio_heat_pct": round(portfolio_heat_pct, 2),
    }


@router.get("/")
async def get_portfolio(mode: str = "paper", db: AsyncSession = Depends(get_db)):
    q = select(Portfolio).where(Portfolio.mode == mode)
    result = await db.execute(q)
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return {"message": f"No {mode} portfolio found. Start paper trading to create one."}
    return _serialize(portfolio)


@router.post("/init")
async def init_portfolio(mode: str = "paper", db: AsyncSession = Depends(get_db)):
    """Create a paper/live portfolio if one doesn't exist yet."""
    q = select(Portfolio).where(Portfolio.mode == mode)
    result = await db.execute(q)
    existing = result.scalar_one_or_none()
    if existing:
        return {"message": f"{mode} portfolio already exists", "portfolio": existing.__dict__}

    capital = settings.initial_capital
    portfolio = Portfolio(
        mode=mode,
        capital_initial=capital,
        capital_current=capital,
        capital_deployed=0.0,
        peak_capital=capital,
    )
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return {"message": f"{mode} portfolio created with ₹{capital:,.0f}", "portfolio": portfolio.__dict__}


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
