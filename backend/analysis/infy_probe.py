"""Probe: can we get INFY equity bars + expired option contracts from Upstox?
If yes, we can backtest INFY option strategies (esp. earnings-gap behaviour)."""
import asyncio, time
from datetime import date, timedelta, datetime
import httpx

BASE = "https://api.upstox.com/v2"
# INFY equity instrument key (ISIN INE009A01021)
INFY_EQ = "NSE_EQ|INE009A01021"


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
            return r.status_code, (r.json() if r.status_code == 200 else r.text[:200])
        except Exception as e:
            time.sleep(0.5)
    return None, "fail"

out = []

# 1. Equity daily bars (last 2 years)
sc, j = get(f"{BASE}/historical-candle/{INFY_EQ}/day/{date.today()}/{date.today()-timedelta(days=730)}")
n = len(j.get("data", {}).get("candles", [])) if sc == 200 and isinstance(j, dict) else 0
out.append(f"INFY equity daily bars: status={sc} candles={n}")
if n:
    cs = j["data"]["candles"]
    last = cs[0]
    out.append(f"  latest bar: {last[0][:10]} close={last[4]}")

# 2. Expired option expiries for INFY
sc, j = get(f"{BASE}/expired-instruments/expiries", instrument_key=INFY_EQ)
exps = j.get("data", []) if sc == 200 and isinstance(j, dict) else []
out.append(f"INFY expired-option expiries: status={sc} count={len(exps)}")
if exps:
    out.append(f"  sample expiries: {sorted(exps)[-6:]}")

# 3. Try an option contract list for the most recent expiry
if exps:
    exp = sorted(exps)[-1]
    sc, j = get(f"{BASE}/expired-instruments/option/contract", instrument_key=INFY_EQ, expiry_date=exp)
    contracts = j.get("data", []) if sc == 200 and isinstance(j, dict) else []
    out.append(f"INFY option contracts for {exp}: status={sc} count={len(contracts)}")
    if contracts:
        strikes = sorted({c.get("strike_price") for c in contracts})
        out.append(f"  strikes range: {strikes[0]}..{strikes[-1]} ({len(strikes)} strikes)")
        # try candles for one contract
        ck = contracts[len(contracts)//2].get("instrument_key")
        sc, j = get(f"{BASE}/expired-instruments/historical-candle/{ck}/day/{exp}/{exp}")
        nn = len(j.get("data", {}).get("candles", [])) if sc == 200 and isinstance(j, dict) else 0
        out.append(f"  sample contract daily candles: status={sc} n={nn}")

print("\n".join(out))
print("DONE")
