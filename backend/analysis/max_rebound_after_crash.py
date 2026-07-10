"""After a >2% down day, what's the max intraday bounce/rebound?
Also: how high did it recover? Real Upstox 30-min data."""
import asyncio, time
from datetime import date, timedelta, datetime
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

def get(url, **params):
    for _ in range(4):
        try:
            r = client.get(url, params=params or None)
            if r.status_code == 429:
                time.sleep(1); continue
            return r.json() if r.status_code == 200 else None
        except Exception:
            time.sleep(0.5)
    return None


exps = sorted(date.fromisoformat(x) for x in
              (get(f"{BASE}/expired-instruments/expiries", instrument_key=IDX) or {}).get("data", []))
idx, cur = [], exps[0] - timedelta(days=12)
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)

by_day = {}
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    d = ts.date()
    t = ts.strftime("%H:%M")
    if d not in by_day:
        by_day[d] = {}
    by_day[d][t] = {"o": float(c[1]), "h": float(c[2]), "l": float(c[3]), "c": float(c[4])}

days = sorted(by_day)
closes = {}
for d in days:
    bar = by_day[d].get("15:15") or by_day[d].get("14:45")
    if bar:
        closes[d] = bar["c"]

rows = []
for i in range(2, len(days)):
    d, d_prev, d_2d_ago = days[i], days[i-1], days[i-2]
    c_prev = closes.get(d_prev)
    c_2d_ago = closes.get(d_2d_ago)
    if not c_prev or not c_2d_ago or "09:15" not in by_day[d]:
        continue

    prev_ret = c_prev / c_2d_ago - 1
    if prev_ret > -0.02:  # only >2% falls
        continue

    # intraday rebound on the next day
    open_price = by_day[d]["09:15"]["o"]
    intraday_low = min(bar["l"] for bar in by_day[d].values())
    intraday_high = max(bar["h"] for bar in by_day[d].values())

    # recovery from low to high
    recovery_pct = intraday_high / intraday_low - 1
    recovery_pts = intraday_high - intraday_low

    # how much recovered vs the overnight gap
    overnight_gap = open_price - intraday_low
    pct_of_gap_recovered = (intraday_high - intraday_low) / overnight_gap - 1 if overnight_gap > 0 else 0

    rows.append({
        "date": d,
        "overnight_fall_pct": prev_ret * 100,
        "open": open_price,
        "low": intraday_low,
        "high": intraday_high,
        "gap_pts": overnight_gap,
        "recovery_pct": recovery_pct * 100,
        "recovery_pts": recovery_pts,
        "pct_of_gap_recovered": pct_of_gap_recovered * 100,
    })

df = pd.DataFrame(rows)
print(f"days with >2% overnight fall: {len(df)}\n")
print(df.sort_values("recovery_pct", ascending=False).to_string(index=False))
print(f"\n=== SUMMARY ===")
print(f"Total occurrences: {len(df)}")
print(f"Avg overnight fall: {df.overnight_fall_pct.mean():.2f}%")
print(f"Avg intraday recovery (low→high): {df.recovery_pct.mean():.2f}%")
print(f"Max intraday recovery: {df.recovery_pct.max():.2f}% ({df.recovery_pts.max():.0f} pts)")
print(f"Min intraday recovery (dead bounce): {df.recovery_pct.min():.2f}% ({df.recovery_pts.min():.0f} pts)")
print(f"\nGap recovery:")
print(f"Avg % of overnight gap recovered: {df.pct_of_gap_recovered.mean():.0f}%")
print(f"Max % of overnight gap recovered: {df.pct_of_gap_recovered.max():.0f}%")
print(f"Min % of overnight gap recovered: {df.pct_of_gap_recovered.min():.0f}%")
print(f"\nP(recover >50% of gap): {len(df[df.pct_of_gap_recovered > 50]) / len(df) * 100:.0f}%")
print(f"P(recover >75% of gap): {len(df[df.pct_of_gap_recovered > 75]) / len(df) * 100:.0f}%")
print(f"P(full gap recovery, then rally): {len(df[df.pct_of_gap_recovered > 100]) / len(df) * 100:.0f}%")
print("DONE")
