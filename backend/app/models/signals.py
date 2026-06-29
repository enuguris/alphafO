"""Signal ORM Model."""
import enum
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base



class SignalDirection(str, enum.Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class SignalStatus(str, enum.Enum):
    ACTIVE = "active"
    EXECUTED = "executed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pattern_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pattern_version: Mapped[str] = mapped_column(String(20), default="1.0")
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    underlying: Mapped[str] = mapped_column(String(50), nullable=False)
    instrument: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. NIFTY24JUN23000CE
    direction: Mapped[str] = mapped_column(Enum(SignalDirection), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    expected_return_pct: Mapped[float] = mapped_column(Float, nullable=False)  # e.g. 3.5
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)     # 0.0 – 1.0
    explanation: Mapped[str] = mapped_column(Text, nullable=False)             # why this trade
    trading_style: Mapped[str] = mapped_column(String(20), default="intraday") # intraday | positional
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(Enum(SignalStatus), default=SignalStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Options-specific
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)         # CE | PE
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry_date_str: Mapped[str | None] = mapped_column(String(20), nullable=True)    # "03JUL26" (NSE symbol)
    expiry_date_iso: Mapped[str | None] = mapped_column(String(10), nullable=True)    # "2026-07-03"
    expiry_display: Mapped[str | None] = mapped_column(String(30), nullable=True)     # "03 Jul 2026 (Thu)"
    expiry_dte: Mapped[int | None] = mapped_column(Integer, nullable=True)            # days to expiry
    expiry_series: Mapped[str | None] = mapped_column(String(10), nullable=True)      # "weekly" | "monthly"
    option_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)    # buy | sell | spread
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Greeks at signal time
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv_at_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv_rank: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Regime
    regime_trend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    regime_volatility: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Cost
    estimated_premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Scan context
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 15m | 1h | 4h | daily
