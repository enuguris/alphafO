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
            "kwargs": {"timeframes": ["1h", "4h", "daily"]},
        },
        # End-of-day full scan at 15:35 IST
        "scan-eod": {
            "task": "workers.scan_all_instruments",
            "schedule": crontab(
                minute="35",
                hour="15",
                day_of_week="1-5",
            ),
            "kwargs": {"timeframes": ["daily", "4h"]},
        },
        # Pre-market setup at 9:00 IST
        "scan-premarket": {
            "task": "workers.scan_all_instruments",
            "schedule": crontab(
                minute="0",
                hour="9",
                day_of_week="1-5",
            ),
            "kwargs": {"timeframes": ["daily"]},
        },
    },
)
