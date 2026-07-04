"""
BUY-HEAVY / LOSS-MINIMIZING structures on REAL Upstox 30-min data (21 months).
Focus: what do the added long legs do to win rate AND to the loss profile.

  BackspreadCE : SELL 1 ATM CE, BUY 2 CE at +2 steps   (loss capped between strikes)
  BackspreadPE : SELL 1 ATM PE, BUY 2 PE at -2 steps
  BWB_PE       : BUY 1 ATM PE, SELL 2 PE at -2, BUY 1 PE at -5 (broken wing fly)
  CalendarCE   : SELL this-week ATM CE, BUY next-week ATM CE (max loss = debit)
  CalendarPE   : same with puts
  Baseline     : BearCall spread (the champion) for comparison

Exits: credit structures TP 50%/SL 2x credit/half-DTE; debit structures
TP +60% of cost / SL -50% of cost / near-expiry morning. Entries Tue-Thu
every 2 sessions. All prices are real 30-min closes.
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


def rnd50(x):
    return round(x / STEP) * STEP


def charges(et, xt, legs):
    b = min(20.0, et * 0.0003) * legs + min(20.0, xt * 0.0003) * legs
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

start = exps[0] - timedelta(days=40)
idx, cur = [], start
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)
by_day = defaultdict(list)
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    by_day[ts.date()].append((ts, float(c[4])))
for d in by_day:
    by_day[d].sort()
days = sorted(by_day.keys())
close = {d: by_day[d][-1][1] for d in days}
closes = pd.Series([close[d] for d in days], index=days)
sma10 = closes.rolling(10).mean()

contract_cache, cand_cache = {}, {}


def contracts(exp):
    if exp not in contract_cache:
        j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=IDX, expiry_date=str(exp))
        contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                               for r in (j or {}).get("data", [])}
    return contract_cache[exp]


def candles(key, exp):
    if key not in cand_cache:
        j = get(f"{BASE}/expired-instruments/historical-candle/{key}/30minute/{exp}/{exp - timedelta(days=40)}")
        cand_cache[key] = sorted((datetime.fromisoformat(c[0]).replace(tzinfo=None), float(c[4]))
                                 for c in (j or {}).get("data", {}).get("candles", []))
    return cand_cache[key]


def px_at(rows, ts):
    b = None
    for t, p in rows:
        if t <= ts:
            b = p
        else:
            break
    return b


def run_structure(legs_spec, d, i, exp, end_exp=None):
    """legs_spec: [(strike, type, qty_signed)] qty>0 = SELL, qty<0 = BUY.
    end_exp: exit deadline (for calendars = near expiry). Returns dict or None."""
    end_exp = end_exp or exp
    ts_in = by_day[d][-1][0]
    rows_all, entry_px = [], []
    for sk, ot, q, leg_exp in legs_spec:
        k = contracts(leg_exp).get((sk, ot))
        if not k:
            return None
        r = candles(k, leg_exp)
        p = px_at(r, ts_in)
        if p is None or p < 1:
            return None
        rows_all.append((r, q))
        entry_px.append(p)
    cost = -sum(q * p for (_, q), p in zip(rows_all, entry_px))   # >0 = net debit paid
    credit = -cost
    n_legs = len(legs_spec)
    dte = (end_exp - d).days
    half = d + timedelta(days=max(1, dte // 2))
    is_credit = credit > 0
    if is_credit:
        tp, sl = credit * 0.5, -(credit * 2.0)
    else:
        tp, sl = cost * 0.6, -cost * 0.5

    exit_mark = None
    reason = "deadline"
    for j in range(i + 1, len(days)):
        dd = days[j]
        if dd >= end_exp:
            break
        done = False
        for ts2, _ in by_day[dd]:
            vals = [px_at(r, ts2) for r, _ in rows_all]
            if any(v is None for v in vals):
                continue
            mark = sum(q * v for (_, q), v in zip(rows_all, vals))
            pnl = credit - mark if is_credit else (-mark) - cost
            if pnl >= tp:
                exit_mark, reason, done = mark, "target", True
                break
            if pnl <= sl:
                exit_mark, reason, done = mark, "stop", True
                break
        if done:
            break
        if dd >= half:
            ts_l = by_day[dd][-1][0]
            vals = [px_at(r, ts_l) for r, _ in rows_all]
            if any(v is None for v in vals):
                return None
            exit_mark, reason = sum(q * v for (_, q), v in zip(rows_all, vals)), "time"
            break
    if exit_mark is None:
        last_d = max((x for x in days if d < x < end_exp), default=None)
        if last_d is None:
            return None
        ts_l = by_day[last_d][-1][0]
        vals = [px_at(r, ts_l) for r, _ in rows_all]
        if any(v is None for v in vals):
            return None
        exit_mark = sum(q * v for (_, q), v in zip(rows_all, vals))
    pnl_pts = (credit - exit_mark) if is_credit else ((-exit_mark) - cost)
    turn = sum(abs(p) for p in entry_px) * LOT
    net = pnl_pts * LOT - charges(turn, turn, n_legs)
    return {"d": d, "net": net, "reason": reason}


results = defaultdict(list)
for i, d in enumerate(days):
    if i < 12 or i >= len(days) - 2 or i % 2 != 0 or d.weekday() not in (1, 2, 3):
        continue
    spot = close[d]
    atm = float(rnd50(spot))
    trend_up = spot > sma10[d]
    near = next((e for e in exps if 7 <= (e - d).days <= 20), None)
    if near is None:
        continue
    nxt_wk = next((e for e in exps if e > near), None)

    specs = {
        "BackspreadCE": [(atm, "CE", 1, near), (atm + 2 * STEP, "CE", -2, near)],
        "BackspreadPE": [(atm, "PE", 1, near), (atm - 2 * STEP, "PE", -2, near)],
        "BWB_PE": [(atm, "PE", -1, near), (atm - 2 * STEP, "PE", 2, near), (atm - 5 * STEP, "PE", -1, near)],
        "BearCall(base)": [(atm, "CE", 1, near), (atm + 2 * STEP, "CE", -1, near)],
    }
    if nxt_wk:
        specs["CalendarCE"] = [(atm, "CE", 1, near), (atm, "CE", -1, nxt_wk)]
        specs["CalendarPE"] = [(atm, "PE", 1, near), (atm, "PE", -1, nxt_wk)]

    for name, legs in specs.items():
        # trend alignment: bearish structures with downtrend, bullish with up
        if name in ("BackspreadCE", "BearCall(base)") and trend_up:
            continue
        if name in ("BackspreadPE", "BWB_PE") and not trend_up:
            continue
        r = run_structure(legs, d, i, near, end_exp=near)
        if r:
            results[name].append(r)

client.close()

print(f"{'structure':16} {'n':>4} {'WIN%':>6} {'PF':>6} {'net':>10} {'avg':>7} "
      f"{'avgLOSS':>8} {'worst':>9} {'maxDD':>9}")
for name, rows in sorted(results.items()):
    t = pd.DataFrame(rows)
    w, l = t[t.net > 0], t[t.net <= 0]
    pf = w.net.sum() / abs(l.net.sum()) if len(l) and l.net.sum() != 0 else 99
    eq = t.sort_values("d").net.cumsum()
    dd = (eq - eq.cummax()).min()
    print(f"{name:16} {len(t):4d} {len(w)/len(t)*100:5.1f}% {pf:6.2f} "
          f"{t.net.sum():>10,.0f} {t.net.mean():>7,.0f} "
          f"{(l.net.mean() if len(l) else 0):>8,.0f} {t.net.min():>9,.0f} {dd:>9,.0f}")
print("\nDONE")
