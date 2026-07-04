"""
POPULAR PRACTITIONER STRATEGIES on REAL Upstox 30-min data (NIFTY, 21 months).

  S920   : daily short ATM straddle at first-candle close (~09:45), per-leg
           SL at +40% of that leg's premium, exit last candle. (The "9:20
           straddle" — India's most popular retail algo, approximated at our
           30-min granularity.)
  ORB    : opening-range breakout — if 2nd 30-min candle closes above/below
           the 1st candle's high/low, buy ATM CE/PE; SL -35% premium,
           TP +70%, exit last candle.
  JADE   : weekly jade lizard — sell ATM-1 PE + sell ATM+1 CE + buy ATM+3 CE,
           structured for zero upside risk when credit > call-spread width;
           managed exits (TP 50% credit, SL 2x, half-DTE).
IS/OOS split at 60%.
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


s920, orb, jade = [], [], []
for i, d in enumerate(days):
    g = by_day[d]
    if len(g) < 4 or i >= len(days) - 1:
        continue
    exp = next((e for e in exps if 0 <= (e - d).days <= 7), None)   # nearest weekly
    exp_pos = next((e for e in exps if 7 <= (e - d).days <= 20), None)
    ts1 = g[0]["ts"]        # first candle (09:15-09:45) close ≈ 09:45 entry
    spot1 = g[0]["c"]
    atm = float(rnd50(spot1))

    # ── S920: daily short straddle, per-leg SL +40%, exit last candle ──────
    if exp is not None and (exp - d).days >= 0:
        cmap = contracts(exp)
        kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
        if kc and kp:
            rc, rp = candles(kc, exp), candles(kp, exp)
            c_in, p_in = px_at(rc, ts1), px_at(rp, ts1)
            if c_in and p_in and c_in > 2 and p_in > 2:
                legs = {"CE": [rc, c_in, None], "PE": [rp, p_in, None]}   # rows, entry, exit
                for bar in g[1:]:
                    for ot, L in legs.items():
                        if L[2] is not None:
                            continue
                        v = px_at(L[0], bar["ts"])
                        if v is not None and v >= L[1] * 1.4:
                            L[2] = v            # leg stopped
                ts_l = g[-1]["ts"]
                pnl = 0.0
                turn_in = (c_in + p_in) * LOT
                turn_out = 0.0
                ok = True
                for ot, L in legs.items():
                    xv = L[2] if L[2] is not None else px_at(L[0], ts_l)
                    if xv is None:
                        ok = False
                        break
                    pnl += (L[1] - xv)
                    turn_out += xv * LOT
                if ok:
                    s920.append({"d": d, "net": pnl * LOT - charges(turn_in, turn_out, 2)})

    # ── ORB: breakout of first candle range, buy ATM option ────────────────
    if exp is not None:
        b2 = g[1]
        direction = None
        if b2["c"] > g[0]["h"]:
            direction = "CE"
        elif b2["c"] < g[0]["l"]:
            direction = "PE"
        if direction:
            cmap = contracts(exp)
            atm2 = float(rnd50(b2["c"]))
            k = cmap.get((atm2, direction))
            if k:
                r = candles(k, exp)
                e_in = px_at(r, b2["ts"])
                if e_in and e_in > 2:
                    exit_v = None
                    for bar in g[2:]:
                        v = px_at(r, bar["ts"])
                        if v is None:
                            continue
                        if v <= e_in * 0.65 or v >= e_in * 1.7:
                            exit_v = v
                            break
                    if exit_v is None:
                        exit_v = px_at(r, g[-1]["ts"])
                    if exit_v is not None:
                        turn = e_in * LOT
                        orb.append({"d": d, "net": (exit_v - e_in) * LOT - charges(turn, exit_v * LOT, 1)})

    # ── JADE lizard: weekly, Tue-Thu entries every 2 sessions ──────────────
    if exp_pos is not None and d.weekday() in (1, 2, 3) and i % 2 == 0:
        cmap = contracts(exp_pos)
        ts_e = g[-1]["ts"]
        spot_e = g[-1]["c"]
        atm3 = float(rnd50(spot_e))
        pk, ck, wk = atm3 - STEP, atm3 + STEP, atm3 + 3 * STEP
        kp2, kc2, kw2 = cmap.get((pk, "PE")), cmap.get((ck, "CE")), cmap.get((wk, "CE"))
        if kp2 and kc2 and kw2:
            rp2, rc2, rw2 = candles(kp2, exp_pos), candles(kc2, exp_pos), candles(kw2, exp_pos)
            p_in, c_in, w_in = px_at(rp2, ts_e), px_at(rc2, ts_e), px_at(rw2, ts_e)
            if p_in and c_in and w_in and p_in > 3:
                credit = p_in + c_in - w_in
                cs_width = wk - ck
                if credit <= cs_width:      # classic jade rule NOT met → skip (upside risk)
                    continue
                dte = (exp_pos - d).days
                tp, sl = credit * 0.5, -(credit * 2.0)
                half = d + timedelta(days=max(1, dte // 2))
                rowsL = [(rp2, 1), (rc2, 1), (rw2, -1)]
                exit_mark, done = None, False
                for j2 in range(i + 1, len(days)):
                    dd = days[j2]
                    if dd > exp_pos:
                        break
                    for bar in by_day[dd]:
                        vals = [px_at(r0, bar["ts"]) for r0, _ in rowsL]
                        if any(v is None for v in vals):
                            continue
                        mark = sum(q * v for (_, q), v in zip(rowsL, vals))
                        u = credit - mark
                        if u >= tp or u <= sl:
                            exit_mark, done = mark, True
                            break
                    if done:
                        break
                    if dd >= half:
                        ts_l2 = by_day[dd][-1]["ts"]
                        vals = [px_at(r0, ts_l2) for r0, _ in rowsL]
                        if not any(v is None for v in vals):
                            exit_mark = sum(q * v for (_, q), v in zip(rowsL, vals))
                        break
                if exit_mark is not None:
                    turn = (p_in + c_in + w_in) * LOT
                    jade.append({"d": d, "net": (credit - exit_mark) * LOT - charges(turn, turn, 3)})

client.close()

print(f"{'strategy':22} {'era':4} {'n':>4} {'WIN%':>6} {'PF':>6} {'net':>10} {'avg':>7} {'worst':>8}")
for name, rows in (("S920 daily straddle", s920), ("ORB option buying", orb), ("Jade Lizard weekly", jade)):
    t = pd.DataFrame(rows)
    if not len(t):
        print(f"{name:22} no trades")
        continue
    for era, sub in (("IS", t[t.d <= split]), ("OOS", t[t.d > split]), ("ALL", t)):
        if len(sub) < 5:
            continue
        w, l = sub[sub.net > 0], sub[sub.net <= 0]
        pf = w.net.sum() / abs(l.net.sum()) if len(l) and l.net.sum() != 0 else 99
        print(f"{name:22} {era:4} {len(sub):4d} {len(w)/len(sub)*100:5.1f}% {pf:6.2f} "
              f"{sub.net.sum():>10,.0f} {sub.net.mean():>7,.0f} {sub.net.min():>8,.0f}")
print("DONE")
