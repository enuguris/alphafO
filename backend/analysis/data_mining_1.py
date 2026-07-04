"""
DATA-MINING EXPEDITION 1 — no textbook priors, our own data only.
  P1: index intraday drift by 30-min bucket (+ day-of-week interaction)
  P2: overnight gap behavior — continuation vs fade in the first hour, gap-fill odds
  P3: max-pain pinning — does OI's max-pain predict expiry close better than spot? (10y bhav)
  P4: weekend theta — ATM straddle marks Thu close vs Fri close vs Mon close
Discipline: IS = first 60% of window, OOS = last 40%. Effects must survive both.
"""
import asyncio, time, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
from pathlib import Path
import httpx
import numpy as np
import pandas as pd

BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
STEP = 50


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

rows = []
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    rows.append({"ts": ts, "d": ts.date(), "t": ts.strftime("%H:%M"),
                 "o": float(c[1]), "h": float(c[2]), "l": float(c[3]), "c": float(c[4])})
df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
days = sorted(df.d.unique())
split = days[int(len(days) * 0.6)]
print(f"sessions {len(days)}: IS ≤ {split}, OOS after\n")

# ── P1: bucket drift ──────────────────────────────────────────────────────────
df["ret_bp"] = (df.c / df.o - 1) * 10000
print("=== P1: intraday 30-min bucket drift (bp per bucket) ===")
print(f"{'bucket':>6} {'IS avg':>8} {'IS win%':>8} {'OOS avg':>8} {'OOS win%':>9} {'n':>5}")
for t, g in df.groupby("t"):
    gi, go = g[g.d <= split], g[g.d > split]
    if len(gi) < 30 or len(go) < 30:
        continue
    print(f"{t:>6} {gi.ret_bp.mean():8.2f} {(gi.ret_bp > 0).mean()*100:7.1f}% "
          f"{go.ret_bp.mean():8.2f} {(go.ret_bp > 0).mean()*100:8.1f}% {len(g):5d}")

# ── P2: gap behavior ──────────────────────────────────────────────────────────
print("\n=== P2: overnight gap → first-hour + rest-of-day behavior ===")
day_grp = {d: g.sort_values("ts") for d, g in df.groupby("d")}
recs = []
prev = None
for d in days:
    g = day_grp[d]
    if prev is not None:
        pc = day_grp[prev].iloc[-1].c
        gap_bp = (g.iloc[0].o / pc - 1) * 10000
        fh = (g.iloc[1].c / g.iloc[0].o - 1) * 10000 if len(g) > 1 else np.nan   # first hour-ish
        rod = (g.iloc[-1].c / g.iloc[1].c - 1) * 10000 if len(g) > 2 else np.nan
        filled = (min(g.l) <= pc <= max(g.h))
        recs.append({"d": d, "gap": gap_bp, "fh": fh, "rod": rod, "filled": filled})
    prev = d
gp = pd.DataFrame(recs).dropna()
for nm, lo, hi in (("small |gap|<25bp", 0, 25), ("mid 25-60bp", 25, 60), ("large >60bp", 60, 1e9)):
    for era, sub0 in (("IS", gp[gp.d <= split]), ("OOS", gp[gp.d > split])):
        sub = sub0[(sub0.gap.abs() >= lo) & (sub0.gap.abs() < hi)]
        if len(sub) < 15:
            continue
        same_fh = (np.sign(sub.gap) == np.sign(sub.fh)).mean() * 100
        same_rod = (np.sign(sub.gap) == np.sign(sub.rod)).mean() * 100
        print(f"{nm:20} {era:3}: n={len(sub):3d} first-hour continues gap {same_fh:4.0f}% | "
              f"rest-of-day continues {same_rod:4.0f}% | gap fills same day {sub.filled.mean()*100:4.0f}%")

# ── P3: max-pain pinning (10y bhav) ──────────────────────────────────────────
print("\n=== P3: max-pain pinning into expiry (10y bhav) ===")
BHAV = Path("/app/market_data/bhav")
frames = []
for f in sorted(BHAV.glob("fo*.csv")):
    try:
        x = pd.read_csv(f, usecols=["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR",
                                    "OPTION_TYP", "CLOSE", "TIMESTAMP", "OPEN_INT"], low_memory=False)
    except Exception:
        continue
    x = x[(x.SYMBOL == "NIFTY") & (x.INSTRUMENT.isin(["OPTIDX", "FUTIDX"]))]
    if len(x):
        frames.append(x)
raw = pd.concat(frames, ignore_index=True)
raw["date"] = pd.to_datetime(raw.TIMESTAMP, dayfirst=True, errors="coerce").dt.date
raw["expiry"] = pd.to_datetime(raw.EXPIRY_DT, dayfirst=True, errors="coerce").dt.date
raw = raw.dropna(subset=["date", "expiry"])
futs = raw[raw.INSTRUMENT == "FUTIDX"]
fclose = futs.sort_values("expiry").groupby("date").first()["CLOSE"].to_dict()
opts = raw[raw.INSTRUMENT == "OPTIDX"]

pin = []
all_exp = sorted(opts.expiry.unique())
for exp in all_exp:
    sub_exp = opts[opts.expiry == exp]
    exp_close = fclose.get(exp)
    if exp_close is None:
        continue
    for dback in (3, 1):
        dates_before = sorted(x for x in sub_exp.date.unique() if x < exp)
        if len(dates_before) < dback:
            continue
        dref = dates_before[-dback]
        snap = sub_exp[sub_exp.date == dref]
        strikes = sorted(snap.STRIKE_PR.unique())
        if len(strikes) < 10:
            continue
        ce = snap[snap.OPTION_TYP == "CE"].set_index("STRIKE_PR").OPEN_INT
        pe = snap[snap.OPTION_TYP == "PE"].set_index("STRIKE_PR").OPEN_INT
        pains = []
        for k in strikes:
            pain = sum(ce.get(s, 0) * max(0, k - s) for s in strikes) + \
                   sum(pe.get(s, 0) * max(0, s - k) for s in strikes)
            pains.append((pain, k))
        mp = min(pains)[1]
        spot_ref = fclose.get(dref)
        if spot_ref is None:
            continue
        pin.append({"exp": exp, "dback": dback,
                    "err_mp": abs(exp_close - mp), "err_spot": abs(exp_close - spot_ref)})
pp = pd.DataFrame(pin)
mid = sorted(pp.exp.unique())[int(pp.exp.nunique() * 0.6)]
for dback in (3, 1):
    for era, sub in (("IS", pp[(pp.dback == dback) & (pp.exp <= mid)]),
                     ("OOS", pp[(pp.dback == dback) & (pp.exp > mid)])):
        if len(sub) < 20:
            continue
        better = (sub.err_mp < sub.err_spot).mean() * 100
        print(f"T-{dback} {era:3}: n={len(sub):3d} | max-pain closer than spot {better:4.0f}% of expiries | "
              f"median err: MP {sub.err_mp.median():5.0f} vs spot {sub.err_spot.median():5.0f}")

# ── P4: weekend theta (ATM straddle Thu→Fri→Mon marks) ───────────────────────
print("\n=== P4: weekend theta capture (ATM straddle marks, sampled expiries) ===")
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


def px_at(rows2, ts):
    b = None
    for t2, p in rows2:
        if t2 <= ts:
            b = p
        else:
            break
    return b


didx = {d: day_grp[d] for d in days}
wk = []
for exp in exps[::2]:      # every 2nd expiry: sample
    thu = exp - timedelta(days=(exp.weekday() - 3) % 7)
    # find actual Thu/Fri/Mon sessions preceding this expiry with dte>=4
    cands = [d for d in days if d < exp and (exp - d).days >= 4]
    thus = [d for d in cands if d.weekday() == 3]
    if not thus:
        continue
    thu = thus[-1]
    fri = next((d for d in days if d > thu and d.weekday() == 4), None)
    mon = next((d for d in days if d > thu and d.weekday() == 0), None)
    if not fri or not mon or mon >= exp:
        continue
    spot_thu = didx[thu].iloc[-1].c
    atm = float(round(spot_thu / STEP) * STEP)
    cmap = contracts(exp)
    kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
    if not kc or not kp:
        continue
    rc, rp = candles(kc, exp), candles(kp, exp)
    marks = {}
    ok = True
    for lbl, dd in (("thu", thu), ("fri", fri), ("mon", mon)):
        ts_l = didx[dd].iloc[-1].ts
        c2, p2 = px_at(rc, ts_l), px_at(rp, ts_l)
        if c2 is None or p2 is None:
            ok = False
            break
        marks[lbl] = c2 + p2
    if not ok or marks["thu"] < 10:
        continue
    spot_mon = didx[mon].iloc[-1].c
    move = abs(spot_mon / didx[fri].iloc[-1].c - 1) * 100
    wk.append({"exp": exp,
               "thu_fri": (marks["fri"] / marks["thu"] - 1) * 100,
               "fri_mon": (marks["mon"] / marks["fri"] - 1) * 100,
               "wknd_move": move})
w = pd.DataFrame(wk)
if len(w):
    print(f"expiries sampled: {len(w)}")
    print(f"straddle decay Thu→Fri (1 session):   avg {w.thu_fri.mean():+.1f}%")
    print(f"straddle decay Fri→Mon (weekend+1):   avg {w.fri_mon.mean():+.1f}%  "
          f"(median {w.fri_mon.median():+.1f}%, worst {w.fri_mon.max():+.1f}%)")
    calm = w[w.wknd_move < 0.5]
    print(f"when Monday move <0.5% ({len(calm)} cases): Fri→Mon decay {calm.fri_mon.mean():+.1f}%")
    print("→ if Fri→Mon decay >> Thu→Fri, weekend theta is NOT priced in on Friday (edge);")
    print("  if ≈, sellers already discount it (no edge).")

client.close()
print("\nDONE")
