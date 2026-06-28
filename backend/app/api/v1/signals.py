"""Signal API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.signals import Signal

router = APIRouter()


@router.get("/")
async def list_signals(
    pattern: str | None = None,
    underlying: str | None = None,
    status: str = "active",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Signal).where(Signal.status == status)
    if pattern:
        q = q.where(Signal.pattern_name == pattern)
    if underlying:
        q = q.where(Signal.underlying == underlying)
    q = q.order_by(Signal.created_at.desc()).limit(limit)
    result = await db.execute(q)
    signals = result.scalars().all()
    return {"signals": [s.__dict__ for s in signals], "count": len(signals)}


@router.get("/{signal_id}")
async def get_signal(signal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(404, "Signal not found")
    return signal.__dict__


@router.post("/run")
async def run_signals(
    underlying: str,
    patterns: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a signal generation run (enqueues Celery task)."""
    # In production this would be a Celery task
    return {"message": f"Signal run queued for {underlying}", "patterns": patterns or "all"}
