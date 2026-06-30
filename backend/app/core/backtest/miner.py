"""
Statistical pattern miner.

For each underlying, fetches 1yr of OHLCV, computes features, then exhaustively
tests 1-way, 2-way, and 3-way feature combinations to find which ones produce
statistically significant positive forward returns.

Edge criteria (same as manual patterns):
  - ≥ 20 matching bars (min sample size)
  - p-value < 0.05 (Mann-Whitney U vs complement)
  - Mean forward return > 0 for long signals, < 0 for short signals
  - Win rate (bars where forward return > 0) ≥ 52%

Returns a list of DiscoveredRule dicts, each becoming a CompositePattern.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats

from app.core.backtest.features import compute_features, compute_forward_return, FEATURE_NAMES


# ── Config ────────────────────────────────────────────────────────────────────

MIN_SAMPLES    = 20       # minimum bars matching this feature combo
P_THRESHOLD    = 0.05     # Mann-Whitney U significance
MIN_WIN_RATE   = 0.52     # fraction of matching bars with positive forward return
FORWARD_BARS   = 5        # bars to look ahead
MAX_COMBO_SIZE = 3        # max feature combination depth (1, 2, or 3)

# Features not allowed together (to avoid logical contradictions)
_MUTEX = [
    {"rsi_oversold", "rsi_overbought"},
    {"rsi_oversold", "rsi_neutral"},
    {"rsi_overbought", "rsi_neutral"},
    {"above_vwap", "vwap_break"},
    {"ret_1d_strong_up", "ret_1d_strong_dn"},
    {"oi_rising", "oi_falling"},
    {"hv_low", "hv_high"},
    {"iv_rank_low", "iv_rank_high"},
    {"monday", "friday"},
    {"bb_squeeze", "bb_expansion"},
    {"vol_surge", "vol_dry"},
    # Options market structure
    {"vix_low", "vix_high"},
    {"vix_spike", "vix_crush"},
    {"iv_hv_spread_buy", "iv_hv_spread_sell"},
    {"dte_lt_3", "dte_3_to_7"},
    {"dte_lt_3", "dte_gt_7"},
    {"dte_3_to_7", "dte_gt_7"},
    {"fii_net_long", "fii_net_short"},
    {"fii_adding_longs", "fii_adding_shorts"},
    {"pcr_low", "pcr_high"},
    {"pcr_rising", "pcr_falling"},
    {"above_max_pain", "below_max_pain"},
    {"above_max_pain", "near_max_pain"},
    {"below_max_pain", "near_max_pain"},
]


@dataclass
class DiscoveredRule:
    features:     list[str]         # feature names that must all be True
    direction:    str               # "long" or "short"
    underlying:   str
    timeframe:    str
    n_samples:    int
    win_rate:     float
    mean_fwd_ret: float
    p_value:      float
    effect_size:  float             # rank-biserial correlation
    option_type:  str               # CE for long, PE for short
    explanation:  str
    source:       str = "statistical"
    extra:        dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "features":     self.features,
            "direction":    self.direction,
            "underlying":   self.underlying,
            "timeframe":    self.timeframe,
            "n_samples":    self.n_samples,
            "win_rate":     self.win_rate,
            "mean_fwd_ret": self.mean_fwd_ret,
            "p_value":      self.p_value,
            "effect_size":  self.effect_size,
            "option_type":  self.option_type,
            "explanation":  self.explanation,
            "source":       self.source,
        }


def _is_mutex(combo: tuple[str, ...]) -> bool:
    combo_set = set(combo)
    return any(mx.issubset(combo_set) for mx in _MUTEX)


def _effect_size(group: np.ndarray, rest: np.ndarray) -> float:
    """Rank-biserial correlation as effect size for Mann-Whitney U."""
    n1, n2 = len(group), len(rest)
    if n1 == 0 or n2 == 0:
        return 0.0
    u, _ = stats.mannwhitneyu(group, rest, alternative="two-sided")
    return float(2 * u / (n1 * n2) - 1)


def _explain(features: list[str], direction: str) -> str:
    """Human-readable rule explanation."""
    label_map = {
        "ret_1d_pos":       "price closed up today",
        "ret_5d_pos":       "5-day trend is up",
        "ret_1d_strong_up": "strong up day (>1%)",
        "ret_1d_strong_dn": "strong down day (<-1%)",
        "momentum_aligned": "short and medium momentum aligned",
        "rsi_oversold":     "RSI oversold (<35)",
        "rsi_overbought":   "RSI overbought (>65)",
        "rsi_neutral":      "RSI neutral (40–60)",
        "rsi_turning_up":   "RSI recovering from oversold",
        "rsi_turning_dn":   "RSI rolling over from overbought",
        "above_vwap":       "price above VWAP",
        "vwap_reclaim":     "price just reclaimed VWAP",
        "vwap_break":       "price just broke below VWAP",
        "near_bb_upper":    "near Bollinger upper band",
        "near_bb_lower":    "near Bollinger lower band",
        "bb_squeeze":       "Bollinger squeeze (low volatility)",
        "bb_expansion":     "Bollinger expansion (volatility breakout)",
        "vol_surge":        "volume surge (>1.5× avg)",
        "vol_dry":          "low volume day",
        "hv_low":           "historical volatility low (<15%)",
        "hv_high":          "historical volatility high (>30%)",
        "iv_rank_low":      "IV rank low (<30) — cheap options",
        "iv_rank_high":     "IV rank high (>65) — expensive options",
        "monday":           "Monday",
        "friday":           "Friday",
        "expiry_week":      "expiry week (5 days before expiry)",
        "oi_rising":        "OI rising (fresh positions)",
        "oi_falling":       "OI falling (unwinding)",
        "wide_range_bar":   "wide range candle (>1.5× ATR)",
        "inside_bar":       "inside bar (compression)",
        # Options market structure
        "vix_low":           "India VIX low (<13) — cheap options",
        "vix_high":          "India VIX high (>18) — expensive options",
        "vix_spike":         "VIX spiked >20% (fear event)",
        "vix_crush":         "VIX crushed >12% (fear gone)",
        "iv_hv_spread_buy":  "IV cheaper than realised vol (options mispriced low)",
        "iv_hv_spread_sell": "IV richer than realised vol (options mispriced high)",
        "dte_lt_3":          "≤2 days to expiry (gamma intensive)",
        "dte_3_to_7":        "3–6 days to expiry (weekly window)",
        "dte_gt_7":          ">6 days to expiry (time premium rich)",
        "fii_net_long":      "FII net long index futures",
        "fii_net_short":     "FII net short index futures",
        "fii_adding_longs":  "FII building long positions",
        "fii_adding_shorts": "FII building short positions",
        "pcr_low":           "PCR low (<0.75) — market un-hedged",
        "pcr_high":          "PCR high (>1.25) — heavy put hedging",
        "pcr_rising":        "PCR surging (put buying acceleration)",
        "pcr_falling":       "PCR falling (put hedges unwinding)",
        "above_max_pain":    "spot above max pain (overshoot up)",
        "below_max_pain":    "spot below max pain (overshoot down)",
        "near_max_pain":     "spot pinned near max pain strike",
    }
    parts = [label_map.get(f, f) for f in features]
    signal = "BUY CE" if direction == "long" else "BUY PE"
    return f"{signal} when: {' + '.join(parts)}"


def mine_statistical_patterns(
    df: pd.DataFrame,
    underlying: str,
    timeframe: str,
    max_combo: int = MAX_COMBO_SIZE,
) -> list[DiscoveredRule]:
    """
    Given a bar DataFrame, return all statistically significant feature combos.
    """
    if len(df) < 60:
        return []

    feat_df  = compute_features(df)
    fwd_ret  = compute_forward_return(df, horizon=FORWARD_BARS)

    # Drop last FORWARD_BARS rows (no forward return available)
    valid    = fwd_ret.dropna().index
    feat_df  = feat_df.loc[valid]
    fwd_arr  = fwd_ret.loc[valid].values

    # Only test features with meaningful variance (>5% True rate)
    active_features = [
        f for f in FEATURE_NAMES
        if f in feat_df.columns and feat_df[f].mean() > 0.05
    ]

    rules: list[DiscoveredRule] = []
    tested = 0

    for size in range(1, max_combo + 1):
        for combo in itertools.combinations(active_features, size):
            if _is_mutex(combo):
                continue
            tested += 1

            # Build mask: all features in combo must be True
            mask = np.ones(len(feat_df), dtype=bool)
            for f in combo:
                mask &= feat_df[f].values

            n = mask.sum()
            if n < MIN_SAMPLES:
                continue

            group = fwd_arr[mask]
            rest  = fwd_arr[~mask]

            mean_ret = float(np.mean(group))
            if abs(mean_ret) < 0.002:   # effect too small
                continue

            direction = "long" if mean_ret > 0 else "short"
            win_rate  = float(np.mean(group > 0) if direction == "long" else np.mean(group < 0))

            if win_rate < MIN_WIN_RATE:
                continue

            # Significance test
            if len(rest) < 5:
                continue
            _, p = stats.mannwhitneyu(group, rest, alternative="two-sided")
            if p >= P_THRESHOLD:
                continue

            eff = _effect_size(group, rest)
            rules.append(DiscoveredRule(
                features    = list(combo),
                direction   = direction,
                underlying  = underlying,
                timeframe   = timeframe,
                n_samples   = int(n),
                win_rate    = round(win_rate, 4),
                mean_fwd_ret= round(mean_ret, 6),
                p_value     = round(float(p), 6),
                effect_size = round(eff, 4),
                option_type = "CE" if direction == "long" else "PE",
                explanation = _explain(list(combo), direction),
            ))

    logger.info(
        f"Statistical miner: {underlying}/{timeframe} — "
        f"tested {tested} combos, found {len(rules)} rules"
    )

    # Deduplicate: if a 3-way combo is a superset of a 2-way with similar stats, drop it
    rules = _deduplicate(rules)

    # Sort by effect size descending
    rules.sort(key=lambda r: (r.effect_size, r.win_rate), reverse=True)
    return rules[:30]   # cap at top 30 per instrument/timeframe


def _deduplicate(rules: list[DiscoveredRule]) -> list[DiscoveredRule]:
    """Remove rules that are strict supersets of a shorter rule with same direction."""
    kept = []
    for r in rules:
        is_superset = False
        for other in rules:
            if other is r:
                continue
            if (other.direction == r.direction and
                    len(other.features) < len(r.features) and
                    set(other.features).issubset(set(r.features)) and
                    abs(other.win_rate - r.win_rate) < 0.03):
                is_superset = True
                break
        if not is_superset:
            kept.append(r)
    return kept
