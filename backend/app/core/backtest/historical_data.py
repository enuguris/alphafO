"""
Real historical OHLCV data for backtesting and pattern discovery.

Priority order:
  1. Kite Connect (real NSE data with OI — best)
  2. Yahoo Finance  (free, ~1yr daily / limited intraday — good enough for discovery)
  3. Synthetic      (last resort — only for manual pattern testing, not discovery)

Yahoo Finance NSE ticker mapping:
  NIFTY      → ^NSEI   (Nifty 50 index)
  BANKNIFTY  → ^NSEBANK
  FINNIFTY   → NIFTY_FIN_SERVICE.NS  (approximate)
  individual stocks → SYMBOL.NS  e.g. RELIANCE.NS
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from loguru import logger


# ── Yahoo Finance ticker map ──────────────────────────────────────────────────

_YF_MAP: dict[str, str] = {
    "NIFTY":       "^NSEI",
    "BANKNIFTY":   "^NSEBANK",
    "FINNIFTY":    "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY":  "NIFTY_MIDCAP_SELECT.NS",
    "SENSEX":      "^BSESN",
    "RELIANCE":    "RELIANCE.NS",
    "TCS":         "TCS.NS",
    "INFY":        "INFY.NS",
    "HDFCBANK":    "HDFCBANK.NS",
    "ICICIBANK":   "ICICIBANK.NS",
    "SBIN":        "SBIN.NS",
    "AXISBANK":    "AXISBANK.NS",
    "KOTAKBANK":   "KOTAKBANK.NS",
    "BAJFINANCE":  "BAJFINANCE.NS",
    "WIPRO":       "WIPRO.NS",
    "LT":          "LT.NS",
    "HINDUNILVR":  "HINDUNILVR.NS",
    "TITAN":       "TITAN.NS",
    "MARUTI":      "MARUTI.NS",
    "BHARTIARTL":  "BHARTIARTL.NS",
}

# Yahoo Finance interval strings per timeframe
_YF_INTERVAL: dict[str, str] = {
    "daily":  "1d",
    "1h":     "1h",
    "4h":     "1h",    # resample to 4h afterwards
    "15m":    "15m",
}

# How many days Yahoo Finance lets you pull for each interval
_YF_MAX_DAYS: dict[str, int] = {
    "15m":   60,    # Yahoo only gives 60 days of 15-min
    "1h":    730,   # ~2 years of hourly
    "4h":    730,
    "daily": 1825,  # 5 years of daily
}


def _yf_ticker(underlying: str) -> str:
    return _YF_MAP.get(underlying.upper(), f"{underlying.upper()}.NS")


def _add_synthetic_oi_iv(df: pd.DataFrame, underlying: str) -> pd.DataFrame:
    """
    Yahoo Finance doesn't have OI or option IV.
    Estimate them from the price series so features have something to work with:
      - OI proxy: rolling 20-day cumulative volume momentum (rising vol → rising OI)
      - IV proxy: 20-day HV annualised × 1.15 (options typically trade above HV)
    These are better than zeros and still let OI/IV features fire.
    """
    # IV proxy
    log_ret = np.log(df["close"] / df["close"].shift(1))
    hv20 = log_ret.rolling(20, min_periods=5).std() * np.sqrt(252) * 100
    df["iv"] = (hv20 * 1.15).fillna(hv20.mean()).clip(8, 80)

    # OI proxy: rolling 5-day change in volume (normalised)
    vol = df["volume"].replace(0, np.nan).ffill()
    vol_ma = vol.rolling(20, min_periods=5).mean()
    df["oi"] = (vol / vol_ma * 1e6).fillna(1e6)   # pseudo-OI in meaningful units

    return df


def fetch_yfinance(
    underlying: str,
    timeframe: str,
    days: int | None = None,
) -> pd.DataFrame | None:
    """
    Fetch OHLCV from Yahoo Finance. Returns a DataFrame with columns:
      timestamp, open, high, low, close, volume, iv, oi
    or None if the fetch fails.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — run: pip install yfinance")
        return None

    ticker_str = _yf_ticker(underlying)
    max_days   = _YF_MAX_DAYS.get(timeframe, 365)
    lookback   = min(days or max_days, max_days)
    interval   = _YF_INTERVAL.get(timeframe, "1d")

    end_dt   = date.today()
    start_dt = end_dt - timedelta(days=lookback)

    try:
        raw = yf.download(
            ticker_str,
            start  = start_dt.strftime("%Y-%m-%d"),
            end    = end_dt.strftime("%Y-%m-%d"),
            interval = interval,
            auto_adjust = True,
            progress = False,
        )
    except Exception as e:
        logger.warning(f"Yahoo Finance download failed for {underlying} ({ticker_str}): {e}")
        return None

    if raw is None or raw.empty or len(raw) < 20:
        logger.warning(f"Yahoo Finance returned empty/short data for {underlying} ({ticker_str})")
        return None

    # Flatten multi-index columns (yfinance sometimes returns them)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)

    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"})

    # Keep only OHLCV
    needed = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[needed].copy()

    # Resample to 4h if needed
    if timeframe == "4h" and interval == "1h":
        df = df.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

    df = df.dropna(subset=["close"])
    if len(df) < 20:
        return None

    # Reset index — index is DatetimeIndex from yfinance
    df.index.name = "timestamp"
    df = df.reset_index()

    # Add synthetic OI/IV
    df = _add_synthetic_oi_iv(df, underlying)

    logger.info(
        f"Yahoo Finance: {underlying} ({ticker_str}) {timeframe} — "
        f"{len(df)} bars ({df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()})"
    )
    return df


async def fetch_historical_best(
    underlying: str,
    timeframe: str,
    days: int | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    Returns (df, data_source) using the best available source:
      1. Kite Connect   → "real"
      2. Yahoo Finance  → "yahoo"
      3. Synthetic      → "synthetic"

    Unlike the engine's _fetch_historical which only knows Kite/synthetic,
    this is used by the miner and DT analyzer to get real price structure.
    """
    # ── 1. Kite ──────────────────────────────────────────────────────────────
    try:
        from app.core.data.kite_adapter import KiteAdapter
        from app.core.scanner import _resolve_nse_token
        from app.core.backtest.engine import _TF_KITE, _TF_DAYS
        from datetime import datetime

        adapter = KiteAdapter()
        if adapter.is_configured():
            token = _resolve_nse_token(underlying)
            if token:
                lookback = days or _TF_DAYS.get(timeframe, 365)
                from_dt  = date.today() - timedelta(days=lookback)
                df = adapter.get_historical(token, from_dt, date.today(), _TF_KITE[timeframe])
                if df is not None and not df.empty and len(df) >= 30:
                    if "oi" not in df.columns:
                        df["oi"] = 0.0
                    if "iv" not in df.columns:
                        df = _add_synthetic_oi_iv(df, underlying)
                    try:
                        from app.core.backtest.market_data import enrich_ohlcv
                        df = await asyncio.get_event_loop().run_in_executor(
                            None, enrich_ohlcv, df, underlying
                        )
                    except Exception as e:
                        logger.debug(f"enrich_ohlcv failed (non-fatal): {e}")
                    logger.info(f"Historical: {underlying}/{timeframe} — Kite ({len(df)} bars)")
                    return df, "real"
    except Exception as e:
        logger.debug(f"Kite fetch failed for {underlying}/{timeframe}: {e}")

    # ── 2. Yahoo Finance ──────────────────────────────────────────────────────
    try:
        df = await asyncio.get_event_loop().run_in_executor(
            None, fetch_yfinance, underlying, timeframe, days
        )
        if df is not None and len(df) >= 30:
            try:
                from app.core.backtest.market_data import enrich_ohlcv
                df = await asyncio.get_event_loop().run_in_executor(
                    None, enrich_ohlcv, df, underlying
                )
            except Exception as e:
                logger.debug(f"enrich_ohlcv failed (non-fatal): {e}")
            return df, "yahoo"
    except Exception as e:
        logger.debug(f"Yahoo Finance failed for {underlying}/{timeframe}: {e}")

    # ── 3. Synthetic fallback ─────────────────────────────────────────────────
    logger.warning(
        f"Historical: {underlying}/{timeframe} — falling back to synthetic "
        f"(Kite not configured, Yahoo failed). Discovery results will be poor."
    )
    from app.core.scanner import synthetic_ohlcv
    df = synthetic_ohlcv(underlying, timeframe)
    return df, "synthetic"
