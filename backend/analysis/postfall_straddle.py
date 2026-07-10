"""Test selling ATM straddle the morning after a >=1.25% down day.
Real Upstox expired 30-min data, 10 years, managed exits (TP 50% credit / SL 2x / expiry).
What stop rule survives? Is this more profitable than the bear-call alternative?
"""
import asyncio, time
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd

LOT, STEP, SLIP = 65, 50, 0.005
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


def rnd50(x):
    return round(x / STEP) * STEP


def rt_charges(entry_val, exit_val):
    b = min(20.0, entry_val * 0.0003) * 2 + min(20.0, exit_val * 0.0003) * 2
    txn = (entry_val + exit_val) * 0.00053
    stt = entry_val * 0.001
    return b + txn + stt + (b + txn) * 0.18


exps = sorted(date.fromisoformat(x) for x in
              (get(f"{BASE}/expired-instruments/expiries", instrument_key=IDX) or {}).get("data", []))
print(f"expiries found: {len(exps)}", flush=True)
if not exps:
    print("ERROR: no expiries returned from Upstox API")
    exit(1)
idx, cur = [], exps[0] - timedelta(days=12)
print(f"fetching candles from {cur} to today...", flush=True)
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    n = len((j or {}).get("data", {}).get("candles", []))
    idx += (j or {}).get("data", {}).get("candles", [])
    print(f"  {cur} to {to}: {n} candles", flush=True)
    cur = to + timedelta(days=1)
print(f"total candles: {len(idx)}", flush=True)
by_day = defaultdict(dict)
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    by_day[ts.date()][ts.strftime("%H:%M")] = float(c[4])
days = sorted(by_day)
closes = {d: by_day[d].get("15:15") or by_day[d].get("14:45") for d in days}
print(f"trading days with data: {len(days)}", flush=True)

contract_cache, cand_cache = {}, {}


def contracts(exp):
    if exp not in contract_cache:
        j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=IDX, expiry_date=str(exp))
        contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                               for r in (j or {}).get("data", [])}
    return contract_cache[exp]


def series(exp, k, ot):
    ck = contracts(exp).get((float(k), ot))
    if not ck:
        return {}
    if ck not in cand_cache:
        j = get(f"{BASE}/expired-instruments/historical-candle/{ck}/30minute/{exp}/{exp - timedelta(days=28)}")
        cand_cache[ck] = {(datetime.fromisoformat(c[0]).replace(tzinfo=None).date(),
                           datetime.fromisoformat(c[0]).replace(tzinfo=None).strftime("%H:%M")): float(c[4])
                          for c in (j or {}).get("data", {}).get("candles", [])}
    return cand_cache[ck]


def straddle_trade(d, exp, strike, tp_pct=50, sl_pct=200):
    """Sell ATM straddle at d 09:45; managed to expiry with TP / SL."""
    ce, pe = series(exp, strike, "CE"), series(exp, strike, "PE")
    ce_p, pe_p = ce.get((d, "09:45")), pe.get((d, "09:45"))
    if ce_p is None or pe_p is None:
        return None
    credit = ce_p * (1 - SLIP) + pe_p * (1 - SLIP)  # sell both
    # For straddle, credit must be >50 (livable premium) and <15% of strike (pricing sanity)
    if not (50 <= credit <= strike * 0.15):
        return None
    # walk forward to expiry with TP / SL on straddle value
    buckets = ["09:45", "10:15", "10:45", "11:15", "11:45", "12:15", "12:45",
               "13:15", "13:45", "14:15", "14:45", "15:15"]
    for dd in [d] + [dd for dd in days if d < dd <= exp]:
        for b in (buckets if dd != d else buckets[1:]):
            ce_v, pe_v = ce.get((dd, b)), pe.get((dd, b))
            if ce_v is None or pe_v is None:
                continue
            val = (ce_v + pe_v) * (1 + SLIP)  # cover both, adverse slippage
            if val <= credit * (tp_pct / 100.0):  # TP hit
                net = (credit - val) * LOT
                return net - rt_charges((ce_p + pe_p) * LOT, val * LOT)
            if val >= credit * (1 + sl_pct / 100.0):  # SL hit: sold credit, now pay credit*(1+sl%)
                net = (credit - val) * LOT
                return net - rt_charges((ce_p + pe_p) * LOT, val * LOT)
    # expiry: intrinsic
    sc = closes.get(exp)
    if sc is None:
        return None
    intr_ce = max(0.0, sc - strike)
    intr_pe = max(0.0, strike - sc)
    val = intr_ce + intr_pe
    net = (credit - val) * LOT
    return net - rt_charges((ce_p + pe_p) * LOT, val * LOT)


rows = []
postfall_count = 0
for i in range(1, len(days)):
    d_prev, d = days[i - 1], days[i]
    cp, cq = closes.get(d_prev), closes.get(days[i - 2]) if i >= 2 else (None,)
    if cp is None or i < 2 or closes.get(days[i - 2]) is None:
        continue
    prev_ret = cp / closes[days[i - 2]] - 1
    if prev_ret > -0.0125:
        continue  # trigger only: >=1.25% fall
    postfall_count += 1
    exp = next((e for e in exps if 2 <= (e - d).days <= 9), None)
    if exp is None or (d, "09:45") not in [(d, b) for b in by_day[d]]:
        continue
    S = by_day[d].get("09:45")
    if S is None:
        continue
    atm = rnd50(S)
    t1 = straddle_trade(d, exp, atm, tp_pct=50, sl_pct=200)
    t2 = straddle_trade(d, exp, atm, tp_pct=50, sl_pct=100)
    if t1 is not None:
        rows.append({"d": d, "sl": "2x credit", "net": t1})
    if t2 is not None:
        rows.append({"d": d, "sl": "1x credit", "net": t2})
print(f"post-fall days (trigger>=-1.25%): {postfall_count}", flush=True)

df = pd.DataFrame(rows)
if len(df) == 0:
    print("post-fall straddles: 0 trades (no post-fall days with valid contracts)")
    print("DONE")
else:
    print(f"post-fall straddles: {len(df)} trades across {df.d.nunique()} days\n")
    for sl in ("2x credit", "1x credit"):
        print(f"=== short ATM straddle, SL={sl} (TP 50% credit, expiry / SL close-out) ===")
        s = df[df.sl == sl].net.sort_values()
        if len(s) < 15:
            print(f"  n={len(s)} (too few)"); continue
        split = df[df.sl == sl].d.iloc[int(len(df[df.sl == sl]) * 0.6)]
        for era, sub in (("IS ", df[(df.sl == sl) & (df.d <= split)]), ("OOS", df[(df.sl == sl) & (df.d > split)]), ("ALL", df[df.sl == sl])):
            s = sub.net
            w, l = s[s > 0], s[s <= 0]
            pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else 99
            print(f"  {era} n={len(s):3d} win%={len(w)/len(s)*100:3.0f} avg={s.mean():+7.0f} "
                  f"tot={s.sum():+8.0f} PF={pf:5.2f} best={s.max():+7.0f} worst={s.min():+7.0f}")
    print("\nDONE")
