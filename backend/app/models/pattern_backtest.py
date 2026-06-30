"""Pattern backtest ORM models."""
import enum
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class BacktestStatus(str, enum.Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    FAILED   = "failed"


class PatternBacktest(Base):
    """One row per (underlying × pattern × timeframe) backtest run."""
    __tablename__ = "pattern_backtests"

    id:            Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    underlying:    Mapped[str]  = mapped_column(String(50),  nullable=False)
    pattern_name:  Mapped[str]  = mapped_column(String(100), nullable=False)
    timeframe:     Mapped[str]  = mapped_column(String(10),  nullable=False)  # 15m/1h/4h/daily

    date_from:     Mapped[str]  = mapped_column(String(10),  nullable=False)  # ISO date
    date_to:       Mapped[str]  = mapped_column(String(10),  nullable=False)

    # Counts
    bars_tested:    Mapped[int]  = mapped_column(Integer, default=0)
    total_signals:  Mapped[int]  = mapped_column(Integer, default=0)
    trades_taken:   Mapped[int]  = mapped_column(Integer, default=0)
    winning_trades: Mapped[int]  = mapped_column(Integer, default=0)
    losing_trades:  Mapped[int]  = mapped_column(Integer, default=0)

    # Performance metrics
    win_rate:       Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor:  Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_winner:     Mapped[float | None] = mapped_column(Float, nullable=True)   # ₹
    avg_loser:      Mapped[float | None] = mapped_column(Float, nullable=True)   # ₹ (negative)
    total_net_pnl:  Mapped[float | None] = mapped_column(Float, nullable=True)   # ₹
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True) # %
    sharpe_ratio:   Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_holding_bars: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Meta
    status:        Mapped[str]  = mapped_column(Enum(BacktestStatus), default=BacktestStatus.PENDING)
    data_source:   Mapped[str]  = mapped_column(String(20), default="synthetic")  # real | synthetic
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes:         Mapped[str | None] = mapped_column(Text, nullable=True)


class PatternTrade(Base):
    """One row per simulated trade within a backtest run."""
    __tablename__ = "pattern_trades"

    id:           Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_id:  Mapped[int]  = mapped_column(BigInteger, ForeignKey("pattern_backtests.id"), nullable=False)

    underlying:   Mapped[str]  = mapped_column(String(50))
    pattern_name: Mapped[str]  = mapped_column(String(100))
    timeframe:    Mapped[str]  = mapped_column(String(10))
    signal_date:  Mapped[str]  = mapped_column(String(10))  # ISO date of bar where signal fired
    direction:    Mapped[str]  = mapped_column(String(10))  # long | short
    option_type:  Mapped[str | None] = mapped_column(String(2), nullable=True)   # CE | PE
    strike:       Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry_dte:   Mapped[int | None]   = mapped_column(Integer, nullable=True)
    spot_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)

    entry_price:  Mapped[float] = mapped_column(Float, nullable=False)  # BS-simulated premium
    exit_price:   Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason:  Mapped[str | None]   = mapped_column(String(30), nullable=True)  # target/stop/expiry
    holding_bars: Mapped[int | None]   = mapped_column(Integer, nullable=True)

    gross_pnl:    Mapped[float | None] = mapped_column(Float, nullable=True)
    charges:      Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl:      Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct:      Mapped[float | None] = mapped_column(Float, nullable=True)  # % of premium
    iv_at_entry:  Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence:   Mapped[float | None] = mapped_column(Float, nullable=True)
