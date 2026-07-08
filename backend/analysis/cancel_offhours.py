"""Cancel trade groups entered outside 09:15-15:30 IST; reverse capital effects.
Groups: a2677440 (15:45 IST Jul-7), b3a7be0b + ce501e59 (09:00 Jul-7),
a1e87848 (09:00 Jul-8). Entry prices were previous-close/frozen quotes — no
real order could have filled there. Same precedent as the Saturday stale-price
cancellation."""
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

GROUPS = ("a2677440", "b3a7be0b", "ce501e59", "a1e87848")


async def go():
    async with AsyncSessionLocal() as db:
        legs = (await db.execute(text(
            "SELECT id, trade_group_id, action, entry_price, quantity, "
            "charges_entry, margin_blocked FROM trades "
            "WHERE status='OPEN' AND left(trade_group_id, 8) IN ('a2677440','b3a7be0b','ce501e59','a1e87848')"))).all()
        total_margin = total_cash = 0.0
        for _id, g, action, ep, qty, ch, mb in legs:
            ch = ch or 0.0
            cash = (ep * qty - ch) if action == "SELL" else (-(ep * qty) - ch)
            total_cash += cash
            total_margin += (mb or 0.0) + ch
        print(f"legs={len(legs)} margin+charges to release={total_margin:.0f} entry cash to reverse={total_cash:.0f}")

        await db.execute(text(
            "UPDATE trades SET status='CANCELLED', "
            "exit_reason='cancelled_outside_market_hours', unrealized_pnl=0, pnl=0 "
            "WHERE status='OPEN' AND left(trade_group_id, 8) IN "
            "('a2677440','b3a7be0b','ce501e59','a1e87848')"))
        # Portfolio reversal: entry did capital_deployed += margin; capital_current += cash - margin
        await db.execute(text(
            "UPDATE portfolios SET capital_deployed = GREATEST(0, capital_deployed - :m), "
            "capital_current = capital_current - :c + :m WHERE mode='paper'"),
            {"m": total_margin, "c": total_cash})
        await db.commit()
        print("cancelled + portfolio reversed")

    # Release Redis heat
    from app.core.risk.gate import record_deployed
    record_deployed(-total_margin)
    print(f"redis heat released: -{total_margin:.0f}")

asyncio.run(go())
