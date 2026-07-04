"""
TEST BEFORE SUGGESTING: does trading the overnight strangle ONLY when premium
is historically rich fix the post-2022 breakdown?
Signal: today's credit as % of spot vs its trailing 252-day percentile.
Variants: trade only when percentile > 50 / > 70; also the opposite (< 50)
as a control. Baseline = trade every day. 10y real bhav closes.
"""
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
import numpy as np

BHAV = Path("/app/market_data/bhav")
LOT = 65

frames = []
for f in sorted(BHAV.glob("fo*.csv")):
    try:
        df = pd.read_csv(f, usecols=["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR",
                                     "OPTION_TYP", "CLOSE", "TIMESTAMP"], low_memory=False)
    except Exception:
        continue
    df = df[(df["SYMBOL"] == "NIFTY") & (df["INSTRUMENT"].isin(["OPTIDX", "FUTIDX"]))]
    if len(df):
        frames.append(df)

raw = pd.concat(frames, ignore_index=True)
raw["date"] = pd.to_datetime(raw["TIMESTAMP"], dayfirst=True, errors="coerce").dt.date
raw["expiry"] = pd.to_datetime(raw["EXPIRY_DT"], dayfirst=True, errors="coerce").dt.date
raw = raw.dropna(subset=["date", "expiry"])

opts = raw[raw["INSTRUMENT"] == "OPTIDX"]
futs = raw[raw["INSTRUMENT"] == "FUTIDX"]
fut_close = futs.sort_values("expiry").groupby("date").first()["CLOSE"].to_dict()
px = {(r.date, r.expiry, float(r.STRIKE_PR), r.OPTION_TYP): float(r.CLOSE)
      for r in opts.itertuples()}
exp_by_day = opts.groupby("date")["expiry"].agg(lambda s: sorted(set(s))).to_dict()
days = sorted(fut_close)


def rnd50(x):
    return round(x / 50) * 50


def charges(et, xt):
    b = min(20.0, et * 0.0003) * 2 + min(20.0, xt * 0.0003) * 2
    return b + et * 0.001 + (et + xt) * 0.00053 + (b + (et + xt) * 0.00053) * 0.18 + xt * 0.00003


rows = []
for i, d in enumerate(days[:-1]):
    nxt = days[i + 1]
    spot = fut_close[d]
    exps = exp_by_day.get(d)
    if not exps:
        continue
    monthlies = {max(e for e in exps if (e.year, e.month) == (m.year, m.month)) for m in exps}
    exp = next((e for e in sorted(exps) if e in monthlies and 21 <= (e - d).days <= 60), None)
    if exp is None:
        continue
    pk, ck = float(rnd50(spot * 0.972)), float(rnd50(spot * 1.024))
    pi, ci = px.get((d, exp, pk, "PE")), px.get((d, exp, ck, "CE"))
    po, co = px.get((nxt, exp, pk, "PE")), px.get((nxt, exp, ck, "CE"))
    if None in (pi, ci, po, co) or pi < 5 or ci < 5:
        continue
    credit, debit = pi + ci, po + co
    dte = (exp - d).days
    net = (credit - debit) * LOT - charges(credit * LOT, debit * LOT)
    # normalize: credit as % of spot, per unit sqrt(dte) (richness measure)
    rich = (credit / spot) / np.sqrt(dte)
    rows.append({"d": d, "net": net, "rich": rich})

t = pd.DataFrame(rows).sort_values("d").reset_index(drop=True)
t["pctl"] = t["rich"].rolling(252, min_periods=100).apply(
    lambda w: (w < w.iloc[-1]).mean() * 100, raw=False)
t = t.dropna(subset=["pctl"])
t["yr"] = pd.to_datetime(t["d"].astype(str)).dt.year


def report(name, sub):
    if not len(sub):
        print(f"{name}: no trades")
        return
    wins, loss = sub[sub.net > 0], sub[sub.net <= 0]
    pf = wins.net.sum() / abs(loss.net.sum()) if len(loss) else 99
    eq = sub.sort_values("d").net.cumsum()
    dd = (eq - eq.cummax()).min()
    recent = sub[sub.yr >= 2023]
    rpf = 0
    if len(recent):
        rw, rl = recent[recent.net > 0], recent[recent.net <= 0]
        rpf = rw.net.sum() / abs(rl.net.sum()) if len(rl) else 99
    print(f"{name:28} {len(sub):5d}t | PF {pf:4.2f} | net Rs{sub.net.sum():>10,.0f} | "
          f"worst Rs{sub.net.min():>8,.0f} | maxDD Rs{dd:>9,.0f} | "
          f"2023+: {len(recent):4d}t PF {rpf:4.2f} net Rs{recent.net.sum():>9,.0f}")


print(f"eligible days with 252d history: {len(t)} ({t.d.min()} → {t.d.max()})\n")
report("BASELINE (every day)", t)
report("RICH only (pctl > 50)", t[t.pctl > 50])
report("VERY RICH only (pctl > 70)", t[t.pctl > 70])
report("EXTREME only (pctl > 85)", t[t.pctl > 85])
report("CONTROL: THIN (pctl < 50)", t[t.pctl < 50])
