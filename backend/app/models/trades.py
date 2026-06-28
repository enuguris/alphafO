"""Trade ORM Model — covers both paper and live trades."""
import enum
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TradeMode(str, enum.Enum):
    PAPER = "paper"
    LIVE = "live"


class TradeStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("signals.id"), nullable=True)
    mode: Mapped[str] = mapped_column(Enum(TradeMode), nullable=False)
    symbol: Mapped[str] = mapped_column(String(100), nullable=False)
    underlying: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY / SELL
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    capital_at_risk_pct: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)  # target_hit / stop_hit / manual / eod
    kite_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # for live trades
    status: Mapped[str] = mapped_column(Enum(TradeStatus), default=TradeStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
