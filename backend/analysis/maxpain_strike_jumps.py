"""Live-data learning: how much does the computed max-pain strike jump scan to scan?
Parses strike out of the signal explanation text (metadata dict is not persisted)."""
import asyncio, re
from sqlalchemy import text
from app.database import AsyncSessionLocal


async def go():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT underlying, created_at, direction, entry_price, explanation "
            "FROM signals WHERE created_at >= CURRENT_DATE - INTERVAL '3 days' "
            "AND pattern_name='max_pain' ORDER BY underlying, created_at"))).all()
        prev = {}
        print(f"{'UL':10s} {'utc':11s} {'dir':6s} {'spot':>9s} {'mp_strike':>9s} {'dev%':>6s} {'jump':>7s}")
        for ul, ts, d, spot, expl in rows:
            nums = re.findall(r"[-+]?\d[\d,]*\.?\d*", expl.replace(",", ""))
            # explanation: price ... max pain strike ... deviation
            mp = dev = None
            m = re.search(r"max pain[^\d]*([\d.]+)", expl, re.I)
            if m:
                mp = float(m.group(1))
            m2 = re.search(r"([-+]?[\d.]+)\s*%", expl)
            if m2:
                dev = float(m2.group(1))
            jump = (mp - prev.get(ul)) if (mp and prev.get(ul)) else 0
            if mp:
                prev[ul] = mp
            print(f"{ul:10s} {ts.strftime('%d %H:%M'):11s} {d:6s} {spot!s:>9s} {mp!s:>9s} {dev!s:>6s} {jump:>7.0f}")

asyncio.run(go())
