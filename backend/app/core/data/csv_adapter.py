"""
CSV Adapter — load NSE Bhavcopy and historical CSVs.
Supports NSE F&O Bhavcopy format and generic OHLCV CSVs.
"""
import pandas as pd
from pathlib import Path
from loguru import logger
from app.core.data.normalizer import normalize_ohlcv


class CSVAdapter:
    """Load historical data from NSE Bhavcopy CSV files."""

    def __init__(self, data_dir: str = "./data/nse"):
        self.data_dir = Path(data_dir)

    def load_ohlcv(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Load OHLCV for a symbol from local CSV files."""
        path = self.data_dir / f"{symbol.upper()}.csv"
        if not path.exists():
            logger.warning(f"No CSV found for {symbol} at {path}")
            return pd.DataFrame()

        df = pd.read_csv(path)
        df = normalize_ohlcv(df, source=f"csv:{symbol}")

        if start_date:
            df = df[df["timestamp"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["timestamp"] <= pd.to_datetime(end_date)]

        logger.info(f"Loaded {len(df)} rows for {symbol} from CSV")
        return df

    def load_options_chain(self, underlying: str, expiry_date: str) -> pd.DataFrame:
        """Load options chain snapshot from CSV."""
        path = self.data_dir / "options_chain" / f"{underlying}_{expiry_date}.csv"
        if not path.exists():
            logger.warning(f"No options chain CSV: {path}")
            return pd.DataFrame()
        df = pd.read_csv(path)
        return df

    def download_nse_bhavcopy(self, date_str: str) -> bool:
        """
        Download NSE F&O Bhavcopy for a given date (DDMMYYYY format).
        Saves to data_dir/bhavcopy/
        """
        import urllib.request
        import zipfile
        date = pd.to_datetime(date_str)
        fname = f"fo{date.strftime('%d%b%Y').upper()}bhav.csv.zip"
        url = f"https://www.nseindia.com/content/historical/DERIVATIVES/{date.year}/{date.strftime('%b').upper()}/{fname}"
        out_dir = self.data_dir / "bhavcopy"
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / fname
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                zip_path.write_bytes(response.read())
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(out_dir)
            logger.info(f"Downloaded bhavcopy for {date_str}")
            return True
        except Exception as e:
            logger.error(f"Failed to download bhavcopy for {date_str}: {e}")
            return False
