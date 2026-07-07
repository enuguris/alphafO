"""Verify synthetic OHLCV now ends at real Redis spot for every timeframe."""
import redis
from app.config import settings
from app.core.scanner import synthetic_ohlcv as _synthetic_ohlcv

r = redis.from_url(settings.redis_url, decode_responses=True)
for ul in ("NIFTY", "BANKNIFTY"):
    spot = float(r.get(f"spot:{ul}"))
    for tf in ("15m", "1h", "4h", "daily"):
        df = _synthetic_ohlcv(ul, tf)
        last = float(df["close"].iloc[-1])
        dev = (last / spot - 1) * 100
        flag = "OK" if abs(dev) < 2 else "BAD"
        print(f"{ul:10s} {tf:5s} spot={spot:9.1f} synth_close={last:9.1f} dev={dev:+6.2f}% {flag}")
