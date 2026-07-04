"""Overnight strangle on REAL bhav option closes — every strike, 5 years."""
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd

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
print(f"{len(frames)} files | {raw['date'].min()} → {raw['date'].max()}")

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


trades = []
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
    net = (credit - debit) * LOT - charges(credit * LOT, debit * LOT)
    trades.append({"d": d, "net": net})

t = pd.DataFrame(trades)
wins, loss = t[t.net > 0], t[t.net <= 0]
pf = wins.net.sum() / abs(loss.net.sum())
eq = t.net.cumsum()
dd = (eq - eq.cummax()).min()
print(f"\ntrades {len(t)} | win {len(wins)/len(t)*100:.1f}% | PF {pf:.2f} | "
      f"net Rs{t.net.sum():,.0f} | avg Rs{t.net.mean():,.0f} | worst Rs{t.net.min():,.0f} | maxDD Rs{dd:,.0f}")
t["yr"] = pd.to_datetime(t["d"].astype(str)).dt.year
print("\nper year:")
for yr, g in t.groupby("yr"):
    print(f"{yr}: {len(g):3d}t win {(g.net>0).mean()*100:4.1f}% net Rs{g.net.sum():>10,.0f} worst Rs{g.net.min():>9,.0f}")
print("\n5 worst days:")
for r in t.nsmallest(5, "net").itertuples():
    print(f"{r.d}  Rs{r.net:,.0f}")
