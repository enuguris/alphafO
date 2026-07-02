"""Trade ORM Model — covers both paper and live trades."""
import enum
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TradeMode(str, enum.Enum):
    PAPER = "paper"
    LIVE  = "live"


class TradeStatus(str, enum.Enum):
    PENDING   = "pending"     # limit order placed, awaiting fill confirmation
    OPEN      = "open"
    CLOSED    = "closed"
    CANCELLED = "cancelled"
    EXPIRED   = "expired"     # closed at expiry settlement price


class Trade(Base):
    __tablename__ = "trades"

    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id:  Mapped[int|None] = mapped_column(BigInteger, ForeignKey("signals.id"), nullable=True)
    mode:       Mapped[str]      = mapped_column(Enum(TradeMode), nullable=False)

    # Instrument
    symbol:     Mapped[str]      = mapped_column(String(100), nullable=False)  # e.g. NIFTY16JUL2624850CE
    underlying: Mapped[str]      = mapped_column(String(50),  nullable=False)  # e.g. NIFTY
    option_type: Mapped[str|None]= mapped_column(String(2),   nullable=True)   # CE | PE
    strike:     Mapped[float|None]= mapped_column(Float,      nullable=True)
    lot_size:   Mapped[int|None] = mapped_column(Integer,     nullable=True)
    expiry_date: Mapped[str|None]= mapped_column(String(10),  nullable=True)   # ISO "2026-07-03"
    expiry_display: Mapped[str|None]= mapped_column(String(30), nullable=True) # "03 Jul 2026 (Thu)"
    instrument_token: Mapped[int|None]= mapped_column(BigInteger, nullable=True) # Kite token for MTM

    # Trade direction and sizing
    action:     Mapped[str]      = mapped_column(String(10), nullable=False)   # BUY | SELL
    direction:  Mapped[str|None] = mapped_column(String(10), nullable=True)    # long | short (signal)
    quantity:   Mapped[int]      = mapped_column(Integer,    nullable=False)   # lot_size × lots

    # Prices
    entry_price:   Mapped[float]      = mapped_column(Float, nullable=False)   # premium per unit at entry
    exit_price:    Mapped[float|None] = mapped_column(Float, nullable=True)    # premium per unit at exit
    current_price: Mapped[float|None] = mapped_column(Float, nullable=True)    # last MTM price
    target_price:  Mapped[float|None] = mapped_column(Float, nullable=True, default=0.0)
    stop_loss:     Mapped[float]      = mapped_column(Float, nullable=False)

    # P&L
    gross_pnl:      Mapped[float|None] = mapped_column(Float, nullable=True)   # before charges
    unrealized_pnl: Mapped[float|None] = mapped_column(Float, nullable=True)   # MTM, open trades
    realized_pnl:   Mapped[float|None] = mapped_column(Float, nullable=True)   # after close
    pnl:            Mapped[float|None] = mapped_column(Float, nullable=True)    # net of charges
    pnl_pct:        Mapped[float|None] = mapped_column(Float, nullable=True)   # % of capital at risk

    # Charges breakdown
    charges_total:   Mapped[float|None] = mapped_column(Float, nullable=True)
    charges_brokerage: Mapped[float|None]= mapped_column(Float, nullable=True)
    charges_stt:     Mapped[float|None] = mapped_column(Float, nullable=True)
    charges_txn:     Mapped[float|None] = mapped_column(Float, nullable=True)
    charges_gst:     Mapped[float|None] = mapped_column(Float, nullable=True)
    charges_sebi:    Mapped[float|None] = mapped_column(Float, nullable=True)
    charges_stamp:   Mapped[float|None] = mapped_column(Float, nullable=True)
    # Entry-only charges deducted at time of order
    charges_entry:   Mapped[float|None] = mapped_column(Float, nullable=True)

    # Timing
    entry_time:  Mapped[datetime]      = mapped_column(DateTime, nullable=False)
    exit_time:   Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    last_mtm_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)

    # Status
    status:      Mapped[str]      = mapped_column(Enum(TradeStatus), default=TradeStatus.OPEN)
    exit_reason: Mapped[str|None] = mapped_column(String(100), nullable=True)
    # target_hit | stop_hit | manual | expiry_settlement | eod

    capital_at_risk_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    kite_order_id: Mapped[str|None]    = mapped_column(String(50), nullable=True)
    notes:         Mapped[str|None]    = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]    = mapped_column(DateTime, default=datetime.utcnow)

    # Price fidelity: where entry_price came from — kite | upstox | chain | bs
    # Only kite/upstox are real market fills; chain may be synthetic fallback.
    entry_price_source: Mapped[str|None] = mapped_column(String(20), nullable=True)

    # Composite strategy fields — all legs of the same trade share a trade_group_id
    # leg_role: primary | hedge | short_wing | long_wing | calendar_short | calendar_long
    trade_group_id: Mapped[str|None]  = mapped_column(String(36), nullable=True, index=True)
    leg_role:       Mapped[str|None]  = mapped_column(String(30), nullable=True)
