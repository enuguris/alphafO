"""Backtest Run Model."""
from datetime import datetime
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pattern_names: Mapped[str] = mapped_column(String(500), nullable=False)  # comma-separated
    underlying: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    final_capital: Mapped[float] = mapped_column(Float, nullable=False)
    total_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_profit_pct: Mapped[float] = mapped_column(Float, nullable=True)
    avg_loss_pct: Mapped[float] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=True)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # full JSON report
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
