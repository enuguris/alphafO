"""
AFTER-2PM INTRADAY TEST (user hypothesis, 2026-07-05):
enter at the 14:15 candle close, exit at the 15:15 close (same day).
Structures on real NIFTY weekly ATM options:
  SS  : sell ATM straddle (final-hour theta), SL 30% of credit
  MOM : buy ATM option in the direction of the day-so-far move (|move|>20bp)
  FADE: buy ATM option against the day-so-far move (|move|>20bp)
Each also split expiry-day vs non-expiry. IS/OOS 60/40. Charges + 0.5% slip.
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

start = exps[0] - timedelta(days=10)
idx, cur = [], start
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)
by_day = defaultdict(list)
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    by_day[ts.date()].append({"ts": ts, "o": float(c[1]), "c": float(c[4])})
for d in by_day:
    by_day[d].sort(key=lambda x: x["ts"])
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
        cand_cache[key] = sorted((datetime.fromisoformat(c[0]).replace(tzinfo=None), float(c[4]))
                                 for c in (j or {}).get("data", {}).get("candles", []))
    return cand_cache[key]


def px_at(rows, ts):
    b = None
    for t2, p in rows:
        if t2 <= ts:
            b = p
        else:
            break
    return b


out = []
for d in days:
    g = by_day[d]
    # need candles up to 14:15 entry and 15:15 exit
    ent = next((b for b in g if b["ts"].strftime("%H:%M") == "14:15"), None)
    if ent is None or len(g) < 5:
        continue
    exp = next((e for e in exps if 0 <= (e - d).days <= 7), None)
    if exp is None:
        continue
    ts_in, spot_in = ent["ts"], ent["c"]
    ts_x = g[-1]["ts"]
    atm = float(rnd50(spot_in))
    cmap = contracts(exp)
    kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
    if not kc or not kp:
        continue
    rc, rp = candles(kc, exp), candles(kp, exp)
    c_in, p_in = px_at(rc, ts_in), px_at(rp, ts_in)
    c_out, p_out = px_at(rc, ts_x), px_at(rp, ts_x)
    if None in (c_in, p_in, c_out, p_out) or c_in < 1 or p_in < 1:
        continue
    day_move_bp = (spot_in / g[0]["o"] - 1) * 10000
    is_exp = (exp == d)

    # SS: sell straddle 14:15 -> 15:15, SL 30%
    ce, pe = c_in * (1 - SLIP), p_in * (1 - SLIP)
    credit = ce + pe
    exit_v = None
    for bar in g:
        if bar["ts"] <= ts_in:
            continue
        cv, pv = px_at(rc, bar["ts"]), px_at(rp, bar["ts"])
        if cv is None or pv is None:
            continue
        if cv + pv >= credit * 1.3:
            exit_v = (cv + pv) * (1 + SLIP)
            break
    if exit_v is None:
        exit_v = (c_out + p_out) * (1 + SLIP)
    ss = (credit - exit_v) * LOT - charges(credit * LOT, exit_v * LOT, 2)

    # MOM / FADE (only when the day has direction by 2pm)
    mom = fade = None
    if abs(day_move_bp) > 20:
        up = day_move_bp > 0
        for nm, buy_ce in (("mom", up), ("fade", not up)):
            e = (c_in if buy_ce else p_in) * (1 + SLIP)
            x = (c_out if buy_ce else p_out) * (1 - SLIP)
            v = (x - e) * LOT - charges(e * LOT, x * LOT, 1)
            if nm == "mom":
                mom = v
            else:
                fade = v
    out.append({"d": d, "ss": ss, "mom": mom, "fade": fade, "is_exp": is_exp})

client.close()
t = pd.DataFrame(out)
print(f"days: {len(t)} ({t.d.min()} → {t.d.max()}), expiry days: {int(t.is_exp.sum())}\n")


def rep(name, series, sub):
    s = sub[series].dropna()
    if len(s) < 10:
        return
    w = (s > 0).sum()
    l = s[s <= 0]
    pf = s[s > 0].sum() / abs(l.sum()) if len(l) else 99
    print(f"  {name:34} n={len(s):3d} | win {w/len(s)*100:5.1f}% | PF {pf:5.2f} | "
          f"net Rs{s.sum():>9,.0f} | avg Rs{s.mean():>6,.0f} | worst Rs{s.min():>7,.0f}")


for era, sub in (("IN-SAMPLE", t[t.d <= split]), ("OUT-OF-SAMPLE", t[t.d > split])):
    print(f"=== {era} ===")
    rep("Sell straddle 14:15→15:15 (all days)", "ss", sub)
    rep("— expiry days only", "ss", sub[sub.is_exp])
    rep("— NON-expiry days only", "ss", sub[~sub.is_exp])
    rep("Momentum option buy (day move >20bp)", "mom", sub)
    rep("Fade option buy", "fade", sub)
    print()
print("DONE")
