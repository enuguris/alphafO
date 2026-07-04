"""
Follow-up: the mined small-gap-fill regularity (88-89% same-day fill, stable
IS/OOS) — can it be TRADED after costs?
Rule: if overnight |gap| is 5-25bp, at 09:15 open fade the gap:
  target = yesterday's close, stop = 2x the gap distance, exit 15:15 latest.
Tested on NIFTY futures points (1 lot = 65); costs ~2.5 pts round trip
(futures brokerage+slippage). IS/OOS split preserved.
"""
import asyncio, time, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import numpy as np
import pandas as pd

BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
LOT = 65
COST_PTS = 2.5   # futures round-trip cost+slippage in index points


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


def get(url):
    for _ in range(3):
        try:
            r = client.get(url)
            if r.status_code == 429:
                time.sleep(1); continue
            return r.json() if r.status_code == 200 else None
        except Exception:
            time.sleep(0.5)
    return None


start = date(2024, 9, 20)
idx, cur = [], start
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)

rows = []
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    rows.append({"ts": ts, "d": ts.date(), "o": float(c[1]), "h": float(c[2]),
                 "l": float(c[3]), "c": float(c[4])})
df = pd.DataFrame(rows).sort_values("ts")
day_grp = {d: g.reset_index(drop=True) for d, g in df.groupby("d")}
days = sorted(day_grp)
split = days[int(len(days) * 0.6)]

trades = []
prev = None
for d in days:
    g = day_grp[d]
    if prev is not None and len(g) >= 3:
        pc = day_grp[prev].iloc[-1].c
        op = g.iloc[0].o
        gap = op - pc
        gap_bp = abs(gap) / pc * 10000
        if 5 <= gap_bp <= 25:
            # fade: short if gap up, long if gap down; target pc; stop 2x gap
            direction = -1 if gap > 0 else 1        # position sign on index
            target = pc
            stop = op + (gap * 2)                    # 2x gap beyond entry, adverse
            pnl = None
            for k in range(len(g)):
                bar = g.iloc[k]
                hit_t = (bar.l <= target <= bar.h)
                hit_s = (bar.l <= stop <= bar.h)
                if k == 0:
                    # entry bar: conservative — stop checked first
                    if hit_s:
                        pnl = direction * (stop - op)
                        break
                    if hit_t:
                        pnl = direction * (target - op)
                        break
                else:
                    if hit_s and hit_t:
                        pnl = direction * (stop - op)   # worst case first
                        break
                    if hit_s:
                        pnl = direction * (stop - op)
                        break
                    if hit_t:
                        pnl = direction * (target - op)
                        break
            if pnl is None:
                pnl = direction * (g.iloc[-1].c - op)
            trades.append({"d": d, "pnl_pts": pnl - COST_PTS, "gap_bp": gap_bp})
    prev = d

t = pd.DataFrame(trades)
t["net"] = t.pnl_pts * LOT
for era, sub in (("IS", t[t.d <= split]), ("OOS", t[t.d > split]), ("ALL", t)):
    if not len(sub):
        continue
    w, l = sub[sub.net > 0], sub[sub.net <= 0]
    pf = w.net.sum() / abs(l.net.sum()) if len(l) else 99
    print(f"{era:3}: n={len(sub):3d} | WIN {len(w)/len(sub)*100:5.1f}% | PF {pf:5.2f} | "
          f"net Rs{sub.net.sum():>8,.0f} | avg Rs{sub.net.mean():>6,.0f} | worst Rs{sub.net.min():>7,.0f}")
client.close()
print("DONE")
