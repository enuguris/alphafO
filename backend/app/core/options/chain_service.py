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

        Priority: Kite (real-time) → NSE via jugaad-data (free, real) → synthetic fallback.
        """
        if kite_adapter is not None:
            try:
                return self._from_kite(underlying, kite_adapter)
            except Exception:
                pass
        try:
            return self._from_nse(underlying)
        except Exception:
            pass
        return self._synthetic_chain(underlying)

    def _get_live_spot(self, underlying: str) -> float:
        """Get live spot price, preferring Redis (cross-process) over in-process ticker."""
        try:
            import redis as _redis_mod
            from app.config import settings as _settings
            _r = _redis_mod.from_url(_settings.redis_url, decode_responses=True)
            val = _r.get(f"spot:{underlying.upper()}")
            if val:
                return float(val)
        except Exception:
            pass
        try:
            from app.core.data.kite_ticker import ticker_service
            snap = ticker_service.get_snapshot()
            ltp = float(snap.get(underlying.upper(), {}).get("ltp", 0))
            if ltp > 10:
                return ltp
        except Exception:
            pass
        from app.core.instruments import BASE_PRICES
        return BASE_PRICES.get(underlying.upper(), 1500)

    def _synthetic_chain(self, underlying: str) -> pd.DataFrame:
        """Generate a realistic synthetic options chain centred on the live spot price."""
        spot = self._get_live_spot(underlying)
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

    def _from_nse(self, underlying: str) -> pd.DataFrame:
        """
        Fetch live option chain from NSE via jugaad-data (free, no API key).
        Uses the nearest weekly expiry. Returns same schema as _from_kite.
        """
        from jugaad_data.nse import NSELive

        NSE_SYMBOLS = {
            "NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY",
            "FINNIFTY": "FINNIFTY", "MIDCPNIFTY": "MIDCPNIFTY",
        }
        nse_sym = NSE_SYMBOLS.get(underlying.upper())
        if not nse_sym:
            raise ValueError(f"No NSE symbol mapping for {underlying}")

        n = NSELive()
        data = n.index_option_chain(nse_sym)
        records = data.get("records", {}).get("data", [])
        if not records:
            raise ValueError("Empty response from NSE")

        # Pick nearest expiry (records include multiple expiries)
        expiry_dates = data.get("records", {}).get("expiryDates", [])
        if not expiry_dates:
            raise ValueError("No expiry dates in NSE response")
        nearest_expiry = expiry_dates[0]  # e.g. "30-Jun-2026"

        spot = self._get_live_spot(underlying)
        step = STRIKE_STEPS.get(underlying.upper(), DEFAULT_STEP)
        atm = round(spot / step) * step

        # Filter to nearest expiry, ATM ± 10 strikes
        strike_window = {atm + (i - 10) * step for i in range(21)}
        rows = []
        for rec in records:
            ce = rec.get("CE", {})
            pe = rec.get("PE", {})
            if not ce and not pe:
                continue
            expiry = (ce or pe).get("expiryDate", "")
            # NSE returns "30-Jun-2026", nearest_expiry is "30-Jun-2026"
            if expiry and expiry.replace("-", " ").lower()[:6] != nearest_expiry.replace("-", " ").lower()[:6]:
                continue
            strike = rec.get("strikePrice") or (ce or pe).get("strikePrice")
            if not strike or strike not in strike_window:
                continue

            ce_iv_raw = ce.get("impliedVolatility", 0) or 0
            pe_iv_raw = pe.get("impliedVolatility", 0) or 0
            # NSE returns IV as % (e.g. 18.5); convert to fraction
            ce_iv = ce_iv_raw / 100 if ce_iv_raw > 2 else ce_iv_raw
            pe_iv = pe_iv_raw / 100 if pe_iv_raw > 2 else pe_iv_raw
            ce_iv = ce_iv if 0.01 < ce_iv < 3 else 0.0
            pe_iv = pe_iv if 0.01 < pe_iv < 3 else 0.0

            # OI from NSE is in lots — convert to contracts (×lot_size) if needed
            # NSE openInterest is already in contracts for index options
            ce_oi = int(ce.get("openInterest", 0) or 0)
            pe_oi = int(pe.get("openInterest", 0) or 0)
            ce_oi_chg = int(ce.get("changeinOpenInterest", 0) or 0)
            pe_oi_chg = int(pe.get("changeinOpenInterest", 0) or 0)

            try:
                from app.core.options.expiry import available_expiries
                expiries = available_expiries(underlying)
                T = max(expiries[0]["dte"], 1) / 365.0 if expiries else 7 / 365.0
                iv_for_greeks = ce_iv or pe_iv or 0.18
                g_ce = compute_greeks(spot, strike, T, ce_iv or iv_for_greeks, "CE", RISK_FREE_RATE)
                g_pe = compute_greeks(spot, strike, T, pe_iv or iv_for_greeks, "PE", RISK_FREE_RATE)
                ce_delta = round(g_ce.delta, 4)
                pe_delta = round(g_pe.delta, 4)
            except Exception:
                ce_delta, pe_delta = 0.5, -0.5

            rows.append({
                "strike":      strike,
                "ce_oi":       ce_oi,
                "pe_oi":       pe_oi,
                "ce_oi_chg":   ce_oi_chg,
                "pe_oi_chg":   pe_oi_chg,
                "ce_iv":       round(ce_iv, 4),
                "pe_iv":       round(pe_iv, 4),
                "ce_ltp":      float(ce.get("lastPrice", 0) or 0),
                "pe_ltp":      float(pe.get("lastPrice", 0) or 0),
                "ce_delta":    ce_delta,
                "pe_delta":    pe_delta,
            })

        if not rows:
            raise ValueError("No rows after filtering NSE chain")

        df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
        return df

    def _from_kite(self, underlying: str, kite_adapter) -> pd.DataFrame:
        """Fetch live options chain from Kite quote API using ATM±10 strikes."""
        from app.core.options.expiry import available_expiries
        from app.core.data.kite_ticker import ticker_service

        spot = self._get_live_spot(underlying)
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
        """
        Return 1-year synthetic IV history spanning a realistic NSE range.

        NIFTY VIX typically oscillates 10–35%; BANKNIFTY slightly higher.
        We generate 252 values normally-distributed around the mid-point with
        explicit anchors at the lo/hi to guarantee the empirical range covers
        a realistic window. This ensures iv_rank is meaningful (0.3–0.7 most
        of the time) rather than always 0 or 1 from a narrow synthetic window.
        """
        rng = np.random.default_rng(abs(hash(underlying + "ivhist")) % (2**31))
        base = {"NIFTY": 15.5, "BANKNIFTY": 17.5}.get(underlying.upper(), 16.0)
        lo = base * 0.65   # ≈ 10% for NIFTY
        hi = base * 2.00   # ≈ 31% for NIFTY
        # Normal distribution centred at mid-point, clipped to [lo, hi]
        mid = (lo + hi) / 2
        sigma = (hi - lo) / 6   # 3-sigma → touches lo/hi
        samples = rng.normal(mid, sigma, 248).clip(lo, hi)
        # Add explicit anchors so min/max always span the full range
        ivs = list(np.round(np.concatenate([[lo, lo * 1.05, hi * 0.95, hi], samples]), 2))
        rng.shuffle(ivs)
        return list(ivs)
