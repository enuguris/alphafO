"""Test the user's proposal: when the index is falling hard intraday, BUY ATM PE
with a trailing stop on the option premium. Real Upstox 30-min data, all
weekly expiries Oct 2024 - Jun 2026. Also: did ANY morning feature predict
big afternoon falls (precursor scan)?
"""
import asyncio, time
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd

LOT, STEP, SLIP = 65, 50, 0.005
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
BUCKETS = ["09:15", "09:45", "10:15", "10:45", "11:15", "11:45",
           "12:15", "12:45", "13:15", "13:45", "14:15", "14:45", "15:15"]


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


def charges_buy_sell(bv, sv):
    b = min(20.0, bv * 0.0003) + min(20.0, sv * 0.0003)
    txn = (bv + sv) * 0.00053
    stt = sv * 0.001
    return b + txn + stt + (b + txn) * 0.18


exps = sorted(date.fromisoformat(x) for x in
              (get(f"{BASE}/expired-instruments/expiries", instrument_key=IDX) or {}).get("data", []))
idx, cur = [], exps[0] - timedelta(days=10)
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)
by_day = defaultdict(dict)
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    by_day[ts.date()][ts.strftime("%H:%M")] = {"o": float(c[1]), "h": float(c[2]),
                                               "l": float(c[3]), "c": float(c[4]), "ts": ts}
days = sorted(by_day)
print(f"days: {len(days)}")

contract_cache, cand_cache = {}, {}


def contracts(exp):
    if exp not in contract_cache:
        j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=IDX, expiry_date=str(exp))
        contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                               for r in (j or {}).get("data", [])}
    return contract_cache[exp]


def opt_series(exp, strike, ot):
    ck = contracts(exp).get((float(strike), ot))
    if not ck:
        return {}
    if ck not in cand_cache:
        j = get(f"{BASE}/expired-instruments/historical-candle/{ck}/30minute/{exp}/{exp - timedelta(days=28)}")
        cand_cache[ck] = {(datetime.fromisoformat(c[0]).replace(tzinfo=None).date(),
                           datetime.fromisoformat(c[0]).replace(tzinfo=None).strftime("%H:%M")):
                          {"o": float(c[1]), "h": float(c[2]), "l": float(c[3]), "c": float(c[4])}
                          for c in (j or {}).get("data", {}).get("candles", [])}
    return cand_cache[ck]


# ── strategy: index drops > trigger% within last 2 bars -> buy ATM PE next bar
#    trail stop on PE close: exit when PE close < peak_close*(1-trail); EOD exit 15:15
def run(trigger_pct, trail_pct):
    rows = []
    for d in days:
        db_ = by_day[d]
        exp = next((e for e in exps if 0 <= (e - d).days <= 7), None)
        if exp is None:
            continue
        fired = False
        for i in range(2, len(BUCKETS) - 2):
            b0, b1, b2 = BUCKETS[i - 2], BUCKETS[i - 1], BUCKETS[i]
            if not all(b in db_ for b in (b0, b1, b2)):
                continue
            drop = db_[b2]["c"] / db_[b0]["c"] - 1
            if drop > -trigger_pct / 100:
                continue
            # trigger! enter at next bucket open (approx: this bucket close)
            entry_b = BUCKETS[i + 1]
            if entry_b not in db_:
                break
            atm = rnd50(db_[b2]["c"])
            ser = opt_series(exp, atm, "PE")
            pe_in = ser.get((d, entry_b))
            if not pe_in:
                break
            ein = pe_in["o"] * (1 + SLIP)
            peak = ein
            exit_px = None
            for b in BUCKETS[BUCKETS.index(entry_b):]:
                bar = ser.get((d, b))
                if not bar:
                    continue
                peak = max(peak, bar["c"])
                if bar["c"] < peak * (1 - trail_pct / 100):
                    exit_px = bar["c"] * (1 - SLIP)
                    break
            if exit_px is None:
                last = ser.get((d, "15:15")) or ser.get((d, "14:45"))
                if not last:
                    break
                exit_px = last["c"] * (1 - SLIP)
            net = (exit_px - ein) * LOT - charges_buy_sell(ein * LOT, exit_px * LOT)
            rows.append({"d": d, "net": net})
            fired = True
            break  # one trade per day
        _ = fired
    return pd.DataFrame(rows)


def report(df, label):
    if df.empty or len(df) < 25:
        print(f"{label}: too few trades ({len(df)})"); return
    df = df.sort_values("d")
    split = df.d.iloc[int(len(df) * 0.6)]
    for era, sub in (("IS ", df[df.d <= split]), ("OOS", df[df.d > split]), ("ALL", df)):
        s = sub.net
        w, l = s[s > 0], s[s <= 0]
        pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else 99
        print(f"  {era} n={len(s):3d} win%={len(w)/len(s)*100:3.0f} avg={s.mean():+7.0f} "
              f"tot={s.sum():+8.0f} PF={pf:5.2f} best={s.max():+7.0f} worst={s.min():+7.0f}")


for trig in (0.4, 0.6, 0.8):
    for trail in (20, 30):
        print(f"\n=== buy ATM PE on {trig}% 1h-drop, trail {trail}% ===")
        report(run(trig, trail), "pe_momo")

# ── precursor scan: what did mornings look like before big afternoon falls?
print("\n=== precursor scan: days where 13:45->15:15 fell >0.8% ===")
feats = []
for d in days:
    db_ = by_day[d]
    if not all(b in db_ for b in ("09:15", "13:45", "15:15")):
        continue
    pm = db_["15:15"]["c"] / db_["13:45"]["c"] - 1
    am = db_["13:45"]["c"] / db_["09:15"]["o"] - 1
    feats.append({"d": d, "pm": pm, "am": am})
f = pd.DataFrame(feats)
crash = f[f.pm < -0.008]
print(f"afternoon crashes: {len(crash)}/{len(f)} days ({len(crash)/len(f)*100:.1f}%)")
print(f"morning move on crash days:  median {crash.am.median()*100:+.2f}%  (all days {f.am.median()*100:+.2f}%)")
print(f"P(afternoon crash | morning down >0.3%): {len(f[(f.am < -0.003) & (f.pm < -0.008)]) / max(1,len(f[f.am < -0.003]))*100:.1f}%")
print(f"P(afternoon crash | morning up/flat):    {len(f[(f.am >= -0.003) & (f.pm < -0.008)]) / max(1,len(f[f.am >= -0.003]))*100:.1f}%")
print("DONE")
