"""P(rebound) over next 14 trading days after a 1.25-2% down day in low vol.
Also: strangle strike math — P(breach 23600 PE / 24850 CE from 23895)."""
import asyncio, time
from datetime import date, timedelta
import httpx
import pandas as pd

BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
H = 14  # trading days to Jul 28


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
df["ret1"] = c.pct_change()
df["rv20"] = c.pct_change().rolling(20).std() * (252 ** 0.5) * 100
# forward H-day stats
df["fwd_close"] = c.shift(-H) / c - 1
df["fwd_min"] = (df.l.shift(-1).rolling(H).min().shift(-(H - 1))) / c - 1
df["fwd_max"] = (df.h.shift(-1).rolling(H).max().shift(-(H - 1))) / c - 1

base = df.dropna(subset=["fwd_close", "fwd_min", "fwd_max", "rv20"]).iloc[250:]

# strangle geometry from today: spot 23895, PE 23600 (-1.24%), CE 24850 (+4.00%)
PE_D, CE_D = -0.0124, 0.0400

def stats(sub, label):
    if len(sub) < 25:
        print(f"{label:46s} n={len(sub)} (too few)"); return
    up = (sub.fwd_close > 0).mean() * 100
    reb2 = (sub.fwd_close > 0.02).mean() * 100
    pe_touch = (sub.fwd_min <= PE_D).mean() * 100
    pe_settle = (sub.fwd_close <= PE_D).mean() * 100
    ce_touch = (sub.fwd_max >= CE_D).mean() * 100
    ce_settle = (sub.fwd_close >= CE_D).mean() * 100
    print(f"{label:46s} n={len(sub):4d} P(up)={up:3.0f}% P(reb>2%)={reb2:3.0f}% "
          f"med={sub.fwd_close.median()*100:+5.2f}% | PE touch {pe_touch:3.0f}% settle {pe_settle:3.0f}% "
          f"| CE touch {ce_touch:3.0f}% settle {ce_settle:3.0f}%")

print(f"horizon: {H} trading days | PE 23600 = {PE_D*100:.2f}% | CE 24850 = +{CE_D*100:.2f}%\n")
stats(base, "ALL days")
stats(base[(base.ret1 <= -0.0125) & (base.ret1 > -0.02)], "after 1.25-2% down day (today)")
stats(base[(base.ret1 <= -0.0125) & (base.ret1 > -0.02) & (base.rv20 < 14)], "  ...AND low vol regime (rv20<14)")
stats(base[base.ret1 <= -0.02], "after >2% crash day (worse than today)")
print("DONE")
