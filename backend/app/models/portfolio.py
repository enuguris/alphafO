"""Portfolio State Model."""
import enum
from datetime import datetime
from sqlalchemy import DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # paper | live
    capital_initial: Mapped[float] = mapped_column(Float, nullable=False)
    capital_current: Mapped[float] = mapped_column(Float, nullable=False)
    capital_deployed: Mapped[float] = mapped_column(Float, default=0.0)
    peak_capital: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0)
    daily_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
