"""Backtest API endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import date
from app.database import get_db
from app.models.backtest import BacktestRun

router = APIRouter()


class BacktestRequest(BaseModel):
    underlying: str
    start_date: date
    end_date: date
    patterns: list[str] | None = None
    initial_capital: float = 500000.0
    name: str = "Backtest Run"


@router.post("/run")
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """Queue a backtest run (Celery task in production)."""
    return {
        "message": "Backtest queued",
        "underlying": req.underlying,
        "start_date": str(req.start_date),
        "end_date": str(req.end_date),
        "patterns": req.patterns or "all",
    }


@router.get("/results")
async def list_backtests(limit: int = 20, db: AsyncSession = Depends(get_db)):
    q = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
    result = await db.execute(q)
    runs = result.scalars().all()
    return {"results": [r.__dict__ for r in runs], "count": len(runs)}


@router.get("/{run_id}")
async def get_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    q = select(BacktestRun).where(BacktestRun.id == run_id)
    result = await db.execute(q)
    run = result.scalar_one_or_none()
    if not run:
        from fastapi import HTTPException
        raise HTTPException(404, "Backtest run not found")
    return run.__dict__
