"""IV Rank and IV Percentile service."""
from typing import List


class IVRankService:
    """Compute IV Rank, IV Percentile, and strategy bias."""

    @staticmethod
    def iv_rank(current_iv: float, historical_ivs: List[float]) -> float:
        """
        IV Rank: where current IV sits between min and max of historical IVs.
        Returns 0.0 to 1.0.
        """
        if not historical_ivs or len(historical_ivs) < 2:
            return 0.5
        lo = min(historical_ivs)
        hi = max(historical_ivs)
        if hi == lo:
            return 0.5
        return max(0.0, min(1.0, (current_iv - lo) / (hi - lo)))

    @staticmethod
    def iv_percentile(current_iv: float, historical_ivs: List[float]) -> float:
        """
        IV Percentile: fraction of historical days where IV was below current IV.
        Returns 0.0 to 1.0.
        """
        if not historical_ivs:
            return 0.5
        below = sum(1 for iv in historical_ivs if iv < current_iv)
        return below / len(historical_ivs)

    @staticmethod
    def iv_regime(iv_rank: float) -> str:
        """Classify IV regime."""
        if iv_rank > 0.7:
            return "high"
        if iv_rank < 0.3:
            return "low"
        return "normal"

    @staticmethod
    def strategy_bias(iv_rank: float) -> str:
        """Suggest trading strategy based on IV rank."""
        if iv_rank > 0.7:
            return "sell_premium"
        if iv_rank < 0.3:
            return "buy_options"
        return "spreads"
