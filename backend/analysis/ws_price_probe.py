"""Sample /ws/prices twice to see if prices move while market is closed."""
import asyncio, json
import websockets


async def go():
    uri = "ws://127.0.0.1:8000/ws/prices"
    async with websockets.connect(uri) as ws:
        frames = []
        for _ in range(6):
            frames.append(json.loads(await ws.recv()))
        for sym in ("NIFTY", "BANKNIFTY"):
            vals = [f["ticks"].get(sym, {}).get("ltp") for f in frames]
            chgs = [f["ticks"].get(sym, {}).get("chg") for f in frames]
            moving = len(set(vals)) > 1
            print(f"{sym}: ltp={vals} chg={chgs} -> {'MOVING (BUG)' if moving else 'frozen (ok)'}")

asyncio.run(go())
