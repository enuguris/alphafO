"""DB model for auto-discovered patterns (statistical + decision-tree)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import String, Float, Integer, Text, JSON, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DiscoverySource(str, enum.Enum):
    STATISTICAL   = "statistical"
    DECISION_TREE = "decision_tree"


class DiscoveredPattern(Base):
    __tablename__ = "discovered_patterns"

    id:           Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at:   Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:   Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Identity
    underlying:   Mapped[str]          = mapped_column(String(32), nullable=False)
    timeframe:    Mapped[str]          = mapped_column(String(10), nullable=False)
    pattern_slug: Mapped[str]          = mapped_column(String(200), nullable=False)  # unique name

    # Rule definition (stored as JSON list of feature names)
    features:     Mapped[list]         = mapped_column(JSON, nullable=False)
    direction:    Mapped[str]          = mapped_column(String(8), nullable=False)    # long / short
    option_type:  Mapped[str]          = mapped_column(String(2), nullable=False)    # CE / PE

    # Stats
    n_samples:    Mapped[int]          = mapped_column(Integer, default=0)
    win_rate:     Mapped[float]        = mapped_column(Float, default=0.0)
    mean_fwd_ret: Mapped[float]        = mapped_column(Float, default=0.0)
    p_value:      Mapped[float | None] = mapped_column(Float, nullable=True)
    effect_size:  Mapped[float]        = mapped_column(Float, default=0.0)

    # Metadata
    source:       Mapped[str]          = mapped_column(String(20), nullable=False)
    explanation:  Mapped[str]          = mapped_column(Text, nullable=False)
    active:       Mapped[bool]         = mapped_column(default=True)    # can be toggled off by user

    # Last backtest result (run same engine as manual patterns)
    last_backtest_win_rate:     Mapped[float | None] = mapped_column(Float, nullable=True)
    last_backtest_profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_backtest_trades:       Mapped[int | None]   = mapped_column(Integer, nullable=True)
    last_backtest_net_pnl:      Mapped[float | None] = mapped_column(Float, nullable=True)
    last_backtest_at:           Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    has_edge:     Mapped[bool]         = mapped_column(default=False)
