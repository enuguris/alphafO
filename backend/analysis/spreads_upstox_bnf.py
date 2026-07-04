"""
The system's PLAIN WINGED SPREADS on REAL Upstox expired 30-min prices.
BullPut: sell ATM PE + buy PE 2 steps below (trend up).
BearCall: sell ATM CE + buy CE 2 steps above (trend down).
Weekly expiry >= 7 DTE. Managed exits on 30-min marks:
TP when unrealized >= 50% of credit, SL at -2x credit, time exit at half DTE,
else settle at last mark before expiry. Entry spacing: 7 sessions per strategy.
"""
import asyncio, time, warnings
warnings.filterwarnings("ignore")
from datetime import date, timedelta, datetime
from collections import defaultdict
import httpx

LOT = 30
STEP = 100
BASE = "https://api.upstox.com/v2"
IDX = "NSE_INDEX|Nifty Bank"


def rnd50(x):
    return round(x / STEP) * STEP


def charges(entry_turn, exit_turn):
    b = min(20.0, entry_turn * 0.0003) * 2 + min(20.0, exit_turn * 0.0003) * 2
    return (b + entry_turn * 0.001 + (entry_turn + exit_turn) * 0.00053
            + (b + (entry_turn + exit_turn) * 0.00053) * 0.18 + exit_turn * 0.00003)


async def get_token():
    from app.database import AsyncSessionLocal
    from app.models.kite_config import KiteConfig
    from app.core.encryption import decrypt
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        cfg = (await db.execute(select(KiteConfig).limit(1))).scalar_one_or_none()
    return decrypt(cfg.upstox_access_token_enc)


def main():
    token = asyncio.get_event_loop().run_until_complete(get_token())
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
    print(f"expired expiries: {len(exps)} ({exps[0]} → {exps[-1]})")

    # index 30-min candles
    start = exps[0] - timedelta(days=40)
    idx = []
    cur = start
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
    days = sorted(by_day.keys())
    day_close = {d: by_day[d][-1][1] for d in days}
    print(f"sessions: {len(days)}")

    contract_cache, cand_cache = {}, {}

    def contracts(exp):
        if exp not in contract_cache:
            j = get(f"{BASE}/expired-instruments/option/contract",
                    instrument_key=IDX, expiry_date=str(exp))
            contract_cache[exp] = {(float(r.get("strike_price", 0)), r.get("instrument_type", "")): r["instrument_key"]
                                   for r in (j or {}).get("data", [])}
        return contract_cache[exp]

    def candles(key, exp):
        if key not in cand_cache:
            j = get(f"{BASE}/expired-instruments/historical-candle/{key}/30minute/{exp}/{exp - timedelta(days=40)}")
            rows = sorted((datetime.fromisoformat(c[0]).replace(tzinfo=None), float(c[4]))
                          for c in (j or {}).get("data", {}).get("candles", []))
            cand_cache[key] = rows
        return cand_cache[key]

    def px_at(rows, ts):
        best = None
        for t, p in rows:
            if t <= ts:
                best = p
            else:
                break
        return best

    trades = []
    last_entry = {"BullPut": -99, "BearCall": -99}
    skipped = 0
    for i, d in enumerate(days):
        if i < 10 or i >= len(days) - 1:
            continue
        sma10 = sum(day_close[days[j]] for j in range(i - 10, i)) / 10
        ts_in, spot = by_day[d][-1]
        trend_up = spot > sma10
        strat = "BullPut" if trend_up else "BearCall"
        if i - last_entry[strat] < 7:
            continue
        exp = next((e for e in exps if (e - d).days >= 7), None)
        if exp is None or (exp - d).days > 35:
            skipped += 1
            continue
        dte = (exp - d).days
        cmap = contracts(exp)
        atm = float(rnd50(spot))
        if strat == "BullPut":
            sk, wk, ot = atm, atm - 2 * STEP, "PE"
        else:
            sk, wk, ot = atm, atm + 2 * STEP, "CE"
        k_s, k_w = cmap.get((sk, ot)), cmap.get((wk, ot))
        if not k_s or not k_w:
            skipped += 1
            continue
        rs, rw = candles(k_s, exp), candles(k_w, exp)
        s_in, w_in = px_at(rs, ts_in), px_at(rw, ts_in)
        if s_in is None or w_in is None or s_in < 5:
            skipped += 1
            continue
        credit = s_in - w_in
        width = 2 * STEP
        if not (width * 0.20 <= credit <= width * 0.80):   # live gate
            skipped += 1
            continue
        tp_level, sl_level = credit * 0.50, -(credit * 2.0)
        half_dte_date = d + timedelta(days=max(1, dte // 2))

        exit_px_s = exit_px_w = None
        exit_reason, exit_day = "expiry_mark", None
        done = False
        for j in range(i + 1, len(days)):
            dd = days[j]
            if dd > exp:
                break
            for ts2, _ in by_day[dd]:
                s2, w2 = px_at(rs, ts2), px_at(rw, ts2)
                if s2 is None or w2 is None:
                    continue
                unreal = (credit - (s2 - w2))
                if unreal >= tp_level:
                    exit_px_s, exit_px_w, exit_reason, exit_day, done = s2, w2, "target", dd, True
                    break
                if unreal <= sl_level:
                    exit_px_s, exit_px_w, exit_reason, exit_day, done = s2, w2, "stop", dd, True
                    break
            if done:
                break
            if dd >= half_dte_date:
                ts_last = by_day[dd][-1][0]
                exit_px_s, exit_px_w = px_at(rs, ts_last), px_at(rw, ts_last)
                exit_reason, exit_day, done = "time_exit", dd, True
                break
        if not done:
            last_d = max((x for x in days if x <= exp and x > d), default=None)
            if last_d is None:
                skipped += 1
                continue
            ts_last = by_day[last_d][-1][0]
            exit_px_s, exit_px_w = px_at(rs, ts_last), px_at(rw, ts_last)
            exit_day = last_d
        if exit_px_s is None or exit_px_w is None:
            skipped += 1
            continue

        debit = exit_px_s - exit_px_w
        turn_in = (s_in + w_in) * LOT
        turn_out = (exit_px_s + exit_px_w) * LOT
        net = (credit - debit) * LOT - charges(turn_in, turn_out)
        last_entry[strat] = i
        trades.append({"d": d, "strat": strat, "exp": exp, "dte": dte, "credit": credit,
                       "net": net, "reason": exit_reason, "exit_day": exit_day,
                       "hold": (exit_day - d).days})
        time.sleep(0.05)

    client.close()

    import pandas as pd
    t = pd.DataFrame(trades)
    print(f"\ntrades: {len(t)} | skipped: {skipped}")
    for name, g in [("ALL", t)] + list(t.groupby("strat")):
        wins, loss = g[g.net > 0], g[g.net <= 0]
        pf = wins.net.sum() / abs(loss.net.sum()) if len(loss) else 99
        eq = g.sort_values("d").net.cumsum()
        dd = (eq - eq.cummax()).min() if len(eq) else 0
        print(f"{name:9} {len(g):3d}t | WIN {len(wins)/len(g)*100:5.1f}% | PF {pf:5.2f} | "
              f"net Rs{g.net.sum():>9,.0f} | avg Rs{g.net.mean():>6,.0f} | "
              f"worst Rs{g.net.min():>8,.0f} | maxDD Rs{dd:>9,.0f} | avg hold {g.hold.mean():.1f}d")
    print("\nexit reasons:", t.reason.value_counts().to_dict())
main()
