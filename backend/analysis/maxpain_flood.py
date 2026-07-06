"""Why 69 max_pain signals today? Dedup/expiry-churn diagnosis."""
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal


async def go():
    async with AsyncSessionLocal() as db:
        print("== today's max_pain by bucket ==")
        rows = (await db.execute(text(
            "SELECT underlying, direction, option_type, status, count(*), "
            "min(created_at at time zone 'Asia/Kolkata')::time(0), "
            "max(created_at at time zone 'Asia/Kolkata')::time(0) "
            "FROM signals WHERE created_at >= CURRENT_DATE AND pattern_name='max_pain' "
            "GROUP BY 1,2,3,4 ORDER BY 5 DESC"))).all()
        for r in rows:
            print(" ", r)
        print("\n== creation times, first 40 (IST) ==")
        ts = (await db.execute(text(
            "SELECT underlying, direction, status, "
            "(created_at at time zone 'Asia/Kolkata')::time(0), confidence "
            "FROM signals WHERE created_at >= CURRENT_DATE AND pattern_name='max_pain' "
            "ORDER BY created_at LIMIT 40"))).all()
        for r in ts:
            print(" ", r)
        print("\n== other patterns today for contrast ==")
        o = (await db.execute(text(
            "SELECT pattern_name, status, count(*) FROM signals "
            "WHERE created_at >= CURRENT_DATE GROUP BY 1,2 ORDER BY 1"))).all()
        for r in o:
            print(" ", r)

asyncio.run(go())
