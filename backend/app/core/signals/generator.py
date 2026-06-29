"""
Signal Generator — orchestrates all patterns and returns ranked signals.
"""
import pandas as pd
from datetime import datetime
from loguru import logger
from app.core.patterns.registry import PatternRegistry
from app.core.patterns.base import PatternSignal
from app.core.risk.manager import RiskManager


class SignalGenerator:
    """Runs all registered patterns and returns valid, risk-filtered signals."""

    def __init__(self, risk_manager: RiskManager | None = None):
        self.registry = PatternRegistry.get()
        self.risk = risk_manager or RiskManager()

    def run(
        self,
        ohlcv: pd.DataFrame,
        options_chain: pd.DataFrame | None = None,
        underlying: str = "",
        pattern_filter: list[str] | None = None,
        context: dict | None = None,
    ) -> list[PatternSignal]:
        """
        Run all (or filtered) patterns and return valid signals sorted by confidence.

        Args:
            context: optional dict with keys like "iv_rank" and "regime" that patterns
                     can use to adjust confidence scores.
        """
        context = context or {}
        patterns = self.registry.all()
        if pattern_filter:
            patterns = [p for p in patterns if p.name in pattern_filter]

        all_signals: list[PatternSignal] = []
        for pattern in patterns:
            try:
                signals = pattern.detect(ohlcv, options_chain=options_chain, underlying=underlying, context=context)
                for s in signals:
                    if self._is_valid(s):
                        all_signals.append(s)
            except Exception as e:
                logger.error(f"Pattern {pattern.name} failed: {e}")

        # Sort by confidence descending
        all_signals.sort(key=lambda s: s.confidence_score, reverse=True)
        logger.info(f"Generated {len(all_signals)} valid signals for {underlying}")
        return all_signals

    def _is_valid(self, signal: PatternSignal) -> bool:
        """Basic sanity checks on a signal before accepting it."""
        if signal.entry_price <= 0 or signal.stop_loss <= 0 or signal.target_price <= 0:
            return False
        if signal.risk_reward_ratio < 1.5:
            return False
        if signal.confidence_score < 0.5:
            return False
        return True
