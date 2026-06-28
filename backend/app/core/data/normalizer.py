"""Normalize market data from any source into a standard DataFrame schema."""
import pandas as pd
from datetime import datetime


REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

def normalize_ohlcv(df: pd.DataFrame, source: str = "unknown") -> pd.DataFrame:
    """
    Ensure DataFrame has standard columns. Adds missing optional columns as NaN.
    """
    df = df.copy()
    # Rename common aliases
    rename_map = {
        "Date": "timestamp", "date": "timestamp", "Datetime": "timestamp",
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Volume": "volume", "OI": "oi", "IV": "iv",
    }
    df.rename(columns=rename_map, inplace=True)

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Missing required column '{col}' from source '{source}'")

    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    for optional in ["oi", "iv"]:
        if optional not in df.columns:
            df[optional] = None

    numeric_cols = ["open", "high", "low", "close", "volume", "oi", "iv"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df
