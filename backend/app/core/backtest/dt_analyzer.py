"""
Decision-tree analyzer.

Trains a DecisionTreeClassifier on the existing PatternTrade history
to discover which market features at entry time predict winners vs losers.

The tree's leaf nodes become discovered rules:
  - leaf win_rate ≥ 55% AND sample count ≥ 10 → "long" rule
  - leaf win_rate ≤ 45% AND sample count ≥ 10 → the *inverse* conditions → "short" rule

The rules are expressed in terms of FEATURE_NAMES so they can be used
identically to statistically-mined rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from app.core.backtest.features import compute_features, FEATURE_NAMES
from app.core.backtest.miner import DiscoveredRule, _explain


# ── Config ────────────────────────────────────────────────────────────────────

MIN_LEAF_SAMPLES = 10
MIN_LEAF_WIN_RATE = 0.55
MAX_DEPTH = 4


def _fetch_df_for_dates(
    underlying: str,
    timeframe: str,
    dates: list[str],
) -> pd.DataFrame | None:
    """
    Fetch OHLCV for the given dates synchronously (uses Yahoo Finance if Kite unavailable).
    Returns a DataFrame indexed by date string, or None if not enough data.
    """
    import asyncio
    from app.core.backtest.historical_data import fetch_historical_best

    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an async context — use run_in_executor
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(asyncio.run, fetch_historical_best(underlying, timeframe))
                    df, _ = fut.result(timeout=60)
            else:
                df, _ = loop.run_until_complete(fetch_historical_best(underlying, timeframe))
        except RuntimeError:
            df, _ = asyncio.run(fetch_historical_best(underlying, timeframe))

        if df is None or df.empty:
            return None

        # Normalise index to date string "YYYY-MM-DD" for lookup
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")
        return df
    except Exception as e:
        logger.warning(f"DT analyzer: could not fetch data for {underlying}/{timeframe}: {e}")
        return None


async def run_dt_analysis(
    trades: list[dict],
    underlying: str,
    timeframe: str,
) -> list[DiscoveredRule]:
    """
    Given a list of trade dicts (from PatternTrade records), train a decision
    tree and extract high-confidence leaf rules.

    Each trade dict must have: signal_date, net_pnl (or pnl_pct), direction.
    """
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.tree import _tree as sk_tree

    if len(trades) < MIN_LEAF_SAMPLES * 2:
        logger.info(f"DT analyzer: not enough trades for {underlying}/{timeframe} ({len(trades)})")
        return []

    # Build date → feature lookup
    dates = [t["signal_date"] for t in trades if t.get("signal_date")]
    if not dates:
        return []

    df = _fetch_df_for_dates(underlying, timeframe, dates)
    if df is None:
        return []

    feat_df = compute_features(df)

    # Only use features present in this DataFrame (enriched features like VIX/DTE
    # are only available if the underlying DataFrame was enriched)
    available_features = [f for f in FEATURE_NAMES if f in feat_df.columns]

    # Build X, y
    rows_X, rows_y = [], []
    for t in trades:
        date_key = t.get("signal_date", "")[:10]
        if date_key not in feat_df.index:
            continue
        row = feat_df.loc[date_key][available_features].values.astype(float)
        label = 1 if (t.get("net_pnl") or t.get("pnl_pct") or 0) > 0 else 0
        rows_X.append(row)
        rows_y.append(label)

    if len(rows_X) < MIN_LEAF_SAMPLES * 2:
        return []

    X = np.array(rows_X)
    y = np.array(rows_y)

    clf = DecisionTreeClassifier(
        max_depth          = MAX_DEPTH,
        min_samples_leaf   = MIN_LEAF_SAMPLES,
        class_weight       = "balanced",
        random_state       = 42,
    )
    clf.fit(X, y)

    rules = _extract_leaf_rules(clf, available_features, underlying, timeframe, len(trades))
    logger.info(f"DT analyzer: {underlying}/{timeframe} — {len(rules)} leaf rules from {len(trades)} trades")
    return rules


def _extract_leaf_rules(
    clf,
    feature_names: list[str],
    underlying: str,
    timeframe: str,
    total_trades: int,
) -> list[DiscoveredRule]:
    """Walk the tree and extract high-confidence leaf nodes as rules."""
    from sklearn.tree import _tree as sk_tree

    tree_   = clf.tree_
    rules   = []

    def _recurse(node: int, conditions: list[dict]):
        is_leaf = tree_.children_left[node] == sk_tree.TREE_LEAF

        if is_leaf:
            n_samples  = int(tree_.n_node_samples[node])
            value      = tree_.value[node][0]
            n_pos      = value[1] if len(value) > 1 else 0
            win_rate   = float(n_pos / n_samples) if n_samples > 0 else 0

            if n_samples < MIN_LEAF_SAMPLES:
                return

            # Extract feature names from conditions (each condition is bool feature)
            feature_conds = [c for c in conditions if c["threshold"] >= 0.5]
            features = [c["feature"] for c in feature_conds]

            if not features:
                return

            if win_rate >= MIN_LEAF_WIN_RATE:
                direction = "long"
                rules.append(DiscoveredRule(
                    features    = features,
                    direction   = direction,
                    underlying  = underlying,
                    timeframe   = timeframe,
                    n_samples   = n_samples,
                    win_rate    = round(win_rate, 4),
                    mean_fwd_ret= round(win_rate - 0.5, 4),   # proxy
                    p_value     = 0.0,   # not applicable for DT leaves
                    effect_size = round(win_rate - 0.5, 4),
                    option_type = "CE",
                    explanation = _explain(features, direction),
                    source      = "decision_tree",
                    extra       = {"tree_node": node, "total_trades": total_trades},
                ))
            elif win_rate <= (1 - MIN_LEAF_WIN_RATE):
                # Inverted: these conditions predict a loss → the inverse is a short signal
                direction = "short"
                rules.append(DiscoveredRule(
                    features    = features,
                    direction   = direction,
                    underlying  = underlying,
                    timeframe   = timeframe,
                    n_samples   = n_samples,
                    win_rate    = round(1 - win_rate, 4),
                    mean_fwd_ret= round(0.5 - win_rate, 4),
                    p_value     = 0.0,
                    effect_size = round(0.5 - win_rate, 4),
                    option_type = "PE",
                    explanation = _explain(features, direction),
                    source      = "decision_tree",
                    extra       = {"tree_node": node, "total_trades": total_trades},
                ))
            return

        feat_idx  = tree_.feature[node]
        threshold = tree_.threshold[node]
        feat_name = feature_names[feat_idx] if feat_idx < len(feature_names) else f"f{feat_idx}"

        # Left child: feature <= threshold (for bool features: False path)
        _recurse(tree_.children_left[node],  conditions + [{"feature": feat_name, "threshold": threshold, "lte": True}])
        # Right child: feature > threshold (for bool features: True path)
        _recurse(tree_.children_right[node], conditions + [{"feature": feat_name, "threshold": threshold, "lte": False}])

    _recurse(0, [])
    return rules
