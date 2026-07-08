"""Batman (double butterfly) + double calendar on real Upstox expired data.
NIFTY weeklies, entry ~6d before expiry at 09:45, settle/exit at expiry close.
Slippage 0.5%/leg adverse, leg-level charges, IS/OOS 60/40 by expiry.
"""
import asyncio, time
from datetime import date, timedelta, datetime
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


def leg_charge(premium_value, side):
    """Entry-side charges per leg (1 lot): brokerage, txn, GST, STT on sells."""
    brok = min(20.0, premium_value * 0.0003)
    txn = premium_value * 0.00053
    stt = premium_value * 0.001 if side == "SELL" else 0.0
    gst = (brok + txn) * 0.18
    return brok + txn + stt + gst


def settle_charge(intrinsic_value):
    """Expiry settlement: STT 0.125% on ITM exercise value (long legs)."""
    return intrinsic_value * 0.00125


exps = sorted(date.fromisoformat(x) for x in
              (get(f"{BASE}/expired-instruments/expiries", instrument_key=IDX) or {}).get("data", []))
print(f"expiries: {len(exps)}  {exps[0]} -> {exps[-1]}")

# index 30-min candles for spot at entry + settle close
idx, cur = [], exps[0] - timedelta(days=12)
while cur < date.today():
    to = min(cur + timedelta(days=80), date.today())
    j = get(f"{BASE}/historical-candle/{IDX}/30minute/{to}/{cur}")
    idx += (j or {}).get("data", {}).get("candles", [])
    cur = to + timedelta(days=1)
spot_at = {}
for c in idx:
    ts = datetime.fromisoformat(c[0]).replace(tzinfo=None)
    spot_at[(ts.date(), ts.strftime("%H:%M"))] = float(c[4])
days_avail = sorted({d for d, _ in spot_at})

contract_cache, cand_cache = {}, {}


def contracts(exp):
    if exp not in contract_cache:
        j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=IDX, expiry_date=str(exp))
        contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                               for r in (j or {}).get("data", [])}
    return contract_cache[exp]


def px(exp, strike, ot, day, hhmm):
    key = contracts(exp).get((float(strike), ot))
    if not key:
        return None
    if key not in cand_cache:
        j = get(f"{BASE}/expired-instruments/historical-candle/{key}/30minute/{exp}/{exp - timedelta(days=28)}")
        cand_cache[key] = {(datetime.fromisoformat(c[0]).replace(tzinfo=None).date(),
                            datetime.fromisoformat(c[0]).replace(tzinfo=None).strftime("%H:%M")): float(c[4])
                           for c in (j or {}).get("data", {}).get("candles", [])}
    return cand_cache[key].get((day, hhmm))


def entry_day(exp):
    cands = [d for d in days_avail if 4 <= (exp - d).days <= 7 and (d, "09:45") in spot_at]
    return cands[0] if cands else None


def settle_close(exp):
    return spot_at.get((exp, "15:15")) or spot_at.get((exp, "14:45"))


def run_batman(offset, wing):
    rows = []
    for exp in exps:
        ed = entry_day(exp)
        sc = settle_close(exp)
        if not ed or not sc:
            continue
        S = spot_at[(ed, "09:45")]
        cl, ch = rnd50(S - offset), rnd50(S + offset)
        # put fly at cl, call fly at ch (1-2-1, width=wing)
        legs = [("PE", cl + wing, +1), ("PE", cl, -2), ("PE", cl - wing, +1),
                ("CE", ch - wing, +1), ("CE", ch, -2), ("CE", ch + wing, +1)]
        cash = chg = 0.0
        ok = True
        for ot, k, q in legs:
            p = px(exp, k, ot, ed, "09:45")
            if p is None:
                ok = False; break
            fill = p * (1 + SLIP) if q > 0 else p * (1 - SLIP)
            cash -= q * fill * LOT
            chg += leg_charge(abs(q) * fill * LOT, "BUY" if q > 0 else "SELL")
        if not ok:
            continue
        # settle at expiry close
        for ot, k, q in legs:
            intr = max(0.0, (sc - k) if ot == "CE" else (k - sc))
            cash += q * intr * LOT
            if q > 0 and intr > 0:
                chg += settle_charge(q * intr * LOT)
        rows.append({"exp": exp, "net": cash - chg})
    return pd.DataFrame(rows)


def run_dcal(offset):
    rows = []
    for i, exp in enumerate(exps[:-1]):
        far = exps[i + 1]
        if not 5 <= (far - exp).days <= 9:
            continue
        ed = entry_day(exp)
        sc = settle_close(exp)
        if not ed or not sc:
            continue
        S = spot_at[(ed, "09:45")]
        kc, kp = rnd50(S + offset), rnd50(S - offset)
        legs = [("CE", kc, -1, exp), ("PE", kp, -1, exp),   # sell near
                ("CE", kc, +1, far), ("PE", kp, +1, far)]   # buy far
        cash = chg = 0.0
        ok = True
        for ot, k, q, e in legs:
            p = px(e, k, ot, ed, "09:45")
            if p is None:
                ok = False; break
            fill = p * (1 + SLIP) if q > 0 else p * (1 - SLIP)
            cash -= q * fill * LOT
            chg += leg_charge(abs(q) * fill * LOT, "BUY" if q > 0 else "SELL")
        if not ok:
            continue
        # exit everything at near expiry 15:15: near legs at intrinsic, far at market
        for ot, k, q, e in legs:
            if e == exp:
                v = max(0.0, (sc - k) if ot == "CE" else (k - sc))
                cash += q * v * LOT
                chg += settle_charge(abs(q) * v * LOT) if v > 0 else 0.0
            else:
                p = px(e, k, ot, exp, "15:15") or px(e, k, ot, exp, "14:45")
                if p is None:
                    ok = False; break
                fill = p * (1 - SLIP) if q > 0 else p * (1 + SLIP)  # closing: sell longs
                cash += q * fill * LOT
                chg += leg_charge(abs(q) * fill * LOT, "SELL" if q > 0 else "BUY")
        if not ok:
            continue
        rows.append({"exp": exp, "net": cash - chg})
    return pd.DataFrame(rows)


def report(df, label):
    if df.empty or len(df) < 20:
        print(f"{label}: too few trades ({len(df)})")
        return
    split = df.exp.iloc[int(len(df) * 0.6)]
    for era, sub in (("IS ", df[df.exp <= split]), ("OOS", df[df.exp > split]), ("ALL", df)):
        s = sub.net
        w, l = s[s > 0], s[s <= 0]
        pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else float("inf")
        print(f"  {era} n={len(s):3d} win%={len(w)/len(s)*100:3.0f} avg={s.mean():+7.0f} "
              f"total={s.sum():+8.0f} PF={pf:4.2f} worst={s.min():+7.0f}")


for off, wing in [(100, 100), (150, 100), (200, 150)]:
    print(f"\n=== BATMAN offset={off} wing={wing} (6 legs, hold to expiry) ===")
    report(run_batman(off, wing), "batman")

for off in (100, 200, 300):
    print(f"\n=== DOUBLE CALENDAR offset={off} (4 legs, exit at near expiry) ===")
    report(run_dcal(off), "dcal")
print("\nDONE")
