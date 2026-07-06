"""Expire phantom ACTIVE max_pain signals; show any signals created in last 10 min."""
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal


async def go():
    async with AsyncSessionLocal() as db:
        n = await db.execute(text(
            "UPDATE signals SET status='EXPIRED' "
            "WHERE status='ACTIVE' AND pattern_name='max_pain'"))
        await db.commit()
        print("phantom max_pain expired:", n.rowcount)
        rows = (await db.execute(text(
            "SELECT pattern_name, underlying, direction, entry_price, "
            "created_at::time(0) FROM signals "
            "WHERE created_at >= NOW() - INTERVAL '10 minutes' "
            "ORDER BY created_at DESC LIMIT 12"))).all()
        print("fresh signals (last 10 min):")
        for r in rows:
            print(" ", r)

asyncio.run(go())
