"""Unit tests — Black-Scholes pricing and Greeks."""
import math
import pytest

from app.core.options.greeks import (
    _bs_price, compute_greeks, iv_from_price, RISK_FREE_RATE,
)

S, K, T, IV = 24100.0, 24100.0, 14 / 365.0, 0.15


def test_put_call_parity():
    call = _bs_price(S, K, T, RISK_FREE_RATE, IV, "CE")
    put  = _bs_price(S, K, T, RISK_FREE_RATE, IV, "PE")
    # C - P = S - K*e^(-rT)
    assert call - put == pytest.approx(S - K * math.exp(-RISK_FREE_RATE * T), rel=1e-4)


def test_call_delta_bounds():
    g = compute_greeks(S, K, T, IV, "CE")
    assert 0.0 < g.delta < 1.0
    assert 0.45 < g.delta < 0.60   # ATM call delta near 0.5


def test_put_delta_negative():
    g = compute_greeks(S, K, T, IV, "PE")
    assert -1.0 < g.delta < 0.0


def test_theta_negative_for_long_options():
    for ot in ("CE", "PE"):
        g = compute_greeks(S, K, T, IV, ot)
        assert g.theta < 0, f"{ot} theta should be negative (decay)"


def test_deep_itm_call_near_intrinsic():
    price = _bs_price(S, S - 2000, 1 / 365.0, RISK_FREE_RATE, IV, "CE")
    assert price == pytest.approx(2000, rel=0.02)


def test_otm_option_cheaper_than_atm():
    atm = _bs_price(S, K, T, RISK_FREE_RATE, IV, "CE")
    otm = _bs_price(S, K + 400, T, RISK_FREE_RATE, IV, "CE")
    assert otm < atm


def test_iv_roundtrip():
    price = _bs_price(S, K, T, RISK_FREE_RATE, 0.18, "CE")
    recovered = iv_from_price(price, S, K, T, RISK_FREE_RATE, "CE")
    assert recovered == pytest.approx(0.18, abs=0.005)
