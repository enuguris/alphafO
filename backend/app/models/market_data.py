"""Market Data ORM Models."""
import enum
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Enum, Float, Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class InstrumentType(str, enum.Enum):
    FUTURES = "FUT"
    CALL = "CE"
    PUT = "PE"
    EQUITY = "EQ"


class MarketData(Base):
    """OHLCV + OI + IV data for F&O instruments."""
    __tablename__ = "market_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), default="NFO")
    instrument_type: Mapped[str] = mapped_column(Enum(InstrumentType), nullable=False)
    expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)  # CE / PE
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interval: Mapped[str] = mapped_column(String(10), default="day")  # day, 5minute, etc.
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    oi: Mapped[int] = mapped_column(BigInteger, default=0)     # Open Interest
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)  # Implied Volatility

    __table_args__ = (
        Index("ix_market_data_symbol_ts", "symbol", "timestamp"),
        Index("ix_market_data_symbol_expiry", "symbol", "expiry"),
    )


class OptionsChain(Base):
    """Snapshot of full options chain (for PCR, max pain calculations)."""
    __tablename__ = "options_chain"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    underlying: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    strike: Mapped[float] = mapped_column(Float, nullable=False)
    ce_oi: Mapped[int] = mapped_column(BigInteger, default=0)
    pe_oi: Mapped[int] = mapped_column(BigInteger, default=0)
    ce_iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    ce_ltp: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_ltp: Mapped[float | None] = mapped_column(Float, nullable=True)
    pcr: Mapped[float | None] = mapped_column(Float, nullable=True)  # PE OI / CE OI

    __table_args__ = (
        Index("ix_options_chain_underlying_expiry", "underlying", "expiry", "snapshot_time"),
    )
