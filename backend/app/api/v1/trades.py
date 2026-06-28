"""Trade API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.trades import Trade

router = APIRouter()


@router.get("/")
async def list_trades(mode: str = "paper", status: str | None = None,
                      limit: int = 50, db: AsyncSession = Depends(get_db)):
    q = select(Trade).where(Trade.mode == mode)
    if status:
        q = q.where(Trade.status == status)
    q = q.order_by(Trade.entry_time.desc()).limit(limit)
    result = await db.execute(q)
    trades = result.scalars().all()
    return {"trades": [t.__dict__ for t in trades], "count": len(trades)}


@router.post("/{signal_id}/execute")
async def execute_trade(signal_id: int, mode: str = "paper", db: AsyncSession = Depends(get_db)):
    """Execute a signal as a paper or live trade."""
    return {"message": f"Trade execution queued for signal {signal_id} in {mode} mode"}


@router.post("/{trade_id}/exit")
async def exit_trade(trade_id: int, reason: str = "manual", db: AsyncSession = Depends(get_db)):
    """Manually exit an open trade."""
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    return {"message": f"Exit queued for trade {trade_id}", "reason": reason}
