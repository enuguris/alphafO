"""Trade API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.trades import Trade

router = APIRouter()


def _trade_dict(t: Trade) -> dict:
    return {
        "id": t.id, "signal_id": t.signal_id, "mode": t.mode,
        "symbol": t.symbol, "underlying": t.underlying,
        "option_type": t.option_type, "strike": t.strike,
        "lot_size": t.lot_size, "expiry_date": t.expiry_date,
        "expiry_display": t.expiry_display,
        "action": t.action, "direction": t.direction, "quantity": t.quantity,
        "entry_price": t.entry_price, "exit_price": t.exit_price,
        "current_price": t.current_price, "target_price": t.target_price,
        "stop_loss": t.stop_loss,
        "gross_pnl": t.gross_pnl, "unrealized_pnl": t.unrealized_pnl,
        "realized_pnl": t.realized_pnl, "pnl": t.pnl, "pnl_pct": t.pnl_pct,
        "charges_total": t.charges_total, "charges_entry": t.charges_entry,
        "charges_brokerage": t.charges_brokerage, "charges_stt": t.charges_stt,
        "charges_gst": t.charges_gst, "charges_txn": t.charges_txn,
        "charges_sebi": t.charges_sebi, "charges_stamp": t.charges_stamp,
        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "last_mtm_at": t.last_mtm_at.isoformat() if t.last_mtm_at else None,
        "status": t.status, "exit_reason": t.exit_reason,
        "capital_at_risk_pct": t.capital_at_risk_pct, "notes": t.notes,
        "is_hedge": bool(t.notes and t.notes.startswith("spread_leg:hedge")),
        "pattern": (t.notes.split("pattern:")[-1].split("|")[0] if t.notes and "pattern:" in t.notes else None),
    }


@router.get("/")
async def list_trades(mode: str = "live", status: str | None = None,
                      limit: int = 50, db: AsyncSession = Depends(get_db)):
    from app.models.trades import TradeMode, TradeStatus
    q = select(Trade).where(Trade.mode == TradeMode(mode.lower()))
    if status:
        q = q.where(Trade.status == TradeStatus(status.lower()))
    q = q.order_by(Trade.entry_time.desc()).limit(limit)
    result = await db.execute(q)
    trades = result.scalars().all()
    return {"trades": [_trade_dict(t) for t in trades], "count": len(trades)}


@router.post("/refresh-mtm")
async def refresh_mtm(db: AsyncSession = Depends(get_db)):
    """Run MTM update inline and return all open trades with fresh prices."""
    from app.workers.tasks import _do_mtm_update
    await _do_mtm_update()
    from app.models.trades import TradeStatus
    q = select(Trade).where(
        Trade.status == TradeStatus.OPEN,
    ).order_by(Trade.entry_time.desc())
    trades = (await db.execute(q)).scalars().all()
    total_unrealized = sum(
        (t.unrealized_pnl or 0) for t in trades
        if not (t.notes or "").startswith("spread_leg:hedge")
    )
    return {
        "trades": [_trade_dict(t) for t in trades],
        "total_unrealized_pnl": round(total_unrealized, 2),
        "count": len(trades),
        "refreshed_at": __import__("datetime").datetime.utcnow().isoformat(),
    }


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


@router.post("/{trade_id}/close")
async def close_trade_manual(trade_id: int, db: AsyncSession = Depends(get_db)):
    """Manually close an open paper trade at current price."""
    from app.models.trades import TradeStatus
    from app.core.charges import calculate_charges
    from app.models.portfolio import Portfolio
    from datetime import datetime

    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    if trade.status != TradeStatus.OPEN:
        raise HTTPException(400, f"Trade is already {trade.status.value}")

    exit_price = trade.current_price or trade.entry_price or 0.0
    charges = calculate_charges(
        entry_premium=trade.entry_price or 0.0,
        exit_premium=exit_price,
        quantity=trade.quantity or 1,
        action=trade.action or "BUY",
    )
    if trade.action == "BUY":
        gross = (exit_price - (trade.entry_price or 0)) * (trade.quantity or 1)
    else:
        gross = ((trade.entry_price or 0) - exit_price) * (trade.quantity or 1)
    net_pnl = gross - charges.total

    trade.exit_price     = exit_price
    trade.exit_time      = datetime.utcnow()
    trade.status         = TradeStatus.CLOSED
    trade.exit_reason    = "manual_close"
    trade.gross_pnl      = round(gross, 2)
    trade.realized_pnl   = round(net_pnl, 2)
    trade.pnl            = round(net_pnl, 2)
    trade.unrealized_pnl = None
    trade.charges_total  = round(charges.total, 2)

    port_q = await db.execute(select(Portfolio).where(Portfolio.mode == trade.mode))
    portfolio = port_q.scalar_one_or_none()
    if portfolio:
        trade_cost = (trade.entry_price or 0) * (trade.quantity or 1)
        portfolio.capital_current  += trade_cost + net_pnl
        portfolio.capital_deployed  = max(0, portfolio.capital_deployed - trade_cost)
        portfolio.daily_pnl         = (portfolio.daily_pnl or 0) + net_pnl
        portfolio.total_pnl         = (portfolio.total_pnl or 0) + net_pnl

    await db.commit()
    return {"message": "Trade closed", "trade_id": trade_id, "exit_price": exit_price, "pnl": round(net_pnl, 2)}
