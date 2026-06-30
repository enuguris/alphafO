"""
CompositePattern — a dynamically-constructed pattern built from a list of
feature conditions discovered by the statistical miner or decision tree.

It implements the same AbstractPattern interface as manual patterns so the
scanner can fire it without any special-casing.
"""
from __future__ import annotations

import pandas as pd

from app.core.backtest.features import compute_features


class CompositePattern:
    """
    A pattern defined by N boolean feature conditions that must all be True.

    Attributes
    ----------
    name        : unique slug, e.g. "auto_NIFTY_daily_rsi_oversold__vwap_reclaim"
    features    : list of feature names from features.FEATURE_NAMES
    direction   : "long" or "short"
    option_type : "CE" or "PE"
    source      : "statistical" or "decision_tree"
    explanation : human-readable description
    underlying  : the instrument this was discovered for (or None for universal)
    timeframe   : the timeframe this was discovered on
    """

    def __init__(
        self,
        features:    list[str],
        direction:   str,
        option_type: str,
        explanation: str,
        source:      str,
        underlying:  str  = "",
        timeframe:   str  = "daily",
        win_rate:    float = 0.0,
        effect_size: float = 0.0,
        p_value:     float = 0.0,
        n_samples:   int   = 0,
    ):
        self.features    = features
        self.direction   = direction
        self.option_type = option_type
        self.explanation = explanation
        self.source      = source
        self.underlying  = underlying
        self.timeframe   = timeframe
        self.win_rate    = win_rate
        self.effect_size = effect_size
        self.p_value     = p_value
        self.n_samples   = n_samples
        # Slug name for registry / DB lookup
        feat_slug  = "__".join(features[:3])   # cap at 3 for readability
        self.name  = f"auto_{underlying}_{timeframe}_{feat_slug}".lower().replace(" ", "_")

    # ── AbstractPattern interface ─────────────────────────────────────────────

    def detect(self, df: pd.DataFrame) -> dict | None:
        """
        Run on the latest bar of df.
        Returns a signal dict if all conditions are met, else None.
        """
        if df is None or len(df) < 30:
            return None

        try:
            feat_df = compute_features(df)
        except Exception:
            return None

        if feat_df.empty:
            return None

        last = feat_df.iloc[-1]

        for feat in self.features:
            if feat not in last.index:
                return None
            if not bool(last[feat]):
                return None

        # All conditions satisfied
        close = float(df["close"].iloc[-1])
        confidence = min(0.95, 0.60 + self.effect_size * 0.5 + (self.win_rate - 0.52) * 1.5)

        return {
            "pattern_name":   self.name,
            "direction":      self.direction,
            "option_type":    self.option_type,
            "confidence":     round(confidence, 3),
            "explanation":    self.explanation,
            "underlying":     self.underlying,
            "timeframe":      self.timeframe,
            "source":         self.source,
            "features_fired": self.features,
            "win_rate_hist":  self.win_rate,
            "effect_size":    self.effect_size,
        }


def generate_display_name(features: list[str], direction: str, underlying: str) -> str:
    """
    Generate a human-readable pattern name from feature list.
    Priority order: options structure (VIX/FII/PCR/DTE) → price action (RSI/VWAP/BB) → context (vol/OI/calendar).
    Returns e.g. "NIFTY VIX Crush + Oversold CE" or "BANKNIFTY FII Long + BB Squeeze CE"
    """
    feat_set = set(features)
    opt = "CE" if direction == "long" else "PE"

    # Map each individual feature to a short label (one-to-one for tiebreaking)
    _LABEL: dict[str, str] = {
        # Options market structure
        "vix_crush":          "VIX Crush",
        "vix_spike":          "VIX Fear Spike",
        "vix_low":            "Low VIX",
        "vix_high":           "High VIX",
        "iv_hv_spread_buy":   "IV Cheap",
        "iv_hv_spread_sell":  "IV Rich",
        "fii_net_long":       "FII Long",
        "fii_net_short":      "FII Short",
        "fii_adding_longs":   "FII Building Longs",
        "fii_adding_shorts":  "FII Building Shorts",
        "pcr_high":           "Put Heavy",
        "pcr_low":            "Un-hedged",
        "pcr_rising":         "PCR Surge",
        "pcr_falling":        "PCR Unwind",
        "above_max_pain":     "Above Max Pain",
        "below_max_pain":     "Below Max Pain",
        "near_max_pain":      "Max Pain Pin",
        "dte_lt_3":           "Gamma Day",
        "dte_3_to_7":         "Weekly Window",
        "dte_gt_7":           "Long DTE",
        # Price action
        "rsi_oversold":       "Oversold",
        "rsi_overbought":     "Overbought",
        "rsi_neutral":        "RSI Neutral",
        "rsi_turning_up":     "RSI Turning Up",
        "rsi_turning_dn":     "RSI Turning Down",
        "vwap_reclaim":       "VWAP Reclaim",
        "vwap_break":         "VWAP Break",
        "above_vwap":         "Above VWAP",
        "bb_squeeze":         "BB Squeeze",
        "bb_expansion":       "BB Breakout",
        "near_bb_upper":      "Near Upper Band",
        "near_bb_lower":      "Near Lower Band",
        "vol_surge":          "Volume Surge",
        "vol_dry":            "Low Volume",
        "ret_1d_strong_up":   "Strong Up",
        "ret_1d_strong_dn":   "Strong Down",
        "ret_1d_pos":         "Up Day",
        "ret_5d_pos":         "5-Day Up",
        "momentum_aligned":   "Aligned Momentum",
        "oi_rising":          "OI Buildup",
        "oi_falling":         "OI Unwind",
        "wide_range_bar":     "Wide Range",
        "inside_bar":         "Inside Bar",
        "expiry_week":        "Expiry Week",
        "monday":             "Monday",
        "friday":             "Friday",
        "hv_low":             "Low HV",
        "hv_high":            "High HV",
        "iv_rank_low":        "IV Rank Low",
        "iv_rank_high":       "IV Rank High",
    }

    # Collect labels for all features in priority order (options first, then price)
    _PRIORITY = [
        "vix_crush", "vix_spike", "vix_low", "vix_high",
        "iv_hv_spread_buy", "iv_hv_spread_sell",
        "fii_net_long", "fii_net_short", "fii_adding_longs", "fii_adding_shorts",
        "pcr_high", "pcr_low", "pcr_rising", "pcr_falling",
        "above_max_pain", "below_max_pain", "near_max_pain",
        "dte_lt_3", "dte_3_to_7",
        "rsi_oversold", "rsi_overbought", "rsi_turning_up", "rsi_turning_dn",
        "vwap_reclaim", "vwap_break", "above_vwap",
        "bb_squeeze", "bb_expansion", "near_bb_upper", "near_bb_lower",
        "vol_surge", "vol_dry",
        "ret_1d_strong_up", "ret_1d_strong_dn", "momentum_aligned",
        "oi_rising", "oi_falling",
        "wide_range_bar", "inside_bar", "expiry_week", "monday", "friday",
        "hv_low", "hv_high", "iv_rank_low", "iv_rank_high",
        "ret_1d_pos", "ret_5d_pos", "rsi_neutral", "dte_gt_7",
    ]

    themes: list[str] = []
    for feat in _PRIORITY:
        if feat in feat_set:
            label = _LABEL.get(feat, feat.replace("_", " ").title())
            if label not in themes:
                themes.append(label)
        if len(themes) == 3:
            break

    # Fallback: use raw feature name for any feature not covered
    if not themes:
        for feat in features[:3]:
            label = _LABEL.get(feat, feat.replace("_", " ").title())
            if label not in themes:
                themes.append(label)

    name = " + ".join(themes)
    return f"{underlying.upper()} {name} {opt}"


def composite_from_rule(rule) -> CompositePattern:
    """Build a CompositePattern from a DiscoveredRule dataclass."""
    return CompositePattern(
        features    = rule.features,
        direction   = rule.direction,
        option_type = rule.option_type,
        explanation = rule.explanation,
        source      = rule.source,
        underlying  = rule.underlying,
        timeframe   = rule.timeframe,
        win_rate    = rule.win_rate,
        effect_size = rule.effect_size,
        p_value     = rule.p_value,
        n_samples   = rule.n_samples,
    )
