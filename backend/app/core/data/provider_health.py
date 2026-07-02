"""
Data-provider health tracker — records success/failure/latency per provider
(kite, upstox, nse_chain) in Redis so SystemHealth can show rotation status.

Keys:
  data_provider:{name}  — Redis hash: ok, fail, consec_fail, last_ok_ist,
                          last_fail_ist, last_err, avg_ms (EMA)
All writes are best-effort: a Redis outage must never break a price fetch.
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
PROVIDERS = ("kite", "upstox", "nse_chain")


def _r():
    import redis
    from app.config import settings
    return redis.from_url(settings.redis_url, decode_responses=True)


def record_success(provider: str, latency_ms: float | None = None) -> None:
    try:
        r = _r()
        key = f"data_provider:{provider}"
        pipe = r.pipeline()
        pipe.hincrby(key, "ok", 1)
        pipe.hset(key, "consec_fail", 0)
        pipe.hset(key, "last_ok_ist", datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"))
        if latency_ms is not None:
            prev = r.hget(key, "avg_ms")
            ema = latency_ms if prev is None else 0.8 * float(prev) + 0.2 * latency_ms
            pipe.hset(key, "avg_ms", round(ema, 1))
        pipe.execute()
    except Exception:
        pass


def record_failure(provider: str, err: str = "") -> None:
    try:
        r = _r()
        key = f"data_provider:{provider}"
        pipe = r.pipeline()
        pipe.hincrby(key, "fail", 1)
        pipe.hincrby(key, "consec_fail", 1)
        pipe.hset(key, "last_fail_ist", datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"))
        pipe.hset(key, "last_err", (err or "")[:200])
        pipe.execute()
    except Exception:
        pass


def get_health() -> dict:
    """Return per-provider stats for the SystemHealth UI."""
    out = {}
    try:
        r = _r()
        turn = r.get("ltp_turn")
        for p in PROVIDERS:
            h = r.hgetall(f"data_provider:{p}") or {}
            ok, fail = int(h.get("ok", 0)), int(h.get("fail", 0))
            consec = int(h.get("consec_fail", 0))
            total = ok + fail
            out[p] = {
                "ok": ok, "fail": fail, "consec_fail": consec,
                "success_rate": round(ok / total * 100, 1) if total else None,
                "avg_ms": float(h["avg_ms"]) if h.get("avg_ms") else None,
                "last_ok_ist": h.get("last_ok_ist"),
                "last_fail_ist": h.get("last_fail_ist"),
                "last_err": h.get("last_err") or None,
                "status": ("down" if consec >= 5 else
                           "degraded" if consec >= 2 else
                           "healthy" if ok else "idle"),
            }
        out["_next_turn"] = "upstox" if turn == "1" else "kite"
    except Exception as e:
        out["_error"] = str(e)
    return out
