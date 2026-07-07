"""NIFTY consecutive up-day streaks (>3 days) — count per year, max points gained."""
import asyncio, time
from datetime import date, timedelta
import httpx
import pandas as pd

BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"


async def get_token():
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.core.encryption import decrypt
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        cfg = (await db.execute(select(KiteConfig).limit(1))).scalar_one_or_none()
    return decrypt(cfg.upstox_access_token_enc)

token = asyncio.new_event_loop().run_until_complete(get_token())
client = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})
candles = []
cur = date(2011, 1, 1)
while cur < date.today():
    to = min(cur + timedelta(days=364), date.today())
    for _ in range(3):
        r = client.get(f"{BASE}/historical-candle/{IDX}/day/{to}/{cur}")
        if r.status_code == 429:
            time.sleep(1); continue
        if r.status_code == 200:
            candles += r.json().get("data", {}).get("candles", [])
        break
    cur = to + timedelta(days=1)
client.close()

df = pd.DataFrame(candles, columns=["ts", "o", "h", "l", "c", "v", "oi"])
df["d"] = pd.to_datetime(df.ts.str[:10])
df = df.sort_values("d").reset_index(drop=True)
df["up"] = df.c > df.c.shift(1)

streaks = []
i = 1
while i < len(df):
    if df.up[i]:
        j = i
        while j + 1 < len(df) and df.up[j + 1]:
            j += 1
        n = j - i + 1
        if n > 3:
            gain = df.c[j] - df.c[i - 1]
            streaks.append({"start": df.d[i].date(), "end": df.d[j].date(),
                            "days": n, "points": round(gain),
                            "pct": round(gain / df.c[i - 1] * 100, 1)})
        i = j + 1
    else:
        i += 1

s = pd.DataFrame(streaks)
s["year"] = pd.to_datetime(s.start).dt.year
print(f"total streaks of 4+ up days since 2011: {len(s)}\n")
print("=== per year: count, best streak points ===")
print(s.groupby("year").agg(count=("days", "size"), max_days=("days", "max"),
                            max_points=("points", "max")).to_string())
print("\n=== top 10 streaks by points gained ===")
print(s.nlargest(10, "points").to_string(index=False))
print("\n=== longest streaks ===")
print(s.nlargest(5, "days").to_string(index=False))
print(f"\navg points per 4+ day streak: {round(s.points.mean())}  median: {round(s.points.median())}")
print("DONE")
