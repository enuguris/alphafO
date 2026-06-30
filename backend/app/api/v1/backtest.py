"""Backtest API endpoints — replay pattern engine on Kite historical data."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import date
from loguru import logger

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
    """Replay the pattern engine on Kite historical OHLCV for the given range."""
    from app.core.data.kite_adapter import KiteAdapter
    from app.core.patterns.registry import PatternRegistry
    from app.core.scanner import _resolve_nse_token, synthetic_ohlcv
    import pandas as pd

    adapter = KiteAdapter()

    # Resolve token without calling instruments() (rate-limited)
    token = _resolve_nse_token(req.underlying)
    df: pd.DataFrame | None = None

    if adapter.is_configured() and token:
        try:
            df = adapter.get_historical(token, req.start_date, req.end_date, "day")
        except Exception as e:
            logger.warning(f"Backtest Kite fetch failed: {e}")

    if df is None or df.empty:
        # Fall back to synthetic — at least validates the engine
        df = synthetic_ohlcv(req.underlying, "daily")
        source = "synthetic"
    else:
        source = "kite"

    if "iv" not in df.columns:
        import numpy as np
        rng = __import__("numpy").random.default_rng(42)
        df["iv"] = rng.uniform(12, 28, len(df))
    if "oi" not in df.columns:
        df["oi"] = 0.0

    registry = PatternRegistry.get()
    window = min(120, len(df) // 2)
    results = []

    for i in range(window, len(df)):
        window_df = df.iloc[i - window:i].copy()
        for pattern in registry.all():
            if req.patterns and pattern.name not in req.patterns:
                continue
            try:
                sigs = pattern.detect(window_df, underlying=req.underlying)
                for sig in sigs:
                    if sig.confidence_score < 0.65:
                        continue
                    fwd = min(5, len(df) - i - 1)
                    entry = float(df["close"].iloc[i])
                    exit_ = float(df["close"].iloc[i + fwd]) if fwd > 0 else entry
                    ret_pct = (exit_ - entry) / entry * 100
                    if sig.direction == "short":
                        ret_pct = -ret_pct
                    results.append({
                        "date":        str(df["timestamp"].iloc[i])[:10],
                        "pattern":     pattern.name,
                        "direction":   sig.direction,
                        "confidence":  round(sig.confidence_score, 3),
                        "entry_price": round(entry, 2),
                        "exit_price":  round(exit_, 2),
                        "return_pct":  round(ret_pct, 2),
                    })
            except Exception:
                pass
        await asyncio.sleep(0)  # yield to event loop between bars

    wins = sum(1 for r in results if r["return_pct"] > 0)
    total_return = sum(r["return_pct"] for r in results)

    # Sharpe ratio: mean return / std dev of returns (annualised)
    import math as _math
    sharpe = None
    if len(results) >= 5:
        rets = [r["return_pct"] for r in results]
        mean_r = sum(rets) / len(rets)
        std_r = (_math.sqrt(sum((x - mean_r) ** 2 for x in rets) / len(rets))) if len(rets) > 1 else 0
        sharpe = round(mean_r / std_r * _math.sqrt(252), 2) if std_r > 0 else 0.0

    import json
    run = BacktestRun(
        name=req.name,
        pattern_names=",".join(req.patterns) if req.patterns else "all",
        underlying=req.underlying,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        final_capital=req.initial_capital * (1 + total_return / 100),
        total_return_pct=round(total_return, 2),
        max_drawdown_pct=0.0,
        sharpe_ratio=sharpe,
        total_trades=len(results),
        win_rate=round(wins / len(results) * 100, 1) if results else 0,
        report_json=json.dumps({"data_source": source, "trades": results[:200]}),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "run_id":          run.id,
        "underlying":      req.underlying,
        "start_date":      str(req.start_date),
        "end_date":        str(req.end_date),
        "data_source":     source,
        "bars_analysed":   len(df) - window,
        "signals_found":   len(results),
        "win_rate":        run.win_rate,
        "total_return_pct": run.total_return_pct,
        "trades":          results,
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
        raise HTTPException(404, "Backtest run not found")
    return run.__dict__
