"""
System health & operational visibility endpoints.
  GET /system/schedule   — Celery beat schedule + last-run info from Redis
  GET /system/health     — Component health (DB, Redis, Kite, Celery)
  POST /system/run-task  — Manually trigger a background task
"""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()


@router.get("/schedule")
async def get_schedule():
    """
    Return the Celery beat schedule with each task's cron expression,
    human-readable description, and last-run timestamp from Redis.
    """
    from app.workers.celery_app import celery_app
    import redis as _redis
    from app.config import settings

    try:
        r = _redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        redis_ok = True
    except Exception:
        r = None
        redis_ok = False

    schedule = celery_app.conf.beat_schedule or {}

    _descriptions = {
        "scan-priority-15m":      "Scan NIFTY+BANKNIFTY — 15m/1h timeframes",
        "scan-all-1h":            "Full multi-TF scan — 1h/4h/daily",
        "scan-eod":               "End-of-day scan at 15:35",
        "scan-premarket":         "Pre-market daily scan at 09:00",
        "mtm-update":             "Reprice open positions (every minute)",
        "eod-close-intraday":     "Square off intraday trades at 15:20",
        "expiry-settlement":      "Settle expired options at 15:31",
        "cleanup-stale-signals":  "Expire stale signals (every 15 min)",
        "sync-market-data":       "Download bhav/VIX/FII data at 16:15",
        "nightly-pattern-backtest":  "Walk-forward backtest all patterns at 16:00",
        "nightly-pattern-discovery": "Statistical pattern discovery at 16:30",
        "reset-daily-pnl":        "Reset daily P&L counter at 09:15",
        "reset-weekly-pnl":       "Reset weekly P&L every Monday at 09:15",
        "confirm-order-fills":    "Confirm Kite live order fills (every 2 min)",
        "generate-briefing":      "AI pre-market briefing via Claude Sonnet at 08:45",
        "verify-lot-sizes":       "Cross-check lot sizes vs Kite NFO master at 08:30",
        "health-scan":            "Health check: drift, stale signals, halt status (every 5 min)",
    }

    tasks_out = []
    for name, cfg in schedule.items():
        sched = cfg.get("schedule")
        cron_str = ""
        if hasattr(sched, "minute"):
            cron_str = (
                f"min={sched._orig_minute} "
                f"hr={sched._orig_hour} "
                f"dow={sched._orig_day_of_week}"
            )

        # Last-run: written by each task via _stamp_task_run()
        last_run = None
        task_name = cfg.get("task", "")
        # Per-schedule label takes priority (scan-all-1h/eod/premarket all share the same task)
        task_label = cfg.get("kwargs", {}).get("task_label") or task_name
        if r:
            for key_candidate in [f"task_last_run:{task_label}", f"task_last_run:{task_name}"]:
                val = r.get(key_candidate)
                if val:
                    try:
                        last_run = datetime.fromisoformat(val).isoformat()
                    except Exception:
                        last_run = val
                    break

        tasks_out.append({
            "name":        name,
            "task":        task_name,
            "schedule":    cron_str,
            "description": _descriptions.get(name, ""),
            "last_run":    last_run,
        })

    return {
        "as_of":     datetime.utcnow().isoformat(),
        "redis_ok":  redis_ok,
        "tasks":     tasks_out,
        "count":     len(tasks_out),
    }


@router.get("/health")
async def system_health():
    """Check health of all system components."""
    import asyncio
    from app.config import settings

    components: dict[str, dict] = {}

    # DB
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        components["database"] = {"ok": True, "detail": "PostgreSQL connected"}
    except Exception as e:
        components["database"] = {"ok": False, "detail": str(e)[:80]}

    # Redis
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        daily_pnl = float(r.get("daily_pnl") or 0)
        deployed  = float(r.get("daily_deployed") or 0)
        halted    = r.get("TRADING_HALTED") == "1"
        components["redis"] = {
            "ok": True,
            "daily_pnl": round(daily_pnl, 2),
            "deployed":  round(deployed, 2),
            "trading_halted": halted,
        }
    except Exception as e:
        components["redis"] = {"ok": False, "detail": str(e)[:80]}

    # Kite
    kite_ok = bool(settings.kite_api_key and settings.kite_access_token)
    components["kite"] = {
        "ok":             kite_ok,
        "api_key_set":    bool(settings.kite_api_key),
        "token_set":      bool(settings.kite_access_token),
        "detail":         "Connected" if kite_ok else "Credentials missing — using synthetic data",
    }

    # Ticker
    try:
        from app.core.data.kite_ticker import ticker_service
        snap = ticker_service.get_snapshot()
        nifty_ltp = (snap.get("NIFTY") or {}).get("ltp", 0)
        components["ticker"] = {
            "ok":       nifty_ltp > 0,
            "mode":     "live" if kite_ok else "synthetic",
            "nifty_ltp": nifty_ltp,
            "symbols":  len(snap),
        }
    except Exception as e:
        components["ticker"] = {"ok": False, "detail": str(e)[:80]}

    # Celery (check if any worker is alive)
    try:
        from app.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2)
        active = inspect.active()
        celery_alive = active is not None and len(active) > 0
        components["celery"] = {
            "ok":      celery_alive,
            "workers": list(active.keys()) if active else [],
            "detail":  "Workers responding" if celery_alive else "No workers detected (may still be running)",
        }
    except Exception as e:
        components["celery"] = {"ok": False, "detail": str(e)[:80]}

    # Market data cache
    try:
        from pathlib import Path
        import os
        cache_dir = Path(os.environ.get("MARKET_DATA_CACHE", "/app/market_data"))
        bhav_count = len(list((cache_dir / "bhav").glob("*.csv"))) if (cache_dir / "bhav").exists() else 0
        vix_ok = (cache_dir / "india_vix.csv").exists()
        fii_ok = (cache_dir / "fii_fo.csv").exists()
        pcr_nf = (cache_dir / "pcr_NIFTY.csv").exists()
        pcr_bnf = (cache_dir / "pcr_BANKNIFTY.csv").exists()
        components["market_data"] = {
            "ok": bhav_count > 0,
            "bhav_files": bhav_count,
            "vix_cache":  vix_ok,
            "fii_cache":  fii_ok,
            "pcr_nifty":  pcr_nf,
            "pcr_banknifty": pcr_bnf,
        }
    except Exception as e:
        components["market_data"] = {"ok": False, "detail": str(e)[:80]}

    overall = all(v.get("ok", False) for k, v in components.items() if k != "celery")
    return {
        "ok":         overall,
        "as_of":      datetime.utcnow().isoformat(),
        "components": components,
    }


@router.post("/run-task/{task_name}")
async def run_task(task_name: str):
    """Manually trigger a background Celery task by its beat-schedule name."""
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule or {}
    cfg = schedule.get(task_name)
    if not cfg:
        # Also allow direct task name
        task_fn_map = {
            "sync_market_data":          "workers.sync_market_data",
            "run_nightly_backtests":     "workers.run_nightly_backtests",
            "run_nightly_discovery":     "workers.run_nightly_discovery",
            "cleanup_stale_signals":     "workers.cleanup_stale_signals",
            "mtm_update":                "workers.mtm_update",
            "eod_close_intraday":        "workers.eod_close_intraday",
            "expiry_settlement":         "workers.expiry_settlement",
        }
        task_fn = task_fn_map.get(task_name)
        if not task_fn:
            from fastapi import HTTPException
            raise HTTPException(404, f"Task '{task_name}' not found")
    else:
        task_fn = cfg["task"]
        kwargs  = cfg.get("kwargs", {})

    try:
        result = celery_app.send_task(task_fn, kwargs=kwargs if cfg else {})
        return {
            "queued":  True,
            "task":    task_fn,
            "task_id": result.id,
            "message": f"Task '{task_fn}' queued successfully",
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(500, f"Failed to queue task: {e}")


@router.get("/providers")
async def data_provider_health():
    """Round-robin data provider health — success/fail counts, latency, next turn."""
    from app.core.data.provider_health import get_health
    return get_health()


@router.get("/integrity")
async def trade_integrity():
    """
    Latest trade-integrity verification (runs inside health-scan every 5 min).
    Checks P&L structural bounds, charge recomputation, CE/PE price swaps,
    group atomicity, price sanity. Empty violations = every number verified.
    """
    import json
    import redis as _r
    from app.config import settings as _st
    r = _r.from_url(_st.redis_url, decode_responses=True)
    raw = r.get("trade_integrity:last")
    if raw:
        return json.loads(raw)
    # Not cached — run inline
    from app.workers.tasks import _verify_trade_integrity
    violations = await _verify_trade_integrity()
    return {"violations": violations, "checked_at_ist": "inline"}


@router.get("/market-watch")
async def market_watch(day: str | None = None):
    """
    Market/book snapshots recorded every 15 min on trading days (7-day retention).
    day: YYYY-MM-DD, defaults to today (IST).
    """
    import json
    from datetime import datetime, timedelta, timezone
    import redis as _r
    from app.config import settings as _st
    r = _r.from_url(_st.redis_url, decode_responses=True)
    if not day:
        day = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    raw = r.lrange(f"market_watch:{day}", 0, -1)
    return {"day": day, "snapshots": [json.loads(x) for x in raw], "count": len(raw)}


@router.get("/readiness")
async def premarket_readiness_result():
    """Latest pre-market readiness result (runs 08:50 IST Mon-Fri; also on demand)."""
    import json
    import redis as _r
    from app.config import settings as _st
    r = _r.from_url(_st.redis_url, decode_responses=True)
    raw = r.get("premarket_readiness")
    if raw:
        return json.loads(raw)
    from app.workers.tasks import _do_premarket_readiness
    return await _do_premarket_readiness()
