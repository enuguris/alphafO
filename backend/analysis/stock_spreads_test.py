"""
SLEEVE TWO CANDIDATE: the champion credit-spread playbook on single-stock
options (liquid+rich shortlist from the terrain survey), REAL bhav closes,
last 3 years (the current regime).

Per underlying: trend via 10-SMA of near future close. Uptrend -> BullPut
(sell nearest-below-ATM strike PE, buy next strike below). Downtrend ->
BearCall mirrored. Monthly expiry 7-35 DTE. Managed exits on daily closes:
TP 50% credit / SL 2x credit / half-DTE / expiry intrinsic. Entries Tue-Thu,
>=5 sessions apart per name. Strikes = actually listed strikes that day.
Extra slippage 1.5% of each premium (stock option spreads are wider).
IS/OOS split 60/40.
"""
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

BHAV = Path("/app/market_data/bhav")
CUTOFF = date.today() - timedelta(days=3 * 365)
SYMS = ["DIXON", "BSE", "MCX", "COFORGE", "KAYNES", "PERSISTENT",
        "ANGELONE", "PAYTM", "MAZDOCK", "ADANIGREEN"]

frames = []
for f in sorted(BHAV.glob("fo*.csv")):
    try:
        df = pd.read_csv(f, usecols=["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR",
                                     "OPTION_TYP", "CLOSE", "TIMESTAMP", "CONTRACTS"],
                         low_memory=False)
    except Exception:
        continue
    df = df[df.SYMBOL.isin(SYMS)]
    if not len(df):
        continue
    df["date"] = pd.to_datetime(df.TIMESTAMP, dayfirst=True, errors="coerce").dt.date
    df = df[df.date >= CUTOFF]
    if len(df):
        frames.append(df)

raw = pd.concat(frames, ignore_index=True)
raw["expiry"] = pd.to_datetime(raw.EXPIRY_DT, dayfirst=True, errors="coerce").dt.date
raw = raw.dropna(subset=["date", "expiry"])
print(f"rows: {len(raw):,}")

LOT_APPROX = {}   # use notional sizing instead: qty = round(600000 / spot) approx? Use lot from contract value.
# NSE stock lots vary; approximate lot so that spot*lot ~= 7-8L (SEBI band)
def lot_for(spot):
    return max(1, int(round(750000 / spot / 25) * 25)) if spot > 0 else 1


def charges(et, xt):
    b = min(20.0, et * 0.0003) * 2 + min(20.0, xt * 0.0003) * 2
    return b + et * 0.001 + (et + xt) * 0.00053 + (b + (et + xt) * 0.00053) * 0.18 + xt * 0.00003


all_trades = []
for sym in SYMS:
    g = raw[raw.SYMBOL == sym]
    futs = g[g.INSTRUMENT == "FUTSTK"]
    opts = g[g.INSTRUMENT == "OPTSTK"]
    fclose = futs.sort_values("expiry").groupby("date").first()["CLOSE"].to_dict()
    days = sorted(fclose)
    if len(days) < 200:
        continue
    closes = pd.Series([fclose[d] for d in days], index=days)
    sma10 = closes.rolling(10).mean()
    px = {(r.date, r.expiry, float(r.STRIKE_PR), r.OPTION_TYP): float(r.CLOSE)
          for r in opts.itertuples()}
    vol = {(r.date, r.expiry, float(r.STRIKE_PR), r.OPTION_TYP): float(r.CONTRACTS or 0)
           for r in opts.itertuples()}
    chain_by_day = opts.groupby(["date", "expiry"])["STRIKE_PR"].agg(lambda s: sorted(set(float(x) for x in s)))

    last_i = -99
    for i, d in enumerate(days[:-1]):
        if d.weekday() not in (1, 2, 3) or i - last_i < 5 or i < 10:
            continue
        spot = fclose[d]
        exps = sorted(set(e for (dd, e) in chain_by_day.index if dd == d))
        exp = next((e for e in exps if 7 <= (e - d).days <= 35), None)
        if exp is None:
            continue
        strikes = chain_by_day.get((d, exp))
        if strikes is None or len(strikes) < 6:
            continue
        trend_up = spot > sma10[d]
        ot = "PE" if trend_up else "CE"
        below = [k for k in strikes if k <= spot]
        above = [k for k in strikes if k > spot]
        if len(below) < 2 or len(above) < 2:
            continue
        if trend_up:
            sk, wk = below[-1], below[-2]           # sell just below ATM PE, wing next below
        else:
            sk, wk = above[0], above[1]             # sell just above ATM CE, wing next above
        s_raw, w_raw = px.get((d, exp, sk, ot)), px.get((d, exp, wk, ot))
        if s_raw is None or w_raw is None or s_raw < 2:
            continue
        if vol.get((d, exp, sk, ot), 0) < 500:      # liquidity floor on the short leg
            continue
        s_in = s_raw * 0.985                        # slippage: sell 1.5% below close
        w_in = w_raw * 1.015                        # buy 1.5% above close
        credit = s_in - w_in
        width = abs(sk - wk)
        if not (width * 0.15 <= credit <= width * 0.85):
            continue
        qty = lot_for(spot)
        dte = (exp - d).days
        tp, sl = credit * 0.5, -(credit * 2.0)
        half_d = d + timedelta(days=max(1, dte // 2))

        pnl_pts, reason = None, "expiry"
        for j in range(i + 1, len(days)):
            dd = days[j]
            if dd >= exp:
                sp2 = fclose.get(dd, spot)
                intr_s = max(0, sp2 - sk) if ot == "CE" else max(0, sk - sp2)
                intr_w = max(0, sp2 - wk) if ot == "CE" else max(0, wk - sp2)
                pnl_pts = credit - (intr_s - intr_w)
                break
            s2, w2 = px.get((dd, exp, sk, ot)), px.get((dd, exp, wk, ot))
            if s2 is None or w2 is None:
                continue
            u = credit - (s2 - w2)
            if u >= tp:
                pnl_pts, reason = u, "target"
                break
            if u <= sl:
                pnl_pts, reason = u, "stop"
                break
            if dd >= half_d:
                pnl_pts, reason = u, "time"
                break
        if pnl_pts is None:
            continue
        turn = (s_in + w_in) * qty
        net = pnl_pts * qty - charges(turn, turn)
        last_i = i
        all_trades.append({"sym": sym, "d": d, "net": net, "reason": reason,
                           "strat": "BullPut" if trend_up else "BearCall"})

t = pd.DataFrame(all_trades)
print(f"total trades: {len(t)} across {t.sym.nunique()} symbols")
split = sorted(t.d)[int(len(t) * 0.6)]


def rep(name, g, min_n=8):
    if len(g) < min_n:
        return
    w, l = g[g.net > 0], g[g.net <= 0]
    pf = w.net.sum() / abs(l.net.sum()) if len(l) and l.net.sum() != 0 else 99
    print(f"  {name:24} {len(g):4d}t | WIN {len(w)/len(g)*100:5.1f}% | PF {pf:5.2f} | "
          f"net Rs{g.net.sum():>9,.0f} | avg Rs{g.net.mean():>6,.0f} | worst Rs{g.net.min():>8,.0f}")


print("\n=== pooled ===")
rep("ALL", t)
rep("IS", t[t.d <= split])
rep("OOS", t[t.d > split])
rep("BullPut", t[t.strat == "BullPut"])
rep("BearCall", t[t.strat == "BearCall"])
print("\n=== per symbol ===")
for sym, g in t.groupby("sym"):
    rep(sym, g)
print("\nexit mix:", t.reason.value_counts().to_dict())
print("DONE")
