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

    def get_options_chain(self, underlying: str = "NIFTY") -> pd.DataFrame:
        """
        Fetch a simplified options chain for the nearest expiry.
        Returns DataFrame with columns: strike, ce_ltp, pe_ltp, ce_oi, pe_oi, iv
        """
        kite = self._get_kite()
        instruments = pd.DataFrame(kite.instruments("NFO"))

        prefix = "NIFTY" if underlying.upper() == "NIFTY" else underlying.upper()
        opts = instruments[
            (instruments["name"] == prefix) &
            (instruments["instrument_type"].isin(["CE", "PE"]))
        ].copy()

        if opts.empty:
            return pd.DataFrame()

        # Pick nearest expiry
        opts["expiry"] = pd.to_datetime(opts["expiry"])
        nearest_expiry = opts["expiry"].min()
        opts = opts[opts["expiry"] == nearest_expiry]

        # Fetch quotes in batches of 200
        tokens = [f"NFO:{s}" for s in opts["tradingsymbol"].tolist()]
        quotes = {}
        for i in range(0, len(tokens), 200):
            try:
                quotes.update(kite.quote(tokens[i:i + 200]))
            except Exception as e:
                logger.warning(f"Options quote batch failed: {e}")

        rows = []
        for _, row in opts.iterrows():
            sym = f"NFO:{row['tradingsymbol']}"
            q = quotes.get(sym, {})
            rows.append({
                "strike": float(row["strike"]),
                "instrument_type": row["instrument_type"],
                "tradingsymbol": row["tradingsymbol"],
                "ce_ltp": q.get("last_price", 0) if row["instrument_type"] == "CE" else 0,
                "pe_ltp": q.get("last_price", 0) if row["instrument_type"] == "PE" else 0,
                "ce_oi": q.get("oi", 0) if row["instrument_type"] == "CE" else 0,
                "pe_oi": q.get("oi", 0) if row["instrument_type"] == "PE" else 0,
                "iv": q.get("ohlc", {}).get("close", 0),
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # Pivot: one row per strike with both CE and PE
        ce = df[df["instrument_type"] == "CE"][["strike", "ce_ltp", "ce_oi"]].set_index("strike")
        pe = df[df["instrument_type"] == "PE"][["strike", "pe_ltp", "pe_oi"]].set_index("strike")
        chain = ce.join(pe, how="outer").reset_index().fillna(0)
        return chain

    def is_configured(self) -> bool:
        return bool(settings.kite_api_key and settings.kite_access_token)
