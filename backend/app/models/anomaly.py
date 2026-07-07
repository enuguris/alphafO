"""Anomaly journal — permanent record of every issue the system detects.

Unlike Redis-based health state (TTL'd, vanishes), rows here are forever:
health-scan auto-fixes, integrity violations, provider disagreements, signal
churn spikes. Reviewed in the EOD digest so recurring problems become visible
instead of being silently re-fixed every 5 minutes.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source: Mapped[str] = mapped_column(String(40), index=True)   # health_scan | integrity | data_check | signal_churn | readiness
    kind: Mapped[str] = mapped_column(String(60), index=True)     # e.g. capital_drift, ce_pe_swap, spot_vs_bhav_gap
    severity: Mapped[str] = mapped_column(String(10), default="warn")  # info | warn | critical
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    auto_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
