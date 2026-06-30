"""
Feature engineering for automated pattern discovery.

Computes ~25 boolean/numeric features per bar from OHLCV + OI + IV data.
These features feed both the statistical miner and the decision tree analyzer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


# ── Individual indicator helpers ──────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"]
    tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    cum_tpv = (tp * vol).cumsum()
    cum_vol  = vol.cumsum()
    return cum_tpv / cum_vol


def _hv(close: pd.Series, period: int = 20) -> pd.Series:
    """Annualised historical volatility."""
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(period).std() * np.sqrt(252)


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    return upper, mid, lower


def _iv_rank(iv_series: pd.Series, lookback: int = 52) -> pd.Series:
    """IV rank: where is current IV in the past `lookback` bars? 0-100."""
    roll_min = iv_series.rolling(lookback, min_periods=10).min()
    roll_max = iv_series.rolling(lookback, min_periods=10).max()
    rng = (roll_max - roll_min).replace(0, np.nan)
    return ((iv_series - roll_min) / rng * 100).clip(0, 100)


# ── Main feature builder ──────────────────────────────────────────────────────

FEATURE_NAMES = [
    # Momentum
    "ret_1d_pos",          # 1-day return > 0
    "ret_5d_pos",          # 5-day return > 0
    "ret_1d_strong_up",    # 1-day return > +1%
    "ret_1d_strong_dn",    # 1-day return < -1%
    "momentum_aligned",    # 1d and 5d return same sign
    # RSI
    "rsi_oversold",        # RSI < 35
    "rsi_overbought",      # RSI > 65
    "rsi_neutral",         # 40 < RSI < 60
    "rsi_turning_up",      # RSI was < 40 last bar, now > 40
    "rsi_turning_dn",      # RSI was > 60 last bar, now < 60
    # VWAP
    "above_vwap",          # close > VWAP
    "vwap_reclaim",        # close crossed above VWAP this bar
    "vwap_break",          # close crossed below VWAP this bar
    # Bollinger
    "near_bb_upper",       # close within 0.5% of upper band
    "near_bb_lower",       # close within 0.5% of lower band
    "bb_squeeze",          # band width < 20th percentile of last 50 bars
    "bb_expansion",        # band width > 80th percentile of last 50 bars
    # Volume
    "vol_surge",           # volume > 1.5× 20-day avg
    "vol_dry",             # volume < 0.6× 20-day avg
    # Volatility / IV
    "hv_low",              # HV < 15%
    "hv_high",             # HV > 30%
    "iv_rank_low",         # IV rank < 30 (cheap vol → buy)
    "iv_rank_high",        # IV rank > 65 (expensive → sell)
    # Calendar
    "monday",
    "friday",
    "expiry_week",         # within 5 days of monthly expiry (last Thursday)
    # OI (optional — only present if column exists)
    "oi_rising",           # OI change > +2%
    "oi_falling",          # OI change < -2%
    # ATR / range
    "wide_range_bar",      # bar range > 1.5× ATR
    "inside_bar",          # high < prev high and low > prev low
    # ── Options market structure (require enriched columns) ──────────────────
    # India VIX — requires 'vix' column from enrich_ohlcv
    "vix_low",             # India VIX < 13  (cheap vol — buy premium)
    "vix_high",            # India VIX > 18  (expensive vol — sell premium)
    "vix_spike",           # VIX rose > 20% in 1 day (fear spike)
    "vix_crush",           # VIX fell > 12% in 1 day (fear collapse)
    "iv_hv_spread_buy",    # VIX < HV * 0.9  (options cheap vs realised)
    "iv_hv_spread_sell",   # VIX > HV * 1.15 (options expensive vs realised)
    # DTE — requires 'dte' column (always computed by enrich_ohlcv)
    "dte_lt_3",            # ≤ 2 days to Thursday expiry (gamma intensive)
    "dte_3_to_7",          # 3–6 days (normal weekly window)
    "dte_gt_7",            # > 6 days (slow theta, buy premium)
    # FII positioning — requires 'fii_net_idx' column
    "fii_net_long",        # FII net long index futures
    "fii_net_short",       # FII net short index futures
    "fii_adding_longs",    # FII net position increased vs yesterday
    "fii_adding_shorts",   # FII net position decreased vs yesterday
    # PCR / options market structure — requires 'pcr' column
    "pcr_low",             # PCR < 0.75  (market un-hedged, bullish)
    "pcr_high",            # PCR > 1.25  (heavy put hedging, bearish)
    "pcr_rising",          # PCR rose > 10% in 1 day (put buying surge)
    "pcr_falling",         # PCR fell > 10% in 1 day (put unwinding)
    # Max pain — requires 'max_pain' column
    "above_max_pain",      # spot > max_pain * 1.005  (overshoot up)
    "below_max_pain",      # spot < max_pain * 0.995  (overshoot down)
    "near_max_pain",       # spot within 0.3% of max pain (pinned)
]


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with columns [open, high, low, close, volume] and
    optionally [oi, iv], return a new DataFrame of boolean feature columns
    aligned to the same index.

    NaN rows at the head (warm-up) are filled with False.
    """
    feat = pd.DataFrame(index=df.index)

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df.get("volume", pd.Series(1, index=df.index))

    # ── Momentum ──────────────────────────────────────────────────────────────
    ret1 = close.pct_change(1)
    ret5 = close.pct_change(5)
    feat["ret_1d_pos"]       = ret1 > 0
    feat["ret_5d_pos"]       = ret5 > 0
    feat["ret_1d_strong_up"] = ret1 > 0.01
    feat["ret_1d_strong_dn"] = ret1 < -0.01
    feat["momentum_aligned"] = ((ret1 > 0) & (ret5 > 0)) | ((ret1 < 0) & (ret5 < 0))

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi = _rsi(close)
    feat["rsi_oversold"]   = rsi < 35
    feat["rsi_overbought"] = rsi > 65
    feat["rsi_neutral"]    = (rsi >= 40) & (rsi <= 60)
    feat["rsi_turning_up"] = (rsi.shift(1) < 40) & (rsi >= 40)
    feat["rsi_turning_dn"] = (rsi.shift(1) > 60) & (rsi <= 60)

    # ── VWAP ──────────────────────────────────────────────────────────────────
    vwap = _vwap(df)
    feat["above_vwap"]   = close > vwap
    feat["vwap_reclaim"] = (close > vwap) & (close.shift(1) <= vwap.shift(1))
    feat["vwap_break"]   = (close < vwap) & (close.shift(1) >= vwap.shift(1))

    # ── Bollinger ─────────────────────────────────────────────────────────────
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    bb_width = (bb_upper - bb_lower) / bb_mid
    bw_lo = bb_width.rolling(50, min_periods=20).quantile(0.20)
    bw_hi = bb_width.rolling(50, min_periods=20).quantile(0.80)
    feat["near_bb_upper"] = close >= bb_upper * 0.995
    feat["near_bb_lower"] = close <= bb_lower * 1.005
    feat["bb_squeeze"]    = bb_width < bw_lo
    feat["bb_expansion"]  = bb_width > bw_hi

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_avg = volume.rolling(20, min_periods=5).mean()
    feat["vol_surge"] = volume > vol_avg * 1.5
    feat["vol_dry"]   = volume < vol_avg * 0.6

    # ── Historical volatility ─────────────────────────────────────────────────
    hv = _hv(close)
    feat["hv_low"]  = hv < 0.15
    feat["hv_high"] = hv > 0.30

    # ── IV rank ───────────────────────────────────────────────────────────────
    if "iv" in df.columns:
        ivr = _iv_rank(df["iv"])
    else:
        ivr = _iv_rank(hv * 100)   # use HV as IV proxy
    feat["iv_rank_low"]  = ivr < 30
    feat["iv_rank_high"] = ivr > 65

    # ── Calendar ──────────────────────────────────────────────────────────────
    try:
        dow = pd.Series(df.index).dt.dayofweek.values
    except Exception:
        dow = pd.to_datetime(df.index).dayofweek.values
    feat["monday"] = dow == 0
    feat["friday"] = dow == 4

    # expiry week: find last Thursday of each month, flag bars within 5 days
    dates = pd.to_datetime(df.index)
    # last Thursday of each month
    def _is_expiry_week(dt: pd.Timestamp) -> bool:
        month_end = dt.replace(day=28) + pd.offsets.MonthEnd(0)
        last_thu  = month_end - pd.offsets.Week(weekday=3)
        if month_end.weekday() < 3:
            last_thu -= pd.offsets.Week()
        return 0 <= (last_thu - dt).days <= 5
    feat["expiry_week"] = [_is_expiry_week(d) for d in dates]

    # ── OI ────────────────────────────────────────────────────────────────────
    if "oi" in df.columns:
        oi_chg = df["oi"].pct_change(1, fill_method=None)
        feat["oi_rising"]  = oi_chg > 0.02
        feat["oi_falling"] = oi_chg < -0.02
    else:
        feat["oi_rising"]  = False
        feat["oi_falling"] = False

    # ── ATR / range ───────────────────────────────────────────────────────────
    atr = _atr(df)
    bar_range = high - low
    feat["wide_range_bar"] = bar_range > atr * 1.5
    feat["inside_bar"]     = (high < high.shift(1)) & (low > low.shift(1))

    # ── India VIX features ───────────────────────────────────────────────────
    if "vix" in df.columns:
        vix = pd.to_numeric(df["vix"], errors="coerce")
        hv_pct = hv * 100   # already annualised, convert to same % scale as VIX
        vix_chg = vix.pct_change(1)

        feat["vix_low"]           = vix < 13.0
        feat["vix_high"]          = vix > 18.0
        feat["vix_spike"]         = vix_chg > 0.20
        feat["vix_crush"]         = vix_chg < -0.12
        feat["iv_hv_spread_buy"]  = vix < (hv_pct * 0.90)
        feat["iv_hv_spread_sell"] = vix > (hv_pct * 1.15)

    # ── DTE features ─────────────────────────────────────────────────────────
    if "dte" in df.columns:
        dte = pd.to_numeric(df["dte"], errors="coerce")
        feat["dte_lt_3"]   = dte <= 2
        feat["dte_3_to_7"] = (dte >= 3) & (dte <= 6)
        feat["dte_gt_7"]   = dte > 6

    # ── FII positioning ───────────────────────────────────────────────────────
    if "fii_net_idx" in df.columns:
        fii = pd.to_numeric(df["fii_net_idx"], errors="coerce")
        fii_chg = fii.diff(1)
        feat["fii_net_long"]      = fii > 0
        feat["fii_net_short"]     = fii < 0
        feat["fii_adding_longs"]  = fii_chg > 0
        feat["fii_adding_shorts"] = fii_chg < 0

    # ── PCR features ─────────────────────────────────────────────────────────
    if "pcr" in df.columns:
        pcr = pd.to_numeric(df["pcr"], errors="coerce")
        pcr_chg = pcr.pct_change(1)
        feat["pcr_low"]     = pcr < 0.75
        feat["pcr_high"]    = pcr > 1.25
        feat["pcr_rising"]  = pcr_chg > 0.10
        feat["pcr_falling"] = pcr_chg < -0.10

    # ── Max pain features ─────────────────────────────────────────────────────
    if "max_pain" in df.columns:
        mp = pd.to_numeric(df["max_pain"], errors="coerce")
        feat["above_max_pain"] = close > mp * 1.005
        feat["below_max_pain"] = close < mp * 0.995
        feat["near_max_pain"]  = (close >= mp * 0.997) & (close <= mp * 1.003)

    # Cast all to bool, fill NaN → False
    for col in feat.columns:
        feat[col] = feat[col].fillna(False).astype(bool)

    return feat


def compute_forward_return(df: pd.DataFrame, horizon: int = 5) -> pd.Series:
    """
    Compute the N-bar forward log return of close prices.
    Used as the target variable for statistical mining.
    """
    return np.log(df["close"].shift(-horizon) / df["close"])
