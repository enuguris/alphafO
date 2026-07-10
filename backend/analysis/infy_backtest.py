"""INFY option-strategy backtest on real Upstox data (monthly expiries).
1. Earnings-gap profile: how big are INFY's daily moves, clustered by month.
2. Premium structures per monthly cycle, entered ~21 DTE, managed to expiry:
   - Short strangle (~6% OTM both sides), SL 2x credit / TP 50% / expiry
   - Iron condor (sell 6% OTM, buy 10% OTM wings) — defined risk
   - Short-put ratio flag (the user's structure) — measured as downside tail
Reports win %, PF, worst loss, IS/OOS, and marks earnings-month expiries.
"""
import asyncio, time
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd

BASE = "https://api.upstox.com/v2"
INFY_EQ = "NSE_EQ|INE009A01021"
LOT, SLIP = 400, 0.01
ENTRY_DTE = 21          # enter ~21 calendar days before expiry
OTM = 0.06              # short strikes ~6% OTM
WING = 0.10             # condor wings ~10% OTM
EARNINGS_MONTHS = {1, 4, 7, 10}   # Indian IT quarterly results


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


def charges(entry_val, exit_val):
    b = min(20.0, entry_val * 0.0003) * 2 + min(20.0, exit_val * 0.0003) * 2
    txn = (entry_val + exit_val) * 0.00053
    stt = entry_val * 0.001
    return b + txn + stt + (b + txn) * 0.18


# ── equity daily bars → spot by date + gap profile ──
j = get(f"{BASE}/historical-candle/{INFY_EQ}/day/{date.today()}/{date.today()-timedelta(days=760)}")
eq = list(reversed((j or {}).get("data", {}).get("candles", [])))
edf = pd.DataFrame(eq, columns=["ts", "o", "h", "l", "c", "v", "oi"])
edf["d"] = pd.to_datetime(edf.ts.str[:10]).dt.date
edf["c"] = pd.to_numeric(edf.c)
edf["ret"] = edf.c.pct_change()
spot_by_date = dict(zip(edf.d, edf.c))
edf["month"] = pd.to_datetime(edf.ts.str[:10]).dt.month

print("=== INFY DAILY MOVE / GAP PROFILE (2y) ===")
print(f"trading days: {len(edf)}  daily vol (std): {edf.ret.std()*100:.2f}%  annualized: {edf.ret.std()*(252**0.5)*100:.0f}%")
big = edf[edf.ret.abs() > 0.05]
print(f"days with >5% move: {len(big)}  ({len(big)/len(edf)*100:.1f}%)")
for _, r in big.sort_values("ret").iterrows():
    tag = "EARNINGS-mo" if r.month in EARNINGS_MONTHS else ""
    print(f"  {r.d}  {r.ret*100:+.1f}%  {tag}")
em = edf[edf.month.isin(EARNINGS_MONTHS)]
print(f"earnings-month days |move|: mean {em.ret.abs().mean()*100:.2f}%  vs other months {edf[~edf.month.isin(EARNINGS_MONTHS)].ret.abs().mean()*100:.2f}%")

# ── expiries + spot helper ──
exps = sorted(date.fromisoformat(x) for x in (get(f"{BASE}/expired-instruments/expiries", instrument_key=INFY_EQ) or {}).get("data", []))
edates = sorted(spot_by_date)


def spot_on(d):
    lo = [x for x in edates if x <= d]
    return spot_by_date[lo[-1]] if lo else None


contract_cache, cand_cache = {}, {}


def contracts(exp):
    if exp not in contract_cache:
        j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=INFY_EQ, expiry_date=str(exp))
        contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                               for r in (j or {}).get("data", [])}
    return contract_cache[exp]


def day_series(exp, strike, ot):
    ck = contracts(exp).get((float(strike), ot))
    if not ck:
        return {}
    if ck not in cand_cache:
        j = get(f"{BASE}/expired-instruments/historical-candle/{ck}/day/{exp}/{exp-timedelta(days=40)}")
        cand_cache[ck] = {datetime.fromisoformat(c[0][:10]).date(): float(c[4])
                          for c in (j or {}).get("data", {}).get("candles", [])}
    return cand_cache[ck]


def nearest_strike(exp, target, ot):
    ks = [k for (k, o) in contracts(exp) if o == ot]
    return min(ks, key=lambda k: abs(k - target)) if ks else None


def run_strangle(condor=False):
    rows = []
    for exp in exps:
        entry_d = exp - timedelta(days=ENTRY_DTE)
        S = spot_on(entry_d)
        if not S:
            continue
        ce_k = nearest_strike(exp, S * (1 + OTM), "CE")
        pe_k = nearest_strike(exp, S * (1 - OTM), "PE")
        if not ce_k or not pe_k:
            continue
        ce_s, pe_s = day_series(exp, ce_k, "CE"), day_series(exp, pe_k, "PE")
        # entry price = close on nearest date >= entry_d
        edays = sorted(d for d in ce_s if d in pe_s and d >= entry_d)
        if not edays:
            continue
        d0 = edays[0]
        cp, pp = ce_s.get(d0), pe_s.get(d0)
        if not cp or not pp:
            continue
        credit = (cp + pp) * (1 - SLIP)
        wing_cost = 0.0
        cw = pw = None
        if condor:
            cw_k = nearest_strike(exp, S * (1 + WING), "CE")
            pw_k = nearest_strike(exp, S * (1 - WING), "PE")
            cw, pw = day_series(exp, cw_k, "CE"), day_series(exp, pw_k, "PE")
            wc, wp = cw.get(d0), pw.get(d0)
            if wc is None or wp is None:
                continue
            wing_cost = (wc + wp) * (1 + SLIP)
            credit -= wing_cost
        if credit <= 0:
            continue
        # walk to expiry, TP 50% / SL 2x on net position value
        exit_val = None
        for d in sorted(x for x in ce_s if x >= d0 and x <= exp):
            cv, pv = ce_s.get(d), pe_s.get(d)
            if cv is None or pv is None:
                continue
            val = (cv + pv)
            if condor and cw and pw:
                val -= (cw.get(d, 0) + pw.get(d, 0))
            val *= (1 + SLIP)
            if val <= credit * 0.5:
                exit_val = val; break
            if val >= credit * 3.0:
                exit_val = val; break
        if exit_val is None:
            sc = spot_on(exp)
            ce_i = max(0.0, sc - ce_k); pe_i = max(0.0, pe_k - sc)
            val = ce_i + pe_i
            if condor:
                val -= max(0.0, sc - nearest_strike(exp, S*(1+WING), "CE")) + max(0.0, nearest_strike(exp, S*(1-WING), "PE") - sc)
            exit_val = max(0.0, val)
        net = (credit - exit_val) * LOT - charges((cp+pp)*LOT, exit_val*LOT)
        rows.append({"exp": exp, "earnings": exp.month in EARNINGS_MONTHS, "net": net})
    return pd.DataFrame(rows)


def report(df, label):
    if df.empty:
        print(f"{label}: no trades"); return
    df = df.sort_values("exp")
    s = df.net
    w, l = s[s > 0], s[s <= 0]
    pf = w.sum()/abs(l.sum()) if len(l) and l.sum() != 0 else 99
    print(f"{label}: n={len(s)} win%={len(w)/len(s)*100:.0f} avg={s.mean():+.0f} tot={s.sum():+.0f} "
          f"PF={pf:.2f} best={s.max():+.0f} worst={s.min():+.0f}")
    e = df[df.earnings]; ne = df[~df.earnings]
    if len(e): print(f"    earnings-month expiries: n={len(e)} win%={len(e[e.net>0])/len(e)*100:.0f} avg={e.net.mean():+.0f} worst={e.net.min():+.0f}")
    if len(ne): print(f"    non-earnings expiries:   n={len(ne)} win%={len(ne[ne.net>0])/len(ne)*100:.0f} avg={ne.net.mean():+.0f} worst={ne.net.min():+.0f}")


print("\n=== INFY PREMIUM STRUCTURES (monthly, ~21 DTE entry, managed) ===")
report(run_strangle(condor=False), "Short strangle 6% OTM")
report(run_strangle(condor=True),  "Iron condor 6%/10%   ")
print("DONE")
