"""Snapshot NIFTY option-chain OI walls to market_data/oi_walls/YYYY-MM-DD.json
and diff against the previous snapshot. Run daily to see walls build/unwind.

Usage: python analysis/oi_walls_snapshot.py [expiry_YYYY-MM-DD]
"""
import asyncio, sys, json
from datetime import date
from pathlib import Path

EXPIRY = sys.argv[1] if len(sys.argv) > 1 else "2026-07-28"
OUT = Path("/app/market_data/oi_walls")
OUT.mkdir(parents=True, exist_ok=True)


async def fetch():
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.core.encryption import decrypt
    from sqlalchemy import select
    import httpx

    async with AsyncSessionLocal() as db:
        cfg = (await db.execute(select(KiteConfig).limit(1))).scalar_one_or_none()
    token = decrypt(cfg.upstox_access_token_enc)
    h = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30, headers=h) as c:
        r = await c.get("https://api.upstox.com/v2/market-quote/ltp",
                        params={"instrument_key": "NSE_INDEX|Nifty 50"})
        spot = next(iter(r.json().get("data", {}).values()), {}).get("last_price")
        r = await c.get("https://api.upstox.com/v2/option/chain",
                        params={"instrument_key": "NSE_INDEX|Nifty 50", "expiry_date": EXPIRY})
        rows = {}
        for row in r.json().get("data", []):
            k = int(row.get("strike_price"))
            ce = row.get("call_options", {}).get("market_data", {})
            pe = row.get("put_options", {}).get("market_data", {})
            rows[k] = {"coi": int(ce.get("oi", 0)), "poi": int(pe.get("oi", 0)),
                       "cl": ce.get("ltp", 0), "pl": pe.get("ltp", 0)}
        return spot, rows


def snap_date():
    # avoid Date.now issues — derive from the newest snapshot or use CLI arg
    return date.today().isoformat()


spot, rows = asyncio.get_event_loop().run_until_complete(fetch())
today = snap_date()
(OUT / f"{today}.json").write_text(json.dumps({"spot": spot, "expiry": EXPIRY, "rows": rows}))

# Load previous snapshot for diff
prev_files = sorted(OUT.glob("*.json"))
prev = None
for f in reversed(prev_files):
    if f.stem != today:
        prev = json.loads(f.read_text()); prev_day = f.stem; break

near = sorted(k for k in rows if abs(k - spot) <= 900)
print(f"NIFTY OI WALLS — spot {spot}, expiry {EXPIRY}, {today}\n")

# Top walls
calls = sorted(((rows[k]["coi"], k) for k in rows if k >= spot), reverse=True)[:4]
puts = sorted(((rows[k]["poi"], k) for k in rows if k <= spot), reverse=True)[:4]
print("RESISTANCE (top call OI above spot):")
for oi, k in calls:
    print(f"  {k}: {oi/1e6:.2f}M")
print("SUPPORT (top put OI below spot):")
for oi, k in puts:
    print(f"  {k}: {oi/1e6:.2f}M")

if prev:
    print(f"\nWALL CHANGE vs {prev_day} (Δ OI in millions, near-spot strikes):")
    print("STRIKE   CALL_OI    ΔCALL     PUT_OI    ΔPUT")
    pr = prev["rows"]
    for k in near:
        c_now = rows[k]["coi"]; p_now = rows[k]["poi"]
        c_prev = pr.get(str(k), pr.get(k, {})).get("coi", 0) if pr else 0
        p_prev = pr.get(str(k), pr.get(k, {})).get("poi", 0) if pr else 0
        dc = (c_now - c_prev) / 1e6
        dp = (p_now - p_prev) / 1e6
        flag = ""
        if abs(dc) > 0.5: flag += " CE" + ("+" if dc > 0 else "-")
        if abs(dp) > 0.5: flag += " PE" + ("+" if dp > 0 else "-")
        print(f"{k:6d}  {c_now/1e6:6.2f}M  {dc:+6.2f}  {p_now/1e6:6.2f}M  {dp:+6.2f}{flag}")
else:
    print("\n(no previous snapshot — baseline saved; run again tomorrow to diff)")
print("\nDONE")
