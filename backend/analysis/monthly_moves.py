"""Max monthly NIFTY gain/fall in points — Upstox daily candles, max history."""
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
df = df.sort_values("d").set_index("d")
print(f"days: {len(df)}  range: {df.index[0].date()} -> {df.index[-1].date()}\n")

m = df.resample("ME").agg(first_open=("o", "first"), high=("h", "max"),
                          low=("l", "min"), last_close=("c", "last"))
m["close_chg"] = m.last_close - m.first_open              # month open -> close
m["max_rise"] = m.high - m.low                            # intra-month range (low->high)
m["pct"] = (m.close_chg / m.first_open * 100).round(1)
m = m.dropna()

print("=== 10 biggest monthly GAINS (open->close, points) ===")
print(m.nlargest(10, "close_chg")[["first_open", "last_close", "close_chg", "pct"]].round(0).to_string())
print("\n=== 10 biggest monthly FALLS ===")
print(m.nsmallest(10, "close_chg")[["first_open", "last_close", "close_chg", "pct"]].round(0).to_string())
print("\n=== 10 biggest intra-month RANGES (high-low, points) ===")
print(m.nlargest(10, "max_rise")[["low", "high", "max_rise"]].round(0).to_string())
print("\n=== recent 24 months ===")
print(m.tail(24)[["first_open", "last_close", "close_chg", "pct", "max_rise"]].round(0).to_string())
print("\nabs monthly close-move: median", round(m.close_chg.abs().median()),
      " p90", round(m.close_chg.abs().quantile(0.9)),
      " max", round(m.close_chg.abs().max()))
print("DONE")
