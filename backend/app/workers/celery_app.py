"""Celery application with Beat schedule for continuous scanning."""
from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "alphafO",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    # Beat schedule — runs during NSE market hours (9:15 – 15:30 IST, Mon-Fri)
    beat_schedule={
        # Priority scan every 15 min during market hours
        "scan-priority-15m": {
            "task": "workers.scan_priority_instruments",
            "schedule": crontab(
                minute="*/15",
                hour="9-15",
                day_of_week="1-5",
            ),
            "kwargs": {"timeframes": ["15m", "1h"]},
        },
        # Broader multi-TF scan every hour
        "scan-all-1h": {
            "task": "workers.scan_all_instruments",
            "schedule": crontab(
                minute="5",
                hour="9-15",
                day_of_week="1-5",
            ),
            "kwargs": {"timeframes": ["1h", "4h", "daily"], "task_label": "workers.scan_all_instruments_1h"},
        },
        # End-of-day full scan at 15:35 IST
        "scan-eod": {
            "task": "workers.scan_all_instruments",
            "schedule": crontab(
                minute="35",
                hour="15",
                day_of_week="1-5",
            ),
            "kwargs": {"timeframes": ["daily", "4h"], "task_label": "workers.scan_all_instruments_eod"},
        },
        # Pre-market setup at 9:00 IST
        "scan-premarket": {
            "task": "workers.scan_all_instruments",
            "schedule": crontab(
                minute="0",
                hour="9",
                day_of_week="1-5",
            ),
            "kwargs": {"timeframes": ["daily"], "task_label": "workers.scan_all_instruments_premarket"},
        },
        # MTM repricing every minute during market hours
        "mtm-update": {
            "task": "workers.mtm_update",
            "schedule": crontab(
                minute="*",
                hour="9-15",
                day_of_week="1-5",
            ),
        },
        # EOD intraday square-off at 15:20 IST (before broker auto-square-off at 15:25)
        "eod-close-intraday": {
            "task": "workers.eod_close_intraday",
            "schedule": crontab(minute="20", hour="15", day_of_week="1-5"),
        },
        # Expiry settlement at 15:31 IST (after market close, before 15:35 EOD scan)
        "expiry-settlement": {
            "task": "workers.expiry_settlement",
            "schedule": crontab(
                minute="31",
                hour="15",
                day_of_week="1-5",
            ),
        },
        # Signal expiry check every 15 minutes (expires past valid_until)
        "cleanup-stale-signals": {
            "task": "workers.cleanup_stale_signals",
            "schedule": crontab(minute="*/15"),
        },
        # Market data sync + PCR bootstrap at 16:15 IST (after bhav release)
        "sync-market-data": {
            "task": "workers.sync_market_data",
            "schedule": crontab(minute="15", hour="16", day_of_week="1-5"),
        },
        # Nightly pattern backtest refresh — runs after market close
        "nightly-pattern-backtest": {
            "task": "workers.run_nightly_backtests",
            "schedule": crontab(minute="0", hour="16", day_of_week="1-5"),
        },
        # Nightly auto-discovery — runs 30 min after backtest refresh
        "nightly-pattern-discovery": {
            "task": "workers.run_nightly_discovery",
            "schedule": crontab(minute="30", hour="16", day_of_week="1-5"),
        },
        # Reset daily P&L counter at 9:15 IST every trading day
        "reset-daily-pnl": {
            "task": "workers.reset_daily_pnl",
            "schedule": crontab(minute="15", hour="9", day_of_week="1-5"),
        },
        # Reset weekly P&L every Monday at 9:15 IST
        "reset-weekly-pnl": {
            "task": "workers.reset_weekly_pnl",
            "schedule": crontab(minute="15", hour="9", day_of_week="1"),  # Monday
        },
        # Confirm pending live order fills every 2 minutes during market hours
        "confirm-order-fills": {
            "task": "workers.confirm_order_fills",
            "schedule": crontab(minute="*/2", hour="9-15", day_of_week="1-5"),
        },
        # AI pre-market briefing via Claude Sonnet at 08:45 IST
        "generate-briefing": {
            "task": "workers.generate_briefing",
            "schedule": crontab(minute="45", hour="8", day_of_week="1-5"),
        },
        # Daily lot-size verifier — cross-checks instruments.py vs Kite NFO master
        # Runs at 08:30 IST (before market open, Kite token valid).
        # Logs WARNING if any mismatch found. See docs/NSE_MARKET_CONVENTIONS.md.
        "verify-lot-sizes": {
            "task": "workers.verify_lot_sizes",
            "schedule": crontab(minute="30", hour="8", day_of_week="1-5"),
        },
        # Health scanner — runs every 5 minutes, all day.
        # Checks: deployed-capital drift, stale signals, halt status, signal queue.
        # Auto-fixes: resyncs Redis heat, expires stale signals, clears old halts.
        "health-scan": {
            "task": "workers.health_scan",
            "schedule": crontab(minute="*/5"),
        },
        # Market watch — persists a market/book snapshot every 15 min on
        # trading days so learning survives across assistant sessions.
        # Read via GET /api/v1/system/market-watch (Redis market_watch:YYYY-MM-DD).
        "market-watch": {
            "task": "workers.market_watch_snapshot",
            "schedule": crontab(minute="*/15", hour="9-15", day_of_week="1-5"),
        },
        # Archive today's 30-min option candles at 15:45 IST — expired
        # contracts vanish from every API; this builds our own intraday
        # dataset in market_data/intraday/ for future strategy backtests.
        "collect-option-candles": {
            "task": "workers.collect_option_candles",
            "schedule": crontab(minute="45", hour="15", day_of_week="1-5"),
        },
        # 0DTE expiry-day ATM straddle experiment (1 lot) — Tuesday 09:45 IST.
        # Tested on 90 real expiry days: PF 1.26. Intraday only: SL 40% credit,
        # TP 60%, squared off by eod-close-intraday.
        "zero-dte-straddle": {
            "task": "workers.zero_dte_straddle",
            "schedule": crontab(minute="45", hour="9", day_of_week="2"),
        },
        # Pre-market readiness — 08:50 IST Mon-Fri: broker-token freshness,
        # DB/Redis, beat liveness, integrity, halts, data freshness. Result at
        # GET /api/v1/system/readiness. GO / DEGRADED / NO-GO.
        "premarket-readiness": {
            "task": "workers.premarket_readiness",
            "schedule": crontab(minute="50", hour="8", day_of_week="1-5"),
        },
    },
)
