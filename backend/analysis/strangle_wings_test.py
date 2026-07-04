"""Naked strangle vs WINGED strangle (iron condor) — 10y real bhav closes."""
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

opts = raw[raw["INSTRUMENT"] == "OPTIDX"]
futs = raw[raw["INSTRUMENT"] == "FUTIDX"]
fut_close = futs.sort_values("expiry").groupby("date").first()["CLOSE"].to_dict()
px = {(r.date, r.expiry, float(r.STRIKE_PR), r.OPTION_TYP): float(r.CLOSE)
      for r in opts.itertuples()}
exp_by_day = opts.groupby("date")["expiry"].agg(lambda s: sorted(set(s))).to_dict()
days = sorted(fut_close)


def rnd50(x):
    return round(x / 50) * 50


def charges(et, xt, legs=2):
    b = min(20.0, et * 0.0003) * legs + min(20.0, xt * 0.0003) * legs
    return b + et * 0.001 + (et + xt) * 0.00053 + (b + (et + xt) * 0.00053) * 0.18 + xt * 0.00003


naked, winged = [], []
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
    wpk, wck = float(rnd50(spot * 0.952)), float(rnd50(spot * 1.044))   # wings ~2% beyond
    pi, ci = px.get((d, exp, pk, "PE")), px.get((d, exp, ck, "CE"))
    po, co = px.get((nxt, exp, pk, "PE")), px.get((nxt, exp, ck, "CE"))
    wpi, wci = px.get((d, exp, wpk, "PE")), px.get((d, exp, wck, "CE"))
    wpo, wco = px.get((nxt, exp, wpk, "PE")), px.get((nxt, exp, wck, "CE"))
    if None in (pi, ci, po, co, wpi, wci, wpo, wco) or pi < 5 or ci < 5:
        continue

    # naked strangle
    cr_n, db_n = pi + ci, po + co
    net_n = (cr_n - db_n) * LOT - charges(cr_n * LOT, db_n * LOT, 2)

    # winged (iron condor): shorts minus longs
    cr_w = (pi + ci) - (wpi + wci)
    db_w = (po + co) - (wpo + wco)
    turn_in = (pi + ci + wpi + wci) * LOT
    turn_out = (po + co + wpo + wco) * LOT
    net_w = (cr_w - db_w) * LOT - charges(turn_in, turn_out, 4)

    naked.append({"d": d, "net": net_n, "credit": cr_n})
    winged.append({"d": d, "net": net_w, "credit": cr_w,
                   "wing_cost": wpi + wci,
                   "max_loss": (max(pk - wpk, wck - ck) - cr_w) * LOT})


def report(name, rows):
    t = pd.DataFrame(rows)
    wins, loss = t[t.net > 0], t[t.net <= 0]
    pf = wins.net.sum() / abs(loss.net.sum()) if len(loss) else 99
    eq = t.net.cumsum()
    dd = (eq - eq.cummax()).min()
    print(f"\n=== {name} ({len(t)} identical days) ===")
    print(f"win {len(wins)/len(t)*100:.1f}% | PF {pf:.2f} | net Rs{t.net.sum():,.0f} | "
          f"avg Rs{t.net.mean():,.0f} | worst Rs{t.net.min():,.0f} | maxDD Rs{dd:,.0f}")
    t["yr"] = pd.to_datetime(t["d"].astype(str)).dt.year
    recent = t[t.yr >= 2023]
    if len(recent):
        rw = recent[recent.net > 0]
        rl = recent[recent.net <= 0]
        rpf = rw.net.sum() / abs(rl.net.sum()) if len(rl) else 99
        print(f"2023+ only: {len(recent)}t | PF {rpf:.2f} | net Rs{recent.net.sum():,.0f} | "
              f"worst Rs{recent.net.min():,.0f}")
    return t


tn = report("NAKED strangle", naked)
tw = report("WINGED (iron condor, wings ~2% beyond)", winged)

w = pd.DataFrame(winged)
print(f"\nwing cost: avg {w.wing_cost.mean():.1f} pts = "
      f"{w.wing_cost.mean()/pd.DataFrame(naked).credit.mean()*100:.0f}% of naked credit")
print(f"winged structural max loss: avg Rs{w.max_loss.mean():,.0f} "
      f"(naked has NO cap)")
print(f"approx margin: naked ~Rs170,000 | winged ~Rs{w.max_loss.mean():,.0f} → "
      f"capital efficiency ~{170000/max(w.max_loss.mean(),1):.0f}x better")
