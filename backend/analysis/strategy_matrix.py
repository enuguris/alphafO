"""
STRATEGY MATRIX on REAL Upstox expired 30-min data (Oct 2024 - Jun 2026).
Part A: spread variants x regime indicators (every trade tagged at entry with
        RSI14, 10d realized vol, India VIX, trend strength, day-of-week).
Part B: extra structures — iron condor (2-step OTM), 0DTE expiry-day straddle,
        momentum debit spread.
Part C: loss-mitigation policies on the spread book — tighter stop, roll-out,
        condorize-on-threat. Mitigation capital modeled separately.
Entries every 3 sessions per variant (statistical power); managed exits
(TP 50% credit / SL 2x / half-DTE / expiry-mark) unless stated.
"""
import asyncio, time, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
from pathlib import Path
import httpx
import pandas as pd
import numpy as np

LOT, STEP = 65, 50
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"


def rnd50(x):
    return round(x / STEP) * STEP


def charges(et, xt, legs=2):
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
idx = []
cur = start
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

# indicators (daily)
delta = closes.diff()
gain = delta.clip(lower=0).rolling(14).mean()
lossr = (-delta.clip(upper=0)).rolling(14).mean()
rsi = 100 - 100 / (1 + gain / lossr.replace(0, np.nan))
rv10 = closes.pct_change().rolling(10).std() * np.sqrt(252) * 100
sma10 = closes.rolling(10).mean()

vix_df = None
vp = Path("/app/market_data/india_vix.csv")
if vp.exists():
    vix_df = pd.read_csv(vp)
    vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.date
    vix_map = dict(zip(vix_df["date"], vix_df["vix"]))
else:
    vix_map = {}

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


def managed_exit(legs_rows, legs_sign, credit, d, exp, dte, i):
    """legs_rows: list of candle rows; legs_sign: +1 short(sold), -1 long(bought).
    Returns (net_points, exit_reason, exit_day). credit>0."""
    tp, sl = credit * 0.5, -(credit * 2.0)
    half = d + timedelta(days=max(1, dte // 2))
    for j in range(i + 1, len(days)):
        dd = days[j]
        if dd > exp:
            break
        for ts2, _ in by_day[dd]:
            vals = [px_at(r, ts2) for r in legs_rows]
            if any(v is None for v in vals):
                continue
            mark = sum(s * v for s, v in zip(legs_sign, vals))
            unreal = credit - mark
            if unreal >= tp:
                return credit - mark, "target", dd, vals
            if unreal <= sl:
                return credit - mark, "stop", dd, vals
        if dd >= half:
            ts_l = by_day[dd][-1][0]
            vals = [px_at(r, ts_l) for r in legs_rows]
            if any(v is None for v in vals):
                return None
            return credit - sum(s * v for s, v in zip(legs_sign, vals)), "time", dd, vals
    last_d = max((x for x in days if d < x <= exp), default=None)
    if last_d is None:
        return None
    ts_l = by_day[last_d][-1][0]
    vals = [px_at(r, ts_l) for r in legs_rows]
    if any(v is None for v in vals):
        return None
    return credit - sum(s * v for s, v in zip(legs_sign, vals)), "expiry", last_d, vals


# ── PART A+C: spread trades with tags + mitigation replays ───────────────────
rows_a = []
for i, d in enumerate(days):
    if i < 15 or i >= len(days) - 2 or i % 3 != 0:
        continue
    spot = close[d]
    ts_in = by_day[d][-1][0]
    exp = next((e for e in exps if 7 <= (e - d).days <= 20), None)
    if exp is None:
        continue
    dte = (exp - d).days
    cmap = contracts(exp)
    trend = (spot / sma10[d] - 1) * 100 if not np.isnan(sma10[d]) else 0
    for strat, ot, sign_dir in (("BullPut", "PE", 1), ("BearCall", "CE", -1)):
        for offset_steps, tag_off in ((0, "ATM"), (1, "OTM1")):
            atm = float(rnd50(spot))
            sk = atm - sign_dir * 0 + (offset_steps * STEP * (-1 if ot == "PE" else 1))
            sk = atm + (offset_steps * STEP * (-1 if ot == "PE" else 1))
            wk = sk - 2 * STEP if ot == "PE" else sk + 2 * STEP
            k_s, k_w = cmap.get((sk, ot)), cmap.get((wk, ot))
            if not k_s or not k_w:
                continue
            rs, rw = candles(k_s, exp), candles(k_w, exp)
            s_in, w_in = px_at(rs, ts_in), px_at(rw, ts_in)
            if s_in is None or w_in is None or s_in < 3:
                continue
            credit = s_in - w_in
            if not (STEP * 2 * 0.15 <= credit <= STEP * 2 * 0.85):
                continue
            r = managed_exit([rs, rw], [1, -1], credit, d, exp, dte, i)
            if r is None:
                continue
            net_pts, reason, xday, _ = r
            turn = (s_in + w_in) * LOT
            net = net_pts * LOT - charges(turn, turn)
            rows_a.append({
                "d": d, "strat": strat, "off": tag_off, "net": net, "reason": reason,
                "trend": trend, "rsi": rsi[d], "rv": rv10[d],
                "vix": vix_map.get(d, np.nan), "dow": d.weekday(),
                "aligned": (strat == "BullPut" and trend > 0) or (strat == "BearCall" and trend < 0),
                "credit": credit, "exp": exp, "dte": dte, "i": i,
                "k_s": k_s, "k_w": k_w, "sk": sk, "ot": ot, "s_in": s_in, "w_in": w_in,
            })

ta = pd.DataFrame(rows_a)
print(f"PART A base spread trades: {len(ta)}")


def rep(name, g, min_n=10):
    if len(g) < min_n:
        return
    w = g[g.net > 0]
    l = g[g.net <= 0]
    pf = w.net.sum() / abs(l.net.sum()) if len(l) and l.net.sum() != 0 else 99
    print(f"  {name:42} {len(g):4d}t | WIN {len(w)/len(g)*100:5.1f}% | PF {pf:5.2f} | net Rs{g.net.sum():>9,.0f} | avg Rs{g.net.mean():>6,.0f}")


print("\n=== A1: strategy x strike ===")
for (s, o), g in ta.groupby(["strat", "off"]):
    rep(f"{s} {o}", g)

print("\n=== A2: aligned with trend filter (like live) vs against ===")
for (s, o, a), g in ta.groupby(["strat", "off", "aligned"]):
    rep(f"{s} {o} {'WITH-trend' if a else 'AGAINST-trend'}", g)

print("\n=== A3: conditions (ATM, trend-aligned only — the live config) ===")
base = ta[(ta.off == "ATM") & (ta.aligned)]
rep("baseline (live config)", base)
rep("RSI<40 (oversold)", base[base.rsi < 40])
rep("RSI 40-60 (neutral)", base[(base.rsi >= 40) & (base.rsi <= 60)])
rep("RSI>60 (overbought)", base[base.rsi > 60])
rep("realized vol LOW (<12%)", base[base.rv < 12])
rep("realized vol MID (12-18%)", base[(base.rv >= 12) & (base.rv <= 18)])
rep("realized vol HIGH (>18%)", base[base.rv > 18])
rep("VIX < 13", base[base.vix < 13])
rep("VIX 13-16", base[(base.vix >= 13) & (base.vix <= 16)])
rep("VIX > 16", base[base.vix > 16])
for dow, nm in ((0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri")):
    rep(f"entry {nm}", base[base.dow == dow], min_n=8)
rep("trend strength <0.5%", base[base.trend.abs() < 0.5])
rep("trend strength >1.0%", base[base.trend.abs() > 1.0])

# ── PART B: other structures ─────────────────────────────────────────────────
print("\n=== B: other structures (managed exits) ===")
rows_ic, rows_0d, rows_db = [], [], []
for i, d in enumerate(days):
    if i < 15 or i >= len(days) - 2 or i % 3 != 0:
        continue
    spot = close[d]
    ts_in = by_day[d][-1][0]
    exp = next((e for e in exps if 7 <= (e - d).days <= 20), None)
    if exp is None:
        continue
    dte = (exp - d).days
    cmap = contracts(exp)
    atm = float(rnd50(spot))
    # Iron condor: sell 2-step OTM both sides, wings 2 further
    ks = [(atm + 2 * STEP, "CE", 1), (atm - 2 * STEP, "PE", 1),
          (atm + 4 * STEP, "CE", -1), (atm - 4 * STEP, "PE", -1)]
    keys = [cmap.get((k, o)) for k, o, _ in ks]
    if all(keys):
        rws = [candles(k, exp) for k in keys]
        vals = [px_at(r, ts_in) for r in rws]
        if all(v is not None for v in vals) and vals[0] > 2 and vals[1] > 2:
            credit = vals[0] + vals[1] - vals[2] - vals[3]
            if credit > 5:
                r = managed_exit(rws, [1, 1, -1, -1], credit, d, exp, dte, i)
                if r:
                    net_pts, reason, xday, _ = r
                    turn = sum(vals) * LOT
                    rows_0 = net_pts * LOT - charges(turn, turn, 4)
                    rows_ic.append({"d": d, "net": rows_0, "reason": reason})
    # momentum debit spread: |trend|>0.75% → buy ATM, sell 2 steps out (direction of trend)
    trend = (spot / sma10[d] - 1) * 100 if not np.isnan(sma10[d]) else 0
    if abs(trend) > 0.75:
        if trend > 0:
            bk, sk2, ot = atm, atm + 2 * STEP, "CE"
        else:
            bk, sk2, ot = atm, atm - 2 * STEP, "PE"
        k_b, k_s2 = cmap.get((bk, ot)), cmap.get((sk2, ot))
        if k_b and k_s2:
            rb, rs2 = candles(k_b, exp), candles(k_s2, exp)
            b_in, s2_in = px_at(rb, ts_in), px_at(rs2, ts_in)
            if b_in and s2_in and b_in > s2_in:
                debit = b_in - s2_in
                # managed for debit: TP 60% of max reward, SL half debit, half-DTE
                maxr = 2 * STEP - debit
                tp, sl = maxr * 0.6, -debit * 0.5
                done = None
                half = d + timedelta(days=max(1, dte // 2))
                for j in range(i + 1, len(days)):
                    dd = days[j]
                    if dd > exp:
                        break
                    for ts2, _ in by_day[dd]:
                        b2, s22 = px_at(rb, ts2), px_at(rs2, ts2)
                        if b2 is None or s22 is None:
                            continue
                        pnl = (b2 - s22) - debit
                        if pnl >= tp or pnl <= sl:
                            done = pnl
                            break
                    if done is not None:
                        break
                    if dd >= half:
                        ts_l = by_day[dd][-1][0]
                        b2, s22 = px_at(rb, ts_l), px_at(rs2, ts_l)
                        if b2 is not None and s22 is not None:
                            done = (b2 - s22) - debit
                        break
                if done is not None:
                    turn = (b_in + s2_in) * LOT
                    rows_db.append({"d": d, "net": done * LOT - charges(turn, turn)})

# 0DTE: on each expiry day, sell ATM straddle at first candle, exit last candle, SL 40% of credit
for exp in exps:
    if exp not in by_day or len(by_day[exp]) < 3:
        continue
    ts_open = by_day[exp][1][0]      # 09:45 candle
    spot0 = by_day[exp][1][1]
    atm = float(rnd50(spot0))
    cmap = contracts(exp)
    kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
    if not kc or not kp:
        continue
    rc, rp = candles(kc, exp), candles(kp, exp)
    c_in, p_in = px_at(rc, ts_open), px_at(rp, ts_open)
    if not c_in or not p_in:
        continue
    credit = c_in + p_in
    sl = credit * 1.4          # exit if straddle rises 40%
    exit_val = None
    for ts2, _ in by_day[exp][2:]:
        c2, p2 = px_at(rc, ts2), px_at(rp, ts2)
        if c2 is None or p2 is None:
            continue
        if c2 + p2 >= sl:
            exit_val = c2 + p2
            break
    if exit_val is None:
        ts_l = by_day[exp][-1][0]
        c2, p2 = px_at(rc, ts_l), px_at(rp, ts_l)
        if c2 is None or p2 is None:
            continue
        exit_val = c2 + p2
    turn = credit * LOT
    rows_0d.append({"d": exp, "net": (credit - exit_val) * LOT - charges(turn, exit_val * LOT)})

for nm, rws2 in (("IronCondor 2-step (weekly)", rows_ic),
                 ("0DTE expiry straddle-sell (SL 40%)", rows_0d),
                 ("Momentum debit spread (|trend|>0.75%)", rows_db)):
    g = pd.DataFrame(rws2)
    if len(g):
        rep(nm, g, min_n=5)

# ── PART C: mitigation policies on losing spread trades ──────────────────────
print("\n=== C: mitigation policies (on live-config trades that go -1x credit) ===")
# replay each base trade; when unrealized <= -1x credit BEFORE any exit:
#   (i) baseline: continue managed (2x stop)   — already have result
#   (ii) bail at -1x
#   (iii) condorize: sell opposite-side spread (same expiry) at that moment,
#         then managed on the combined position (uses mitigation capital)
res = {"baseline": [], "bail_1x": [], "condorize": []}
for t in base.itertuples():
    d, exp, i, dte = t.d, t.exp, t.i, t.dte
    cmap = contracts(exp)
    rs, rw = candles(t.k_s, exp), candles(t.k_w, exp)
    credit = t.credit
    hit_ts = None
    for j in range(i + 1, len(days)):
        dd = days[j]
        if dd > exp or dd >= d + timedelta(days=max(1, dte // 2)):
            break
        stop_now = False
        for ts2, _ in by_day[dd]:
            s2, w2 = px_at(rs, ts2), px_at(rw, ts2)
            if s2 is None or w2 is None:
                continue
            unreal = credit - (s2 - w2)
            if unreal >= credit * 0.5 or unreal <= -(credit * 2):
                stop_now = True
                break
            if unreal <= -credit and hit_ts is None:
                hit_ts = (dd, ts2, s2, w2)
                break
        if hit_ts or stop_now:
            break
    res["baseline"].append(t.net)
    if hit_ts is None:
        res["bail_1x"].append(t.net)
        res["condorize"].append(t.net)
        continue
    dd, ts2, s2, w2 = hit_ts
    turn = (t.s_in + t.w_in) * LOT
    bail_net = (credit - (s2 - w2)) * LOT - charges(turn, (s2 + w2) * LOT)
    res["bail_1x"].append(bail_net)
    # condorize: add opposite side spread at ts2
    spot2 = next((p for tt, p in by_day[dd] if tt == ts2), close[dd])
    atm2 = float(rnd50(spot2))
    if t.ot == "PE":
        sk2, wk2, ot2 = atm2 + 0, atm2 + 2 * STEP, "CE"
        sk2 = atm2
    else:
        sk2, wk2, ot2 = atm2, atm2 - 2 * STEP, "PE"
    kk_s, kk_w = cmap.get((sk2, ot2)), cmap.get((wk2, ot2))
    if not kk_s or not kk_w:
        res["condorize"].append(t.net)
        continue
    rs2c, rw2c = candles(kk_s, exp), candles(kk_w, exp)
    s2_in, w2_in = px_at(rs2c, ts2), px_at(rw2c, ts2)
    if s2_in is None or w2_in is None:
        res["condorize"].append(t.net)
        continue
    credit2 = s2_in - w2_in
    comb_credit = (credit - (s2 - w2)) + credit2 + (s2 - w2)   # original credit + new credit
    comb_credit = credit + credit2
    r2 = managed_exit([rs, rw, rs2c, rw2c], [1, -1, 1, -1], comb_credit, dd,
                      exp, (exp - dd).days, days.index(dd))
    if r2 is None:
        res["condorize"].append(t.net)
        continue
    net_pts, _, _, _ = r2
    turn2 = (t.s_in + t.w_in + s2_in + w2_in) * LOT
    res["condorize"].append(net_pts * LOT - charges(turn2, turn2, 4))

for nm, arr in res.items():
    g = pd.DataFrame({"net": arr})
    rep(f"mitigation: {nm}", g, min_n=5)
threatened = sum(1 for t in base.itertuples() if True)
print(f"  (policies differ only on trades that reached -1x credit)")

client.close()
print("\nDONE")
