"""
Zerodha Kite Connect Adapter.
Requires KITE_API_KEY and KITE_ACCESS_TOKEN in environment.
"""
import pandas as pd
from datetime import datetime, date
from loguru import logger
from app.config import settings
from app.core.data.normalizer import normalize_ohlcv


class KiteAdapter:
    """Wrapper around kiteconnect for data fetching."""

    def __init__(self):
        self._kite = None

    def _get_kite(self):
        if self._kite is None:
            if not settings.kite_api_key:
                raise ValueError("Kite API key not configured. Add KITE_API_KEY to .env")
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=settings.kite_api_key)
            if settings.kite_access_token:
                self._kite.set_access_token(settings.kite_access_token)
        return self._kite

    def get_historical(self, instrument_token: int, from_date: date, to_date: date,
                       interval: str = "day") -> pd.DataFrame:
        kite = self._get_kite()
        data = kite.historical_data(instrument_token, from_date, to_date, interval)
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df.rename(columns={"date": "timestamp"}, inplace=True)
        return normalize_ohlcv(df, source="kite")

    def get_instruments(self, exchange: str = "NFO") -> pd.DataFrame:
        kite = self._get_kite()
        instruments = kite.instruments(exchange)
        return pd.DataFrame(instruments)

    def get_quote(self, instruments: list[str]) -> dict:
        kite = self._get_kite()
        return kite.quote(instruments)

    def is_configured(self) -> bool:
        return bool(settings.kite_api_key and settings.kite_access_token)
