"""WebSocket endpoints for real-time signal and portfolio updates."""
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()

# Simple in-memory connection manager
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


@router.websocket("/ws/signals")
async def signals_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(30)  # keep-alive ping
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/ws/portfolio")
async def portfolio_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(5)
            # In production: push real portfolio state
            await websocket.send_json({"type": "portfolio_update", "data": {}})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
