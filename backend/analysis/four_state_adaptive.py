"""
THE FOUR-STATE ADAPTIVE CHALLENGE (user, 2026-07-05):
"Up / down / neutral / swing — pick the aggressive strategy per state, adapt fast."

Per day (real Upstox 30-min candles, NIFTY weekly ATM options):
  observe first two candles (09:15-10:15), then deploy at 10:15, exit 15:15:
    UP    -> BUY ATM CE          DOWN  -> BUY ATM PE
    FLAT  -> SELL ATM straddle (SL 40% of credit)
    SWING -> BUY ATM straddle
Three players on identical days:
  ORACLE     : knows the day's true best structure (upper bound = perfect adaptation)
  CLASSIFIER : aggressive morning rules (gap + first-hour move + range)
  COINFLIP   : random structure (baseline)
The gap Oracle vs Classifier = the cost of not being able to predict the state.
IS/OOS split 60/40. Full charges + 0.5% slippage per leg.
"""
import asyncio, time, random, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd

LOT, STEP = 65, 50
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
random.seed(42)


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
    by_day[ts.date()].append({"ts": ts, "o": float(c[1]), "h": float(c[2]),
                              "l": float(c[3]), "c": float(c[4])})
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


SLIP = 0.005
rows_out = []
prev_close = None
for i, d in enumerate(days):
    g = by_day[d]
    if len(g) < 6:
        prev_close = g[-1]["c"] if g else prev_close
        continue
    exp = next((e for e in exps if 0 <= (e - d).days <= 7), None)
    if exp is None:
        prev_close = g[-1]["c"]
        continue
    ts_dep = g[2]["ts"]                # deploy at 10:15 candle close
    spot = g[2]["c"]
    atm = float(rnd50(spot))
    cmap = contracts(exp)
    kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
    if not kc or not kp:
        prev_close = g[-1]["c"]
        continue
    rc, rp = candles(kc, exp), candles(kp, exp)
    ts_x = g[-1]["ts"]
    c_in, p_in = px_at(rc, ts_dep), px_at(rp, ts_dep)
    c_out, p_out = px_at(rc, ts_x), px_at(rp, ts_x)
    if None in (c_in, p_in, c_out, p_out) or c_in < 2 or p_in < 2:
        prev_close = g[-1]["c"]
        continue

    # payoffs of the four structures (with slippage + charges)
    def long_opt(e, x):
        e2, x2 = e * (1 + SLIP), x * (1 - SLIP)
        return (x2 - e2) * LOT - charges(e2 * LOT, x2 * LOT, 1)

    def short_straddle():
        ce, pe = c_in * (1 - SLIP), p_in * (1 - SLIP)
        credit = ce + pe
        # 40% SL scan
        exit_v = None
        for bar in g[3:]:
            cv, pv = px_at(rc, bar["ts"]), px_at(rp, bar["ts"])
            if cv is None or pv is None:
                continue
            if cv + pv >= credit * 1.4:
                exit_v = (cv + pv) * (1 + SLIP)
                break
        if exit_v is None:
            exit_v = (c_out + p_out) * (1 + SLIP)
        return (credit - exit_v) * LOT - charges(credit * LOT, exit_v * LOT, 2)

    def long_straddle():
        e2 = (c_in + p_in) * (1 + SLIP)
        x2 = (c_out + p_out) * (1 - SLIP)
        return (x2 - e2) * LOT - charges(e2 * LOT, x2 * LOT, 2)

    payoff = {"UP": long_opt(c_in, c_out), "DOWN": long_opt(p_in, p_out),
              "FLAT": short_straddle(), "SWING": long_straddle()}

    # aggressive morning classifier
    gap_bp = ((g[0]["o"] / prev_close - 1) * 10000) if prev_close else 0
    fh = (g[2]["c"] / g[0]["o"] - 1) * 10000      # move by 10:15
    rng = (max(b["h"] for b in g[:3]) - min(b["l"] for b in g[:3])) / spot * 10000
    if fh > 25 or (gap_bp > 40 and fh > 0):
        pick = "UP"
    elif fh < -25 or (gap_bp < -40 and fh < 0):
        pick = "DOWN"
    elif rng > 90:
        pick = "SWING"
    else:
        pick = "FLAT"

    oracle_pick = max(payoff, key=payoff.get)
    rows_out.append({"d": d, "oracle": payoff[oracle_pick], "oracle_pick": oracle_pick,
                     "clf": payoff[pick], "clf_pick": pick,
                     "hit": pick == oracle_pick,
                     "coin": payoff[random.choice(list(payoff))]})
    prev_close = g[-1]["c"]

client.close()
t = pd.DataFrame(rows_out)
print(f"days: {len(t)}  ({t.d.min()} → {t.d.max()})\n")
print("state distribution (oracle's true best):", t.oracle_pick.value_counts().to_dict())
print("classifier picks:", t.clf_pick.value_counts().to_dict())
print(f"classifier matched the true best state: {t.hit.mean()*100:.1f}% (coin flip = 25%)\n")
for name, col in (("ORACLE (perfect foresight)", "oracle"),
                  ("CLASSIFIER (aggressive adaptive)", "clf"),
                  ("COIN FLIP", "coin")):
    for era, sub in (("IS", t[t.d <= split]), ("OOS", t[t.d > split]), ("ALL", t)):
        if era != "ALL" and name == "COIN FLIP":
            continue
        w = sub[sub[col] > 0]
        print(f"{name:34} {era:4} n={len(sub):3d} | win {len(w)/len(sub)*100:5.1f}% | "
              f"net Rs{sub[col].sum():>10,.0f} | avg/day Rs{sub[col].mean():>6,.0f}")
    print()
print("DONE")
