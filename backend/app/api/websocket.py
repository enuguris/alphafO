"""WebSocket endpoints — live signals, price ticks, portfolio updates."""
import asyncio
import json
import random
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.instruments import ALL_INSTRUMENTS, BASE_PRICES

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.signal_clients: list[WebSocket] = []
        self.price_clients: list[WebSocket] = []
        self.portfolio_clients: list[WebSocket] = []

    async def connect_signals(self, ws: WebSocket):
        await ws.accept()
        self.signal_clients.append(ws)
        logger.info(f"Signal WS connected. Total: {len(self.signal_clients)}")

    async def connect_prices(self, ws: WebSocket):
        await ws.accept()
        self.price_clients.append(ws)

    async def connect_portfolio(self, ws: WebSocket):
        await ws.accept()
        self.portfolio_clients.append(ws)

    def disconnect_signals(self, ws: WebSocket):
        if ws in self.signal_clients:
            self.signal_clients.remove(ws)

    def disconnect_prices(self, ws: WebSocket):
        if ws in self.price_clients:
            self.price_clients.remove(ws)

    def disconnect_portfolio(self, ws: WebSocket):
        if ws in self.portfolio_clients:
            self.portfolio_clients.remove(ws)

    async def broadcast(self, message: dict):
        """Broadcast to all signal subscribers (called by scanner)."""
        dead = []
        for ws in self.signal_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_signals(ws)

    async def broadcast_prices(self, ticks: dict):
        dead = []
        for ws in self.price_clients:
            try:
                await ws.send_json(ticks)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_prices(ws)

    async def broadcast_portfolio(self, data: dict):
        dead = []
        for ws in self.portfolio_clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_portfolio(ws)


manager = ConnectionManager()


def _get_price_snapshot() -> dict[str, dict]:
    """Pull latest prices from the ticker service (live or simulated)."""
    try:
        from app.core.data.kite_ticker import ticker_service
        return ticker_service.get_snapshot()
    except Exception:
        # Ultra-safe fallback: static base prices with zero change
        return {sym: {"ltp": float(p), "chg": 0.0} for sym, p in BASE_PRICES.items()}


@router.websocket("/ws/signals")
async def signals_ws(websocket: WebSocket):
    """Push new signals as they are detected by the scanner."""
    await manager.connect_signals(websocket)
    try:
        # Send current DB signals on connect
        from app.database import AsyncSessionLocal
        from app.models.signals import Signal, SignalStatus
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            q = select(Signal).where(Signal.status == SignalStatus.ACTIVE).order_by(Signal.created_at.desc()).limit(20)
            result = await db.execute(q)
            signals = result.scalars().all()
            if signals:
                payload = []
                for s in signals:
                    d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
                    # Make datetime serialisable
                    for k, v in d.items():
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    payload.append(d)
                await websocket.send_json({"type": "initial_signals", "signals": payload})

        # Keep alive
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping", "ts": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        manager.disconnect_signals(websocket)
    except Exception as e:
        logger.warning(f"Signal WS error: {e}")
        manager.disconnect_signals(websocket)


@router.websocket("/ws/prices")
async def prices_ws(websocket: WebSocket):
    """Stream price ticks — sourced from KiteTickerService (live or simulated)."""
    await manager.connect_prices(websocket)
    try:
        while True:
            snapshot = _get_price_snapshot()
            # Enrich with bid/ask spread (±0.01%)
            ticks = {
                sym: {
                    "ltp": data["ltp"],
                    "chg": data["chg"],
                    "bid": round(data["ltp"] * 0.9999, 2),
                    "ask": round(data["ltp"] * 1.0001, 2),
                }
                for sym, data in snapshot.items()
            }
            await websocket.send_json({
                "type": "price_tick",
                "ts": datetime.utcnow().isoformat(),
                "ticks": ticks,
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect_prices(websocket)
    except Exception as e:
        logger.warning(f"Price WS error: {e}")
        manager.disconnect_prices(websocket)


@router.websocket("/ws/portfolio")
async def portfolio_ws(websocket: WebSocket):
    """Push live portfolio P&L updates."""
    await manager.connect_portfolio(websocket)
    try:
        while True:
            from app.database import AsyncSessionLocal
            from app.models.portfolio import Portfolio
            from app.models.trades import Trade, TradeStatus
            from sqlalchemy import select, func

            async with AsyncSessionLocal() as db:
                port_q = select(Portfolio).where(Portfolio.mode == "paper")
                port_result = await db.execute(port_q)
                portfolio = port_result.scalar_one_or_none()

                open_q = select(func.count()).where(Trade.status == TradeStatus.OPEN)
                open_count = (await db.execute(open_q)).scalar()

            data = {
                "type": "portfolio_update",
                "ts": datetime.utcnow().isoformat(),
                "capital_current": portfolio.capital_current if portfolio else 0,
                "capital_deployed": portfolio.capital_deployed if portfolio else 0,
                "daily_pnl": portfolio.daily_pnl if portfolio else 0,
                "open_trades": open_count or 0,
            }
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        manager.disconnect_portfolio(websocket)
    except Exception as e:
        logger.warning(f"Portfolio WS error: {e}")
        manager.disconnect_portfolio(websocket)
