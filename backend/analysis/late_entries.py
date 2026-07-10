"""Find trades entered outside market hours (IST) — user report 2026-07-08."""
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal


async def go():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT trade_group_id, min(entry_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') AS ist, "
            "underlying, count(*), string_agg(DISTINCT leg_role, ','), max(notes) "
            "FROM trades WHERE entry_time >= NOW() - INTERVAL '3 days' "
            "GROUP BY trade_group_id, underlying ORDER BY ist"))).all()
        for g, ist, ul, n, roles, notes in rows:
            hhmm = ist.strftime("%d %H:%M")
            late = ist.hour > 15 or (ist.hour == 15 and ist.minute > 30) or ist.hour < 9
            flag = "  <-- OUTSIDE MARKET HOURS" if late else ""
            print(f"{hhmm} IST  {ul:10s} {(g or '?')[:8]} legs={n} {roles}{flag}")

asyncio.run(go())
