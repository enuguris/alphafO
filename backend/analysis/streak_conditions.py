"""What conditions precede 4+ up-day NIFTY streaks? Base-rate comparison, 2011-2026."""
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
df["up"] = c > c.shift(1)
df["ret5"] = c.pct_change(5) * 100
df["ret20"] = c.pct_change(20) * 100
df["dd52"] = (c / c.rolling(250, min_periods=50).max() - 1) * 100  # % off 52w high
df["above200"] = c > c.rolling(200, min_periods=50).mean()
df["month"] = df.d.dt.month

# mark streak-start days (first up day of a 4+ run)
df["streak_start"] = False
i = 1
while i < len(df):
    if df.up[i]:
        j = i
        while j + 1 < len(df) and df.up[j + 1]:
            j += 1
        if j - i + 1 > 3:
            df.loc[i, "streak_start"] = True
        i = j + 1
    else:
        i += 1

starts = df[df.streak_start]
base = df[df.index > 250]  # skip warmup
print(f"streak starts: {len(starts)}   base days: {len(base)}   base rate: {len(starts)/len(base)*100:.1f}%\n")

# condition on the day BEFORE the streak starts
pre = df.shift(1).loc[starts.index]
allpre = df.shift(1).loc[base.index]

print("=== state on day before streak start vs all days (medians) ===")
for col, label in [("ret5", "prior 5-day return %"), ("ret20", "prior 20-day return %"),
                   ("dd52", "% below 52-week high")]:
    print(f"{label:26s} before-streak: {pre[col].median():6.2f}   all-days: {allpre[col].median():6.2f}")
print(f"{'above 200-DMA %':26s} before-streak: {pre.above200.mean()*100:5.0f}%   all-days: {allpre.above200.mean()*100:5.0f}%")

# conditional probabilities: P(streak starts | condition)
print("\n=== P(a 4+ streak starts on a given day | condition) ===")
conds = {
    "prior 5d return < -2%": allpre.ret5 < -2,
    "prior 5d return -2..0%": (allpre.ret5 >= -2) & (allpre.ret5 < 0),
    "prior 5d return 0..+2%": (allpre.ret5 >= 0) & (allpre.ret5 < 2),
    "prior 5d return > +2%": allpre.ret5 >= 2,
    ">10% below 52w high": allpre.dd52 < -10,
    "5-10% below 52w high": (allpre.dd52 >= -10) & (allpre.dd52 < -5),
    "<5% below 52w high": allpre.dd52 >= -5,
    "below 200-DMA": ~allpre.above200.astype(bool),
    "above 200-DMA": allpre.above200.astype(bool),
}
ss = df.streak_start.loc[base.index]
for name, mask in conds.items():
    m = mask.fillna(False)
    p = ss[m].mean() * 100 if m.sum() else float("nan")
    print(f"{name:26s} {p:5.2f}%   (n={m.sum()})")

print("\n=== streak starts by month ===")
print(starts.month.value_counts().sort_index().to_string())

# gain size conditional on prior 5d return
starts2 = starts.copy()
gains = []
for idx in starts.index:
    j = idx
    while j + 1 < len(df) and df.up[j + 1]:
        j += 1
    gains.append(c[j] - c[idx - 1])
starts2["gain"] = gains
starts2["pre5"] = df.shift(1).ret5.loc[starts.index]
big = starts2[starts2.pre5 < -2]
small = starts2[starts2.pre5 >= 0]
print(f"\nstreaks after 5d drop >2%:  n={len(big)}  median gain {big.gain.median():.0f} pts")
print(f"streaks after flat/up 5d:   n={len(small)}  median gain {small.gain.median():.0f} pts")
print("DONE")
