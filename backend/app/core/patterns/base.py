"""Abstract base class for all AlphaFO trading patterns."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd


@dataclass
class PatternSignal:
    """Output of a pattern detection run."""
    pattern_name: str
    pattern_version: str
    symbol: str
    underlying: str
    instrument: str          # specific F&O contract e.g. NIFTY24JUN23000CE
    direction: str           # long | short | neutral
    entry_price: float
    target_price: float
    stop_loss: float
    expected_return_pct: float
    confidence_score: float  # 0.0 – 1.0
    explanation: str
    trading_style: str       # intraday | positional
    expiry_date: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    @property
    def risk_reward_ratio(self) -> float:
        reward = abs(self.target_price - self.entry_price)
        risk = abs(self.entry_price - self.stop_loss)
        return reward / risk if risk > 0 else 0.0


class AbstractPattern(ABC):
    """
    Every pattern must subclass this.
    New patterns are auto-discovered by PatternRegistry.
    """
    name: str = "unnamed"
    version: str = "1.0"
    description: str = ""
    min_data_rows: int = 50   # minimum historical rows needed

    @abstractmethod
    def detect(
        self,
        ohlcv: pd.DataFrame,
        options_chain: Optional[pd.DataFrame] = None,
        underlying: str = "",
    ) -> list[PatternSignal]:
        """
        Analyse data and return list of signals (empty if no pattern found).

        Args:
            ohlcv: DataFrame with columns [timestamp, open, high, low, close, volume, oi, iv]
            options_chain: Optional DataFrame with options chain snapshot
            underlying: Name of the underlying (e.g. NIFTY, BANKNIFTY)
        """
        ...

    @abstractmethod
    def why_it_works(self) -> str:
        """Return a plain-English explanation of the market mechanism behind this pattern."""
        ...

    def validate_data(self, ohlcv: pd.DataFrame) -> bool:
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        return required.issubset(set(ohlcv.columns)) and len(ohlcv) >= self.min_data_rows
