"""Unit tests — instruments config, lot sizes, and market data freshness."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.core.instruments import BASE_PRICES, LOT_SIZES, get_lot_size, TESTING_FOCUS

CACHE = Path("/app/market_data")


def test_testing_focus_is_nifty_banknifty():
    assert set(TESTING_FOCUS) == {"NIFTY", "BANKNIFTY"}


def test_lot_sizes_sebi_compliant():
    # SEBI mandates ≥ ₹15L contract value
    for sym in ("NIFTY", "BANKNIFTY"):
        assert BASE_PRICES[sym] * LOT_SIZES[sym] >= 1_500_000


def test_get_lot_size_returns_positive():
    assert get_lot_size("NIFTY") > 0
    assert get_lot_size("BANKNIFTY") > 0


def test_base_prices_within_20pct_of_bhav_close():
    """BASE_PRICES fallbacks must track reality — stale values corrupt BS pricing."""
    from app.core.backtest.market_data import build_ohlcv_from_bhav
    for sym in ("NIFTY", "BANKNIFTY"):
        # NOTE: build_ohlcv_from_bhav returns None below 20 rows (by design)
        df = build_ohlcv_from_bhav(sym, rows=30)
        assert df is not None and len(df), f"no bhav data for {sym}"
        last_close = float(df["close"].iloc[-1])
        drift = abs(BASE_PRICES[sym] - last_close) / last_close
        assert drift < 0.20, f"{sym} BASE_PRICE {BASE_PRICES[sym]} vs bhav close {last_close}"


def test_bhav_data_is_recent():
    """Bhav cache must extend to within 7 calendar days of today (UDiFF backfill)."""
    from app.core.backtest.market_data import build_ohlcv_from_bhav
    df = build_ohlcv_from_bhav("NIFTY", rows=30)
    assert df is not None
    last = pd.to_datetime(df["timestamp"]).dt.date.max()
    assert (date.today() - last).days <= 7, f"bhav data stale: last={last}"


def test_pcr_cache_is_recent():
    for sym in ("NIFTY", "BANKNIFTY"):
        f = CACHE / f"pcr_{sym}.csv"
        assert f.exists(), f"missing {f}"
        df = pd.read_csv(f)
        last = pd.to_datetime(df["date"]).dt.date.max()
        assert (date.today() - last).days <= 7, f"PCR {sym} stale: last={last}"
        # PCR values must be sane. Post-expiry OI-reset days can genuinely
        # print extremes (0.18 on 2026-04-02, 4.99 on 2018-05-31) — history
        # gets loose bounds; the last 30 rows (what trading reads) strict ones.
        assert df["pcr"].between(0.05, 8.0).all(), f"PCR {sym} has insane values"
        assert df["pcr"].tail(30).between(0.1, 4.0).all(), f"PCR {sym} recent values insane"


def test_vix_cache_recent_and_sane():
    f = CACHE / "india_vix.csv"
    assert f.exists()
    df = pd.read_csv(f)
    last = pd.to_datetime(df["date"]).dt.date.max()
    assert (date.today() - last).days <= 7, f"VIX stale: last={last}"
    assert df["vix"].between(5, 90).all()
