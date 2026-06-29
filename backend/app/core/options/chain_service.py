"""Options chain data service with synthetic fallback."""
import numpy as np
import pandas as pd
from typing import Optional

from app.core.options.greeks import compute_greeks, RISK_FREE_RATE


STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
}
DEFAULT_STEP = 50


class ChainService:
    """Fetch or generate options chain data."""

    def get_chain(self, underlying: str, kite_adapter=None) -> pd.DataFrame:
        """
        Get options chain DataFrame.
        Columns: strike, ce_oi, pe_oi, ce_iv, pe_iv, ce_ltp, pe_ltp, ce_delta, pe_delta

        Falls back to synthetic data if kite not available.
        """
        if kite_adapter is not None:
            try:
                return self._from_kite(underlying, kite_adapter)
            except Exception:
                pass
        return self._synthetic_chain(underlying)

    def _synthetic_chain(self, underlying: str) -> pd.DataFrame:
        """Generate a realistic synthetic options chain for testing."""
        base_spots = {
            "NIFTY": 24300, "BANKNIFTY": 52700, "FINNIFTY": 23400,
            "MIDCPNIFTY": 12640, "HDFCBANK": 1840, "ICICIBANK": 1375,
        }
        spot = base_spots.get(underlying.upper(), 1500)
        step = STRIKE_STEPS.get(underlying.upper(), DEFAULT_STEP)

        rng = np.random.default_rng(abs(hash(underlying)) % (2**31))

        # Create strikes from spot-500 to spot+500
        n_steps = 500 // step
        atm = round(spot / step) * step
        strikes = [atm + (i - n_steps) * step for i in range(2 * n_steps + 1)]

        rows = []
        T = 7 / 365  # 1 week to expiry
        base_iv = 0.18

        for k in strikes:
            moneyness = (k - spot) / spot
            # IV smile: higher for OTM
            iv_smile = base_iv + 0.05 * moneyness ** 2 + rng.uniform(-0.01, 0.01)
            iv_smile = max(0.05, iv_smile)

            # OI: peaks at ATM for CE, slightly below ATM for PE
            ce_oi_peak = spot - step * 0  # ATM
            pe_oi_peak = spot - step * 1  # slightly below ATM

            ce_oi = max(0, int(500000 * np.exp(-0.5 * ((k - ce_oi_peak) / (5 * step)) ** 2) + rng.integers(0, 50000)))
            pe_oi = max(0, int(600000 * np.exp(-0.5 * ((k - pe_oi_peak) / (5 * step)) ** 2) + rng.integers(0, 50000)))

            try:
                g_ce = compute_greeks(spot, k, T, iv_smile, "CE", RISK_FREE_RATE)
                g_pe = compute_greeks(spot, k, T, iv_smile, "PE", RISK_FREE_RATE)
                ce_ltp = max(0.05, g_ce.iv * spot * 0.1 * (1 + rng.uniform(-0.05, 0.05)))
                pe_ltp = max(0.05, g_pe.iv * spot * 0.1 * (1 + rng.uniform(-0.05, 0.05)))
                ce_delta = round(g_ce.delta, 4)
                pe_delta = round(g_pe.delta, 4)
            except Exception:
                ce_ltp = pe_ltp = 1.0
                ce_delta = 0.5
                pe_delta = -0.5

            rows.append({
                "strike": k,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "ce_iv": round(iv_smile, 4),
                "pe_iv": round(iv_smile, 4),
                "ce_ltp": round(ce_ltp, 2),
                "pe_ltp": round(pe_ltp, 2),
                "ce_delta": ce_delta,
                "pe_delta": pe_delta,
            })

        return pd.DataFrame(rows)

    def _from_kite(self, underlying: str, kite_adapter) -> pd.DataFrame:
        """Fetch live chain from Kite (stub — real implementation would call NSE API)."""
        raise NotImplementedError("Live chain fetching not yet implemented")

    def get_iv_history(self, underlying: str) -> list:
        """Return 30 days of synthetic IV history (12-28%)."""
        rng = np.random.default_rng(abs(hash(underlying + "iv")) % (2**31))
        # Generate IV with some autocorrelation for realism
        ivs = []
        iv = 18.0
        for _ in range(30):
            iv = iv + rng.uniform(-1.5, 1.5)
            iv = max(12.0, min(28.0, iv))
            ivs.append(round(iv, 2))
        return ivs
