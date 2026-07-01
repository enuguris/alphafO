"""Upstox v3 LTP helper — fetches real-time option prices via Upstox API."""
import calendar
from datetime import date
from typing import Optional

import httpx

UPSTOX_BASE = "https://api.upstox.com"

# Upstox instrument key prefix for NSE F&O
_NFO_PREFIX = "NSE_FO"

# Underlying → Upstox index instrument key (for option chain endpoint)
_INDEX_KEYS = {
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "FINNIFTY":   "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
}


def _last_tuesday(year: int, month: int) -> date:
    """Return the last Tuesday of a given month (NSE monthly expiry from Sep 2025)."""
    last_day = calendar.monthrange(year, month)[1]
    return max(
        date(year, month, d)
        for d in range(1, last_day + 1)
        if date(year, month, d).weekday() == 1  # 1 = Tuesday
    )


def _to_upstox_instrument_key(underlying: str, expiry_iso: str, strike: float, opt_type: str) -> str:
    """
    Build Upstox instrument key for an NSE F&O option.
    Upstox uses Kite-style tradingsymbol (NSE changed all index expiries to Tuesday Sep 2025):
      Monthly (last Tuesday): NIFTY{YY}{MON3}{strike}{type}  e.g. NIFTY26JUL24000PE
      Weekly  (other Tuesday): NIFTY{YY}{M}{DD}{strike}{type} e.g. NIFTY2671424000PE
    Instrument key format: NSE_FO|NIFTY2671424000PE
    """
    exp = date.fromisoformat(expiry_iso)
    yy = str(exp.year)[2:]
    mon3 = exp.strftime("%b").upper()
    last_tue = _last_tuesday(exp.year, exp.month)
    strike_str = str(int(strike))
    if exp == last_tue:
        sym = f"{underlying}{yy}{mon3}{strike_str}{opt_type}"
    else:
        sym = f"{underlying}{yy}{exp.month}{exp.day:02d}{strike_str}{opt_type}"
    return f"{_NFO_PREFIX}|{sym}"


def get_ltp(
    access_token: str,
    underlying: str,
    expiry_iso: str,
    strike: float,
    opt_type: str,
    timeout: float = 4.0,
) -> Optional[float]:
    """
    Fetch live LTP for a single option from Upstox v3 market-quote/ltp endpoint.
    Returns price or None if unavailable.
    """
    instrument_key = _to_upstox_instrument_key(underlying, expiry_iso, strike, opt_type)
    try:
        resp = httpx.get(
            f"{UPSTOX_BASE}/v3/market-quote/ltp",
            params={"instrument_key": instrument_key},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # Response: {"status":"success","data":{"NSE_FO:SYMBOL":{"last_price":...}}}
        payload = data.get("data", {})
        for key, val in payload.items():
            ltp = val.get("last_price") or val.get("ltp")
            if ltp and float(ltp) > 0:
                return float(ltp)
    except Exception:
        pass
    return None


def get_ltp_batch(
    access_token: str,
    requests: list[dict],  # [{"underlying":..,"expiry_iso":..,"strike":..,"opt_type":..,"sym":..}]
    timeout: float = 5.0,
) -> dict[str, float]:
    """
    Fetch LTP for multiple options in one Upstox call.
    Returns {our_symbol: ltp} for each hit.
    """
    if not requests:
        return {}

    key_to_sym: dict[str, str] = {}
    for r in requests:
        ik = _to_upstox_instrument_key(r["underlying"], r["expiry_iso"], r["strike"], r["opt_type"])
        key_to_sym[ik] = r["sym"]

    instrument_keys = ",".join(key_to_sym.keys())
    result: dict[str, float] = {}
    try:
        resp = httpx.get(
            f"{UPSTOX_BASE}/v3/market-quote/ltp",
            params={"instrument_key": instrument_keys},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        for raw_key, val in data.items():
            # raw_key may be "NSE_FO:SYMBOL" (colon) or "NSE_FO|SYMBOL" (pipe)
            normalised = raw_key.replace(":", "|")
            sym = key_to_sym.get(normalised)
            if not sym:
                # Try prefix match
                for ik, s in key_to_sym.items():
                    if ik.split("|")[-1] in raw_key:
                        sym = s
                        break
            ltp = val.get("last_price") or val.get("ltp")
            if sym and ltp and float(ltp) > 0:
                result[sym] = float(ltp)
    except Exception:
        pass
    return result


def get_option_chain_ltp(
    access_token: str,
    underlying: str,
    expiry_iso: str,
    timeout: float = 6.0,
) -> dict[tuple, float]:
    """
    Fetch full option chain from Upstox (strike, opt_type) → ltp.
    Uses /v2/option/chain endpoint.
    """
    index_key = _INDEX_KEYS.get(underlying.upper())
    if not index_key:
        return {}
    result: dict[tuple, float] = {}
    try:
        resp = httpx.get(
            f"{UPSTOX_BASE}/v2/option/chain",
            params={"instrument_key": index_key, "expiry_date": expiry_iso},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        for row in resp.json().get("data", []):
            strike = row.get("strike_price")
            ce = row.get("call_options", {}).get("market_data", {})
            pe = row.get("put_options", {}).get("market_data", {})
            if strike and ce.get("ltp", 0) > 0:
                result[(float(strike), "CE")] = float(ce["ltp"])
            if strike and pe.get("ltp", 0) > 0:
                result[(float(strike), "PE")] = float(pe["ltp"])
    except Exception:
        pass
    return result
