"""Options chain data service with synthetic fallback."""
import numpy as np
import pandas as pd
from typing import Optional

from app.core.options.greeks import compute_greeks, _bs_price, RISK_FREE_RATE


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
        """Generate a realistic synthetic options chain centred on the live spot price."""
        # Use live ticker snapshot so strikes are always near actual market price
        spot = 0.0
        try:
            from app.core.data.kite_ticker import ticker_service
            snap = ticker_service.get_snapshot()
            spot = float(snap.get(underlying.upper(), {}).get("ltp", 0))
        except Exception:
            pass
        if not spot or spot < 10:
            from app.core.instruments import BASE_PRICES
            spot = BASE_PRICES.get(underlying.upper(), 1500)
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
                ce_ltp = max(0.05, _bs_price(spot, k, T, RISK_FREE_RATE, iv_smile, "CE") * (1 + rng.uniform(-0.02, 0.02)))
                pe_ltp = max(0.05, _bs_price(spot, k, T, RISK_FREE_RATE, iv_smile, "PE") * (1 + rng.uniform(-0.02, 0.02)))
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
        """Fetch live options chain from Kite quote API using ATM±10 strikes."""
        from app.core.options.expiry import available_expiries
        from app.core.data.kite_ticker import ticker_service

        snap = ticker_service.get_snapshot()
        spot = float(snap.get(underlying.upper(), {}).get("ltp", 0))
        if not spot or spot < 10:
            raise ValueError(f"No live spot for {underlying}")

        step = STRIKE_STEPS.get(underlying.upper(), DEFAULT_STEP)
        atm = round(spot / step) * step
        expiries = available_expiries(underlying)
        if not expiries:
            raise ValueError("No expiries available")

        expiry_short = expiries[0]["short"]  # e.g. "02JUL26"
        sym = underlying.upper()

        strikes = [atm + (i - 10) * step for i in range(21)]
        kite_syms = []
        for k in strikes:
            kite_syms.append(f"NFO:{sym}{expiry_short}{int(k)}CE")
            kite_syms.append(f"NFO:{sym}{expiry_short}{int(k)}PE")

        kite = kite_adapter._get_kite()
        quotes = kite.quote(kite_syms)

        rows = []
        for k in strikes:
            ce_key = f"NFO:{sym}{expiry_short}{int(k)}CE"
            pe_key = f"NFO:{sym}{expiry_short}{int(k)}PE"
            ce = quotes.get(ce_key, {})
            pe = quotes.get(pe_key, {})

            ce_iv_raw = ce.get("implied_volatility") or ce.get("iv", 0)
            pe_iv_raw = pe.get("implied_volatility") or pe.get("iv", 0)
            # Kite returns IV as percentage (e.g. 18.5), convert to fraction
            ce_iv = (ce_iv_raw / 100) if ce_iv_raw > 2 else ce_iv_raw
            pe_iv = (pe_iv_raw / 100) if pe_iv_raw > 2 else pe_iv_raw

            try:
                from app.core.options.greeks import compute_greeks, RISK_FREE_RATE
                dte = expiries[0]["dte"]
                T = max(dte, 1) / 365.0
                g_ce = compute_greeks(spot, k, T, ce_iv or 0.18, "CE", RISK_FREE_RATE) if ce_iv else None
                g_pe = compute_greeks(spot, k, T, pe_iv or 0.18, "PE", RISK_FREE_RATE) if pe_iv else None
                ce_delta = round(g_ce.delta, 4) if g_ce else 0.5
                pe_delta = round(g_pe.delta, 4) if g_pe else -0.5
            except Exception:
                ce_delta, pe_delta = 0.5, -0.5

            rows.append({
                "strike":   k,
                "ce_oi":    ce.get("oi", 0) or 0,
                "pe_oi":    pe.get("oi", 0) or 0,
                "ce_iv":    round(ce_iv, 4) if ce_iv else 0.0,
                "pe_iv":    round(pe_iv, 4) if pe_iv else 0.0,
                "ce_ltp":   ce.get("last_price", 0) or 0,
                "pe_ltp":   pe.get("last_price", 0) or 0,
                "ce_delta": ce_delta,
                "pe_delta": pe_delta,
            })

        df = pd.DataFrame(rows)
        if df.empty or df["ce_oi"].sum() == 0:
            raise ValueError("Empty chain from Kite (symbol format mismatch?)")
        return df

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
