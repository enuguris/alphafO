"""Is premium selling richer the morning AFTER a big down day?
Compare credit spreads entered next-morning-after-fall vs all normal days.
Real Upstox expired 30-min data, managed exits (TP 50% credit / SL 2x / expiry).
"""
import asyncio, time
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd

LOT, STEP, SLIP = 65, 50, 0.005
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
BUCKETS = ["09:45", "10:15", "10:45", "11:15", "11:45", "12:15", "12:45",
           "13:15", "13:45", "14:15", "14:45", "15:15"]


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
idx, cur = [], exps[0] - timedelta(days=12)
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)
by_day = defaultdict(dict)
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    by_day[ts.date()][ts.strftime("%H:%M")] = float(c[4])
days = sorted(by_day)
closes = {d: by_day[d].get("15:15") or by_day[d].get("14:45") for d in days}

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


def spread_trade(d, exp, short_k, long_k, ot):
    """Sell short_k, buy long_k (same ot/expiry) at d 09:45; managed to expiry."""
    ss, ls = series(exp, short_k, ot), series(exp, long_k, ot)
    sp, lp = ss.get((d, "09:45")), ls.get((d, "09:45"))
    if sp is None or lp is None:
        return None
    credit = sp * (1 - SLIP) - lp * (1 + SLIP)
    if credit <= 0:
        return None
    width = abs(short_k - long_k)
    if not (0.15 * width <= credit <= 0.85 * width):
        return None
    # walk forward to expiry with TP 50% / SL 2x on spread value
    trade_days = [dd for dd in days if d < dd <= exp]
    for dd in [d] + trade_days:
        for b in (BUCKETS if dd != d else BUCKETS[1:]):
            sv, lv = ss.get((dd, b)), ls.get((dd, b))
            if sv is None or lv is None:
                continue
            val = sv - lv
            if val <= credit * 0.5:
                exit_v = val
                net = (credit - exit_v * (1 + SLIP)) * LOT
                return net - rt_charges((sp + lp) * LOT, abs(exit_v) * (1 + SLIP) * LOT)
            if val >= credit * 3.0:  # 2x loss on credit => value 3x credit
                exit_v = val
                net = (credit - exit_v * (1 + SLIP)) * LOT
                return net - rt_charges((sp + lp) * LOT, abs(exit_v) * (1 + SLIP) * LOT)
    # expiry: intrinsic
    sc = closes.get(exp)
    if sc is None:
        return None
    intr_s = max(0.0, (sc - short_k) if ot == "CE" else (short_k - sc))
    intr_l = max(0.0, (sc - long_k) if ot == "CE" else (long_k - sc))
    exit_v = intr_s - intr_l
    net = (credit - exit_v) * LOT
    return net - rt_charges((sp + lp) * LOT, abs(exit_v) * LOT)


rows = []
for i in range(1, len(days)):
    d_prev, d = days[i - 1], days[i]
    cp, cq = closes.get(d_prev), closes.get(days[i - 2]) if i >= 2 else (None,)
    if cp is None or i < 2 or closes.get(days[i - 2]) is None:
        continue
    prev_ret = cp / closes[days[i - 2]] - 1
    exp = next((e for e in exps if 2 <= (e - d).days <= 9), None)
    if exp is None or (d, "09:45") not in [(d, b) for b in by_day[d]]:
        continue
    S = by_day[d].get("09:45")
    if S is None:
        continue
    regime = "postfall" if prev_ret <= -0.0125 else ("postbig_up" if prev_ret >= 0.0125 else "normal")
    bp = spread_trade(d, exp, rnd50(S - 200), rnd50(S - 300), "PE")   # bull put
    bc = spread_trade(d, exp, rnd50(S + 200), rnd50(S + 300), "CE")   # bear call
    if bp is not None:
        rows.append({"d": d, "regime": regime, "structure": "bull_put", "net": bp})
    if bc is not None:
        rows.append({"d": d, "regime": regime, "structure": "bear_call", "net": bc})

df = pd.DataFrame(rows)
print(f"trades: {len(df)}  (days with prev-day fall>1.25%: {df[df.regime=='postfall'].d.nunique()})")
for st in ("bull_put", "bear_call"):
    print(f"\n=== {st} (short 200 OTM, wing 100, TP50/SL2x/expiry) ===")
    for rg in ("postfall", "normal", "postbig_up"):
        s = df[(df.structure == st) & (df.regime == rg)].net
        if len(s) < 8:
            print(f"  {rg:11s} n={len(s)} (too few)")
            continue
        w, l = s[s > 0], s[s <= 0]
        pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else 99
        print(f"  {rg:11s} n={len(s):4d} win%={len(w)/len(s)*100:3.0f} avg={s.mean():+7.0f} PF={pf:5.2f} worst={s.min():+7.0f}")
print("DONE")
