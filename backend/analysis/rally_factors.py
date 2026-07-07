"""More factors for the rally question: India VIX level, PCR, FII flows,
July seasonality, upcoming events. Uses cached market_data + Upstox daily."""
import asyncio, time
from datetime import date, timedelta
from pathlib import Path
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
df["fwd21"] = c.shift(-21) / c - 1
df["fwd21_pts"] = c.shift(-21) - c
df["month"] = df.d.dt.month

# ── 1. July seasonality ──────────────────────────────────────────────────────
mret = df.set_index("d").c.resample("ME").last().pct_change() * 100
mret = mret.dropna()
print("=== calendar-month seasonality (2011-2026, median return % / P(up)) ===")
for mo in range(1, 13):
    s = mret[mret.index.month == mo]
    print(f"  {'JFMAMJJASOND'[mo-1]}{mo:02d}: median {s.median():+5.2f}%  P(up) {(s>0).mean()*100:3.0f}%  n={len(s)}")

# ── 2. India VIX level (real, not realized proxy) ───────────────────────────
vixp = Path("/app/market_data/india_vix.csv")
vix = pd.read_csv(vixp)
vix.columns = [x.strip().lower() for x in vix.columns]
dcol = [x for x in vix.columns if "date" in x][0]
vcol = [x for x in vix.columns if x != dcol][0]
vix["d"] = pd.to_datetime(vix[dcol])
vix = vix[["d", vcol]].rename(columns={vcol: "vix"}).sort_values("d")
m = pd.merge_asof(df[["d", "fwd21", "fwd21_pts"]], vix, on="d")
m = m.dropna()
cur_vix = vix.vix.iloc[-1]
print(f"\n=== forward 21d by India VIX band (today VIX={cur_vix:.1f}) ===")
for lo, hi in [(0, 12), (12, 14), (14, 17), (17, 22), (22, 99)]:
    s = m[(m.vix >= lo) & (m.vix < hi)]
    if len(s) > 50:
        print(f"  VIX {lo:>2}-{hi:<2}: P(up)={(s.fwd21>0).mean()*100:3.0f}%  "
              f"P(>+2%)={(s.fwd21>0.02).mean()*100:3.0f}%  P(<-2%)={(s.fwd21<-0.02).mean()*100:3.0f}%  "
              f"median {s.fwd21_pts.median():+5.0f} pts  n={len(s)}")

# ── 3. PCR current + conditional if history depth allows ────────────────────
try:
    pcr = pd.read_csv("/app/market_data/pcr_NIFTY.csv")
    pcr.columns = [x.strip().lower() for x in pcr.columns]
    pc = [x for x in pcr.columns if "pcr" in x][0]
    dc = [x for x in pcr.columns if "date" in x][0]
    pcr["d"] = pd.to_datetime(pcr[dc])
    pcr = pcr.sort_values("d")
    print(f"\n=== PCR ===  latest {pcr[pc].iloc[-1]:.2f} on {pcr.d.iloc[-1].date()}  "
          f"(history {len(pcr)} days, 30d range {pcr[pc].tail(30).min():.2f}-{pcr[pc].tail(30).max():.2f})")
    mp = pd.merge_asof(df[["d", "fwd21"]], pcr[["d", pc]], on="d").dropna()
    if len(mp) > 200:
        for lo, hi in [(0, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 9)]:
            s = mp[(mp[pc] >= lo) & (mp[pc] < hi)]
            if len(s) > 30:
                print(f"  PCR {lo}-{hi}: P(up 21d)={(s.fwd21>0).mean()*100:3.0f}%  n={len(s)}")
except Exception as e:
    print(f"\nPCR: {e}")

# ── 4. FII net flows, last 10 sessions ───────────────────────────────────────
try:
    fii = pd.read_csv("/app/market_data/fii_fo.csv")
    print(f"\n=== FII F&O net (₹ cr), last 10 rows ===")
    print(fii.tail(10).to_string(index=False))
except Exception as e:
    print(f"\nFII: {e}")

# ── 5. Upcoming events ────────────────────────────────────────────────────────
try:
    from app.core.options.event_calendar import get_upcoming_events
    ev = get_upcoming_events(days=30)
    print("\n=== events next 30 days ===")
    for e in ev:
        print(f"  {e}")
except Exception as e:
    print(f"\nevents: {e}")
print("DONE")
