"""Background task definitions."""
from app.workers.celery_app import celery_app


@celery_app.task(name="workers.run_signal_scan")
def run_signal_scan(underlying: str = "NIFTY"):
    """Trigger a pattern scan for the given underlying."""
    return {"status": "ok", "underlying": underlying}


@celery_app.task(name="workers.sync_market_data")
def sync_market_data(underlying: str = "NIFTY"):
    """Sync latest market data from the configured adapter."""
    return {"status": "ok", "underlying": underlying}
