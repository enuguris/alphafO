"""Market regime detector using EMA crossover, ADX, and ATR."""
import math
import pandas as pd
import numpy as np


# Pattern-regime compatibility matrix
REGIME_PATTERNS = {
    ("bullish", None): ["oi_buildup", "vwap_oi", "expiry_week"],
    ("bearish", None): ["oi_buildup", "gap_fill", "pcr_divergence"],
    ("ranging", None): ["mean_reversion", "max_pain", "iv_crush"],
    (None, "high"):    ["iv_crush", "mean_reversion"],
    (None, "low"):     ["gap_fill", "oi_buildup", "expiry_week"],
}


class RegimeDetector:
    """Detect market regime from OHLCV data."""

    def detect(self, ohlcv: pd.DataFrame, india_vix: float = 0.0) -> dict:
        """
        Detect regime from OHLCV.

        Returns dict with:
            trend: "bullish" | "bearish" | "ranging"
            volatility: "high" | "normal" | "low"
            adx: float
            india_vix_proxy: float
            suitable_patterns: list[str]
        """
        df = ohlcv.copy()

        # ── EMAs ─────────────────────────────────────────────────────────────
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

        # ── ADX ──────────────────────────────────────────────────────────────
        adx_val = self._adx(df, period=14)

        # ── Trend classification ──────────────────────────────────────────────
        last = df.iloc[-1]
        if adx_val > 25:
            if last["ema20"] > last["ema50"]:
                trend = "bullish"
            else:
                trend = "bearish"
        else:
            trend = "ranging"

        # ── ATR% vs 30-day average for volatility ────────────────────────────
        atr_series = self._atr_series(df, period=14)
        current_atr_pct = atr_series.iloc[-1] / df["close"].iloc[-1] * 100
        avg_atr_pct = (atr_series / df["close"]).iloc[-30:].mean() * 100

        if current_atr_pct > avg_atr_pct * 1.3:
            volatility = "high"
        elif current_atr_pct < avg_atr_pct * 0.7:
            volatility = "low"
        else:
            volatility = "normal"

        # ── India VIX proxy: annualised 20-day HV ────────────────────────────
        log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        hv20 = log_returns.iloc[-20:].std() * math.sqrt(252) * 100  # as percent

        # ── Suitable patterns ─────────────────────────────────────────────────
        suitable = set()
        key_trend = (trend, None)
        key_vol = (None, volatility)
        suitable.update(REGIME_PATTERNS.get(key_trend, []))
        suitable.update(REGIME_PATTERNS.get(key_vol, []))

        vix_out = round(india_vix, 2) if india_vix > 0 else round(hv20, 2)
        return {
            "trend": trend,
            "volatility": volatility,
            "adx": round(adx_val, 2),
            "india_vix_proxy": vix_out,
            "suitable_patterns": sorted(suitable),
        }

    def _atr_series(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ADX value."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        # When +DM < -DM, set +DM to 0, vice versa
        mask = plus_dm < minus_dm
        plus_dm[mask] = 0
        mask2 = minus_dm <= plus_dm
        minus_dm[mask2] = 0

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1 / period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
        adx = dx.ewm(alpha=1 / period, adjust=False).mean()

        val = adx.iloc[-1]
        return float(val) if not math.isnan(val) else 20.0
