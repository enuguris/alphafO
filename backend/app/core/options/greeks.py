"""Black-Scholes Greeks calculator for NSE F&O."""
import math
from dataclasses import dataclass
from scipy.stats import norm


RISK_FREE_RATE = 0.065  # Indian risk-free rate


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float   # per 1% move in IV
    rho: float
    iv: float     # implied volatility (annualised, as fraction e.g. 0.18 = 18%)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float):
    """Compute d1 and d2 for Black-Scholes."""
    if T <= 0 or sigma <= 0:
        raise ValueError("T and sigma must be positive")
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes option price."""
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if option_type.upper() in ("CE", "C", "CALL"):
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Option delta."""
    if T <= 0:
        # At expiry
        if option_type.upper() in ("CE", "C", "CALL"):
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma)
    if option_type.upper() in ("CE", "C", "CALL"):
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1.0


def gamma(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> float:
    """Option gamma (same for CE and PE)."""
    if T <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma)
    return norm.pdf(d1) / (S * sigma * math.sqrt(T))


def theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Option theta (per calendar day, not annualised)."""
    if T <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    term1 = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type.upper() in ("CE", "C", "CALL"):
        t = term1 - r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        t = term1 + r * K * math.exp(-r * T) * norm.cdf(-d2)
    return t / 365.0  # per calendar day


def vega(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> float:
    """Option vega (per 1% change in IV)."""
    if T <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma)
    return S * norm.pdf(d1) * math.sqrt(T) / 100.0


def rho(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Option rho (per 1% change in rate)."""
    if T <= 0:
        return 0.0
    _, d2 = _d1_d2(S, K, T, r, sigma)
    if option_type.upper() in ("CE", "C", "CALL"):
        return K * T * math.exp(-r * T) * norm.cdf(d2) / 100.0
    else:
        return -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100.0


def iv_from_price(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> float:
    """Implied volatility via Newton-Raphson. Returns annualised IV as a fraction."""
    if T <= 0 or market_price <= 0:
        return 0.0

    # Initial guess using Brenner-Subrahmanyam approximation
    sigma = math.sqrt(2 * math.pi / T) * market_price / S

    for _ in range(max_iter):
        try:
            price = _bs_price(S, K, T, r, sigma, option_type)
            vega_val = S * norm.pdf(_d1_d2(S, K, T, r, sigma)[0]) * math.sqrt(T)
            if abs(vega_val) < 1e-10:
                break
            diff = price - market_price
            if abs(diff) < tol:
                break
            sigma = sigma - diff / vega_val
            if sigma <= 0:
                sigma = 0.001
        except Exception:
            break

    return max(0.0, sigma)


def compute_greeks(
    S: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str,
    r: float = RISK_FREE_RATE,
) -> Greeks:
    """Compute all Greeks for an option."""
    return Greeks(
        delta=delta(S, K, T, r, sigma, option_type),
        gamma=gamma(S, K, T, r, sigma, option_type),
        theta=theta(S, K, T, r, sigma, option_type),
        vega=vega(S, K, T, r, sigma, option_type),
        rho=rho(S, K, T, r, sigma, option_type),
        iv=sigma,
    )
