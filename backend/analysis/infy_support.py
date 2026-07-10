"""INFY support analysis: where is real support, and is a 950 short put a
calculated risk given the 52w low ~982? Real Upstox equity daily bars."""
import asyncio, time
from datetime import date, timedelta
import httpx
import pandas as pd
import numpy as np

BASE = "https://api.upstox.com/v2"
INFY_EQ = "NSE_EQ|INE009A01021"


async def get_token():
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.core.encryption import decrypt
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        cfg = (await db.execute(select(KiteConfig).limit(1))).scalar_one_or_none()
    return decrypt(cfg.upstox_access_token_enc)

token = asyncio.new_event_loop().run_until_complete(get_token())
c = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})
j = c.get(f"{BASE}/historical-candle/{INFY_EQ}/day/{date.today()}/{date.today()-timedelta(days=760)}").json()
rows = list(reversed(j.get("data", {}).get("candles", [])))
df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v", "oi"])
df["d"] = pd.to_datetime(df.ts.str[:10]).dt.date
for k in ("o", "h", "l", "c"):
    df[k] = pd.to_numeric(df[k])
spot = df.c.iloc[-1]

# 52-week window
last1y = df[pd.to_datetime(df.ts) >= (pd.to_datetime(df.ts.iloc[-1]) - pd.Timedelta(days=365))]
lo52 = last1y.l.min(); hi52 = last1y.h.max()
lo52d = last1y.loc[last1y.l.idxmin(), "d"]

print(f"INFY spot: {spot:.1f}")
print(f"52w high/low: {hi52:.0f} / {lo52:.0f} (low on {lo52d})")
print(f"strike 950 is {(950/spot-1)*100:+.1f}% from spot, {(950/lo52-1)*100:+.1f}% vs 52w low")
print(f"strike 982 (52w low) is {(982/spot-1)*100:+.1f}% from spot\n")

# how often has INFY closed below these levels in 2y
for lvl in (1000, 982, 970, 950, 920):
    n = (df.c < lvl).sum()
    print(f"  days closed < {lvl}: {n}/{len(df)} ({n/len(df)*100:.1f}%)")

# closest approach to 950 (lowest low ever in window)
print(f"\nlowest low in 2y: {df.l.min():.0f} on {df.loc[df.l.idxmin(),'d']}")

# forward 18-trading-day move distribution → P(close below 950 / 982 in ~18d from any day)
H = 18
df["fwd_min"] = df.l.shift(-1).rolling(H).min().shift(-(H-1))
base = df.dropna(subset=["fwd_min"])
# scale to current spot: P(spot falls to X within 18d) using historical 18d drawdown %
dd = base.fwd_min / base.c - 1     # worst 18d drawdown fraction
need_950 = 950/spot - 1
need_982 = 982/spot - 1
print(f"\n18-trading-day forward drawdown (from any day, {len(base)} samples):")
print(f"  median worst drawdown: {dd.median()*100:.1f}%   5th pctile: {dd.quantile(0.05)*100:.1f}%")
print(f"  P(drawdown reaches {need_950*100:.1f}% → touches 950): {(dd <= need_950).mean()*100:.0f}%")
print(f"  P(drawdown reaches {need_982*100:.1f}% → touches 982): {(dd <= need_982).mean()*100:.0f}%")

# support zones: local minima (price bounced) via 10-day troughs
df["is_trough"] = (df.l == df.l.rolling(21, center=True).min())
troughs = df[df.is_trough].sort_values("d").tail(8)
print("\nrecent support pivots (21-day troughs):")
for _, r in troughs.iterrows():
    print(f"  {r.d}: low {r.l:.0f}")
print("DONE")
