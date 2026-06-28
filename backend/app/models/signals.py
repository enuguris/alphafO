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
