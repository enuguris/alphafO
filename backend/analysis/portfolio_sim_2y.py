"""
PORTFOLIO SIMULATION: Rs10L compounding over ~2 years of REAL Upstox prices.
Sleeves (only validated ones):
  S1: NIFTY BearCall spreads — trend-down, Tue-Thu, ATM+wing, managed exits.
      Sizing: per-trade margin target = min(5% of capital, 8% of capital/open),
      max 6 concurrent, lots grow with capital.
  S2: 0DTE expiry-day straddle — every expiry, SL 40%/exit close.
      Sizing: 15% of capital / ~1.6L margin per lot (intraday only).
  S3: idle cash earns 6.5%/yr (liquid fund).
BullPut / BANKNIFTY / everything rejected: 0 allocation.
Outputs: equity curve, CAGR, max drawdown, monthly P&L, verdict vs Rs1Cr goal.
"""
import asyncio, time, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx
import pandas as pd
import numpy as np

LOT, STEP = 65, 50
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty 50"
START_CAPITAL = 1_000_000.0


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

start = exps[0] - timedelta(days=20)
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
days = sorted(by_day)
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
    for t2, p in rows:
        if t2 <= ts:
            b = p
        else:
            break
    return b


# ── build per-lot trade ledgers ──────────────────────────────────────────────
spread_ledger = []
last_i = -99
for i, d in enumerate(days):
    if i < 12 or i >= len(days) - 2 or d.weekday() not in (1, 2, 3) or i - last_i < 3:
        continue
    spot = close[d]
    if spot > sma10[d]:                      # BearCall needs downtrend
        continue
    exp = next((e for e in exps if 7 <= (e - d).days <= 20), None)
    if exp is None:
        continue
    cmap = contracts(exp)
    atm = float(rnd50(spot))
    ks, kw = cmap.get((atm, "CE")), cmap.get((atm + 2 * STEP, "CE"))
    if not ks or not kw:
        continue
    rs, rw = candles(ks, exp), candles(kw, exp)
    ts_in = by_day[d][-1][0]
    s_in, w_in = px_at(rs, ts_in), px_at(rw, ts_in)
    if s_in is None or w_in is None or s_in < 5:
        continue
    credit = s_in - w_in
    if not (STEP * 2 * 0.2 <= credit <= STEP * 2 * 0.8):
        continue
    dte = (exp - d).days
    tp, sl = credit * 0.5, -(credit * 2.0)
    half = d + timedelta(days=max(1, dte // 2))
    pnl, xday = None, None
    for j in range(i + 1, len(days)):
        dd = days[j]
        if dd > exp:
            break
        stop = False
        for ts2, _ in by_day[dd]:
            s2, w2 = px_at(rs, ts2), px_at(rw, ts2)
            if s2 is None or w2 is None:
                continue
            u = credit - (s2 - w2)
            if u >= tp or u <= sl:
                pnl, xday, stop = u, dd, True
                break
        if stop:
            break
        if dd >= half:
            ts_l = by_day[dd][-1][0]
            s2, w2 = px_at(rs, ts_l), px_at(rw, ts_l)
            if s2 is not None and w2 is not None:
                pnl, xday = credit - (s2 - w2), dd
            break
    if pnl is None:
        continue
    turn = (s_in + w_in) * LOT
    net_per_lot = pnl * LOT - charges(turn, turn, 2)
    margin_per_lot = (2 * STEP - credit) * LOT
    spread_ledger.append({"open": d, "close_d": xday, "net_lot": net_per_lot,
                          "margin_lot": max(margin_per_lot, 1000)})
    last_i = i

zdte_ledger = []
for exp in exps:
    if exp not in by_day or len(by_day[exp]) < 3:
        continue
    ts_o = by_day[exp][1][0]
    spot0 = by_day[exp][1][1]
    atm = float(rnd50(spot0))
    cmap = contracts(exp)
    kc, kp = cmap.get((atm, "CE")), cmap.get((atm, "PE"))
    if not kc or not kp:
        continue
    rc, rp = candles(kc, exp), candles(kp, exp)
    c_in, p_in = px_at(rc, ts_o), px_at(rp, ts_o)
    if not c_in or not p_in:
        continue
    credit = c_in + p_in
    exit_v = None
    for ts2, _ in by_day[exp][2:]:
        c2, p2 = px_at(rc, ts2), px_at(rp, ts2)
        if c2 is None or p2 is None:
            continue
        if c2 + p2 >= credit * 1.4:
            exit_v = c2 + p2
            break
    if exit_v is None:
        ts_l = by_day[exp][-1][0]
        c2, p2 = px_at(rc, ts_l), px_at(rp, ts_l)
        if c2 is None or p2 is None:
            continue
        exit_v = c2 + p2
    net_per_lot = (credit - exit_v) * LOT - charges(credit * LOT, exit_v * LOT, 2)
    zdte_ledger.append({"d": exp, "net_lot": net_per_lot, "spot": spot0})

client.close()
print(f"spread ledger: {len(spread_ledger)} trades | 0DTE ledger: {len(zdte_ledger)} expiries")

# ── portfolio sequencer with compounding ─────────────────────────────────────
cap = START_CAPITAL
open_spreads = []          # (close_d, lots, net_lot)
equity = []
sp_by_open = defaultdict(list)
for t in spread_ledger:
    sp_by_open[t["open"]].append(t)
z_by_day = {t["d"]: t for t in zdte_ledger}
trades_log = []

for d in days:
    # settle closing spreads
    still = []
    for close_d, lots, net_lot, margin in open_spreads:
        if d >= close_d:
            cap += net_lot * lots
            trades_log.append((close_d, "spread_close", lots, net_lot * lots))
        else:
            still.append((close_d, lots, net_lot, margin))
    open_spreads = still

    # 0DTE (intraday, margin returned same day)
    z = z_by_day.get(d)
    if z:
        lots_z = max(1, int(cap * 0.15 // (z["spot"] * LOT * 0.12)))
        cap += z["net_lot"] * lots_z
        trades_log.append((d, "0dte", lots_z, z["net_lot"] * lots_z))

    # new spreads
    for t in sp_by_open.get(d, []):
        if len(open_spreads) >= 6:
            continue
        deployed = sum(m * lots for _, lots, _, m in [(a, b, c, e) for a, b, c, e in open_spreads])
        target = min(cap * 0.05, max(0.0, cap * 0.5 - deployed) / 3)
        lots = int(target // t["margin_lot"])
        lots = max(1, min(lots, 25))
        open_spreads.append((t["close_d"], lots, t["net_lot"], t["margin_lot"]))
        trades_log.append((d, "spread_open", lots, 0))

    # idle interest (6.5%/yr on ~unblocked cash approximation: 60% of cap)
    cap += cap * 0.6 * 0.065 / 252
    equity.append({"d": d, "cap": cap})

eq = pd.DataFrame(equity)
eq["peak"] = eq.cap.cummax()
eq["dd"] = (eq.cap / eq.peak - 1) * 100
yrs = (days[-1] - days[0]).days / 365.25
cagr = (eq.cap.iloc[-1] / START_CAPITAL) ** (1 / yrs) - 1
print(f"\nwindow: {days[0]} → {days[-1]} ({yrs:.2f}y)")
print(f"final capital: Rs{eq.cap.iloc[-1]:,.0f}  (start Rs{START_CAPITAL:,.0f})")
print(f"total return: {(eq.cap.iloc[-1]/START_CAPITAL-1)*100:+.1f}%  |  CAGR: {cagr*100:+.1f}%/yr")
print(f"max drawdown: {eq.dd.min():.1f}%")
eq["ym"] = pd.to_datetime(eq.d.astype(str)).dt.to_period("M")
monthly = eq.groupby("ym").cap.last().pct_change() * 100
print(f"monthly returns: mean {monthly.mean():+.2f}% | best {monthly.max():+.1f}% | worst {monthly.min():+.1f}% | negative months {int((monthly<0).sum())}/{len(monthly)}")
print(f"\nyears to Rs1Cr at this CAGR: {np.log(10) / np.log(1 + cagr):,.1f}")
print("DONE")
