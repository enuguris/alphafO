"""P(NIFTY rallies this week / this month) — historical base rates conditioned
on states similar to today. 2011-2026 daily data."""
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
c = df.c

df["ret5"] = c.pct_change(5) * 100
df["ret20"] = c.pct_change(20) * 100
df["dd52"] = (c / c.rolling(250, min_periods=50).max() - 1) * 100
df["rv20"] = (c.pct_change().rolling(20).std() * (252 ** 0.5) * 100)  # realized vol proxy for VIX
# forward returns
df["fwd5"] = c.shift(-5) / c - 1
df["fwd21"] = c.shift(-21) / c - 1
df["fwd5_pts"] = c.shift(-5) - c
df["fwd21_pts"] = c.shift(-21) - c

base = df.dropna(subset=["fwd5", "fwd21", "dd52", "rv20"]).iloc[250:]
cur_state = df.iloc[-1]
print(f"today: close={c.iloc[-1]:.0f} ret5={cur_state.ret5:.2f}% ret20={cur_state.ret20:.2f}% "
      f"dd52={cur_state.dd52:.1f}% rv20={cur_state.rv20:.1f}%\n")

def stats(sub, label):
    if len(sub) < 30:
        print(f"{label:44s} n={len(sub)} (too few)")
        return
    for h, col, pcol in [("week", "fwd5", "fwd5_pts"), ("month", "fwd21", "fwd21_pts")]:
        up = (sub[col] > 0).mean() * 100
        big = (sub[col] > 0.02).mean() * 100
        med = sub[pcol].median()
        p90 = sub[pcol].quantile(0.9)
        print(f"{label:38s} {h:5s}: P(up)={up:4.0f}%  P(>+2%)={big:4.0f}%  median {med:+5.0f} pts  p90 {p90:+5.0f}")
    print()

stats(base, "ALL DAYS (unconditional)")
m = base[(base.ret5.between(cur_state.ret5 - 1.5, cur_state.ret5 + 1.5)) &
         (base.ret20.between(cur_state.ret20 - 3, cur_state.ret20 + 3))]
stats(m, f"similar momentum (5d~{cur_state.ret5:.1f}%, 20d~{cur_state.ret20:.1f}%)")
m2 = base[base.dd52.between(cur_state.dd52 - 3, cur_state.dd52 + 3)]
stats(m2, f"similar drawdown ({cur_state.dd52:.0f}% off 52w high)")
m3 = base[base.rv20 < 12]
stats(m3, "low realized vol (<12%, like now)")
m4 = base[(base.ret5.between(cur_state.ret5 - 1.5, cur_state.ret5 + 1.5)) &
          (base.dd52.between(cur_state.dd52 - 4, cur_state.dd52 + 4)) &
          (base.rv20 < 14)]
stats(m4, "ALL THREE combined (closest analogue)")
print("DONE")
