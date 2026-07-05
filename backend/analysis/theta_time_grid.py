"""
EXHAUSTIVE INTRADAY TIMING GRID — short ATM straddle (30% SL), every
entry x exit 30-min window combination, real prices, IS/OOS.
This is the complete map the user's "after 2pm" question probed one cell of.
Multiple-testing discipline: ~78 cells scanned -> a cell only "passes" if
PF > 1.15 in BOTH eras independently.
"""
import asyncio, time, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd

LOT, STEP = 65, 50
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
SLIP = 0.005
BUCKETS = ["09:45", "10:15", "10:45", "11:15", "11:45", "12:15",
           "12:45", "13:15", "13:45", "14:15", "14:45", "15:15"]


def rnd50(x):
    return round(x / STEP) * STEP


def charges(et, xt):
    b = min(20.0, et * 0.0003) * 2 + min(20.0, xt * 0.0003) * 2
    return b + et * 0.001 + (et + xt) * 0.00053 + (b + (et + xt) * 0.00053) * 0.18 + xt * 0.00003


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
    for _ in range(3):
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
start = exps[0] - timedelta(days=10)
idx, cur = [], start
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)
by_day = defaultdict(dict)
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    by_day[ts.date()][ts.strftime("%H:%M")] = (ts, float(c[4]))
days = sorted(by_day)
split = days[int(len(days) * 0.6)]

contract_cache, cand_cache = {}, {}


def contracts(exp):
    if exp not in contract_cache:
        j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=IDX, expiry_date=str(exp))
        contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                               for r in (j or {}).get("data", [])}
    return contract_cache[exp]


def candles(key, exp):
    if key not in cand_cache:
        j = get(f"{BASE}/expired-instruments/historical-candle/{key}/30minute/{exp}/{exp - timedelta(days=30)}")
        cand_cache[key] = {datetime.fromisoformat(c[0]).replace(tzinfo=None): float(c[4])
                           for c in (j or {}).get("data", {}).get("candles", [])}
    return cand_cache[key]


# precompute per-day straddle marks per bucket (one ATM per day, chosen at 09:45)
marks = {}
for d in days:
    db = by_day[d]
    if "09:45" not in db:
        continue
    exp = next((e for e in exps if 0 <= (e - d).days <= 7), None)
    if exp is None:
        continue
    ts0, spot0 = db["09:45"]
    atm = float(rnd50(spot0))
    cmap = contracts(exp)
    kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
    if not kc or not kp:
        continue
    rc, rp = candles(kc, exp), candles(kp, exp)
    day_marks = {}
    for b in BUCKETS:
        if b not in db:
            continue
        ts = db[b][0]
        cv, pv = rc.get(ts), rp.get(ts)
        if cv is not None and pv is not None:
            day_marks[b] = cv + pv
    if len(day_marks) >= 10:
        marks[d] = day_marks

client.close()
print(f"days with full straddle marks: {len(marks)}\n")

results = []
for i_in, b_in in enumerate(BUCKETS[:-1]):
    for b_out in BUCKETS[i_in + 1:]:
        nets = {"IS": [], "OOS": []}
        for d, dm in marks.items():
            if b_in not in dm or b_out not in dm:
                continue
            credit = dm[b_in] * (1 - SLIP)
            # 30% SL scan between entry and exit buckets
            exit_v = None
            for b in BUCKETS[BUCKETS.index(b_in) + 1:BUCKETS.index(b_out) + 1]:
                if b not in dm:
                    continue
                if dm[b] >= credit * 1.3:
                    exit_v = dm[b] * (1 + SLIP)
                    break
            if exit_v is None:
                exit_v = dm[b_out] * (1 + SLIP)
            net = (credit - exit_v) * LOT - charges(credit * LOT, exit_v * LOT)
            nets["IS" if d <= split else "OOS"].append(net)
        row = {"in": b_in, "out": b_out}
        ok = True
        for era in ("IS", "OOS"):
            s = pd.Series(nets[era])
            if len(s) < 40:
                ok = False
                break
            w = s[s > 0]
            l = s[s <= 0]
            pf = w.sum() / abs(l.sum()) if len(l) else 99
            row[f"pf_{era}"] = round(pf, 2)
            row[f"net_{era}"] = round(s.sum())
            row[f"n_{era}"] = len(s)
        if ok:
            results.append(row)

r = pd.DataFrame(results)
r["both_pos"] = (r.pf_IS > 1.15) & (r.pf_OOS > 1.15)
print("=== cells passing BOTH-ERA PF > 1.15 (out of", len(r), "cells scanned) ===")
passing = r[r.both_pos].sort_values("pf_OOS", ascending=False)
if len(passing):
    print(passing.to_string(index=False))
else:
    print("NONE")
print("\n=== top 10 by OOS PF (regardless) ===")
print(r.sort_values("pf_OOS", ascending=False).head(10).to_string(index=False))
print("\n=== the user's cell (14:15 -> 15:15) ===")
print(r[(r["in"] == "14:15") & (r["out"] == "15:15")].to_string(index=False))
print("DONE")
