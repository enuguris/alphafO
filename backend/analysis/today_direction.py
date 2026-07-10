"""One-day-ahead direction read: recent trend + conditional base rates for
today's exact setup (prior day down + closed at/near low, low VIX, Wednesday)."""
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

print("=== last 10 sessions ===")
last10 = df.tail(10).copy()
last10["chg"] = last10.c.diff()
last10["chg_pct"] = last10.c.pct_change() * 100
last10["close_pos"] = (last10.c - last10.l) / (last10.h - last10.l)  # 0=at low, 1=at high
print(last10[["d", "c", "chg", "chg_pct", "close_pos"]].round(2).to_string(index=False))

c = df.c
df["ret1"] = c.pct_change()
df["ret5"] = c.pct_change(5) * 100
df["close_pos"] = (df.c - df.l) / (df.h - df.l)
df["down_at_low"] = (df.ret1 < 0) & (df.close_pos < 0.1)
df["fwd1"] = c.shift(-1) / c - 1
df["fwd1_pts"] = c.shift(-1) - c
df["dow"] = df.d.dt.dayofweek
df["rv20"] = c.pct_change().rolling(20).std() * (252 ** 0.5) * 100

base = df.dropna(subset=["fwd1", "rv20"]).iloc[250:]

def stats(sub, label):
    s = sub.fwd1_pts
    if len(s) < 30:
        print(f"{label:52s} n={len(s)} (too few)"); return
    up = (sub.fwd1 > 0).mean() * 100
    print(f"{label:52s} n={len(s):4d} P(next day up)={up:3.0f}% median={s.median():+6.1f} "
          f"p10={s.quantile(.1):+7.0f} p90={s.quantile(.9):+7.0f}")

stats(base, "ALL days")
stats(base[base.down_at_low], "prior day DOWN and closed at low (<10% of range)")
stats(base[base.down_at_low & (base.rv20 < 13)], "  ...AND low vol (rv20<13, like now)")
stats(base[base.down_at_low & (base.dow == 1)], "  ...AND that day was a Tuesday (today=Wed)")
stats(base[(base.ret1 < 0)], "prior day down (any close position)")
stats(base[(base.ret1 > 0)], "prior day up")
stats(base[base.dow == 2], "all Wednesdays")
print("DONE")
