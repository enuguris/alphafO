"""
PHASE B SURVEY: single-stock options — where is the less efficient pond?
From 10y bhav: per underlying, measure (recent 12 months)
  - liquidity: median daily contracts traded in near-ATM options
  - premium richness: median ATM straddle as % of spot, per sqrt(week)
  - spread viability: how many strikes have OI > threshold
Output: shortlist of stock underlyings where index-style credit spreads are
mechanically tradeable. No strategy conclusions yet — this is terrain mapping.
"""
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

BHAV = Path("/app/market_data/bhav")
CUTOFF = date.today() - timedelta(days=365)

frames = []
for f in sorted(BHAV.glob("fo*.csv")):
    try:
        df = pd.read_csv(f, usecols=["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR",
                                     "OPTION_TYP", "CLOSE", "TIMESTAMP", "CONTRACTS", "OPEN_INT"],
                         low_memory=False)
    except Exception:
        continue
    df = df[df.INSTRUMENT.isin(["OPTSTK", "FUTSTK"])]
    if not len(df):
        continue
    df["date"] = pd.to_datetime(df.TIMESTAMP, dayfirst=True, errors="coerce").dt.date
    df = df[df.date >= CUTOFF]
    if len(df):
        frames.append(df)

raw = pd.concat(frames, ignore_index=True)
raw["expiry"] = pd.to_datetime(raw.EXPIRY_DT, dayfirst=True, errors="coerce").dt.date
print(f"stock F&O rows (last 12mo): {len(raw):,} | underlyings: {raw.SYMBOL.nunique()}")

futs = raw[raw.INSTRUMENT == "FUTSTK"]
opts = raw[raw.INSTRUMENT == "OPTSTK"]
spot = futs.sort_values("expiry").groupby(["SYMBOL", "date"]).first()["CLOSE"]

rows = []
for sym, g in opts.groupby("SYMBOL"):
    days_n = g.date.nunique()
    if days_n < 150:
        continue
    # near-ATM = strike within 3% of that day's future close
    rec = []
    for (d), gg in g.groupby("date"):
        s = spot.get((sym, d))
        if s is None or s <= 0:
            continue
        near = gg[(gg.STRIKE_PR / s - 1).abs() < 0.03]
        if not len(near):
            continue
        # nearest expiry only
        ne = near[near.expiry == near.expiry.min()]
        vol = ne.CONTRACTS.sum()
        # ATM straddle richness (nearest strike CE+PE close / spot)
        k = ne.iloc[(ne.STRIKE_PR - s).abs().argsort()].STRIKE_PR.iloc[0]
        ce = ne[(ne.STRIKE_PR == k) & (ne.OPTION_TYP == "CE")].CLOSE
        pe = ne[(ne.STRIKE_PR == k) & (ne.OPTION_TYP == "PE")].CLOSE
        dte = max((ne.expiry.min() - d).days, 1)
        if len(ce) and len(pe):
            rich = (float(ce.iloc[0]) + float(pe.iloc[0])) / s / np.sqrt(dte / 7) * 100
            rec.append({"vol": vol, "rich": rich,
                        "oi_strikes": (ne.OPEN_INT > 10000).sum()})
    if len(rec) < 100:
        continue
    r = pd.DataFrame(rec)
    rows.append({"symbol": sym, "days": len(r),
                 "med_daily_contracts": r.vol.median(),
                 "straddle_pct_per_wk": r.rich.median(),
                 "med_liquid_strikes": r.oi_strikes.median()})

t = pd.DataFrame(rows)
t = t[t.med_daily_contracts > 2000]          # minimum viable liquidity
t = t.sort_values("straddle_pct_per_wk", ascending=False)
print(f"\nunderlyings passing liquidity screen (>2k contracts/day near ATM): {len(t)}")
print(f"\n{'symbol':14} {'medContr/d':>10} {'straddle%/wk':>13} {'liqStrikes':>10}")
for r in t.head(25).itertuples():
    print(f"{r.symbol:14} {r.med_daily_contracts:>10,.0f} {r.straddle_pct_per_wk:>12.2f}% {r.med_liquid_strikes:>10.0f}")
print(f"\n(NIFTY reference: ATM straddle typically ~1.0-1.3%/wk of spot)")
print("DONE")
