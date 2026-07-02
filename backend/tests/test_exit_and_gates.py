"""Unit tests — managed exit arithmetic and entry gates (mirror of live rules)."""
import pytest


def managed_thresholds(net_credit: float):
    """Live rule in tasks.py group exit: TP 50% of credit, SL 2x credit."""
    return net_credit * 0.50, -(net_credit * 2.0)


def credit_gate(net_credit: float, width: float) -> bool:
    """Live rule: real credit must be 20-80% of spread width."""
    return width * 0.20 <= net_credit <= width * 0.80


def test_tp_is_half_the_credit():
    tp, _ = managed_thresholds(3262.0)
    assert tp == pytest.approx(1631.0)


def test_sl_is_twice_the_credit():
    _, sl = managed_thresholds(3262.0)
    assert sl == pytest.approx(-6524.0)


def test_gate_rejects_thin_credit():
    # The trade the live gate correctly rejected on 2026-07-02
    assert credit_gate(5.7, 100.0) is False


def test_gate_rejects_artifact_credit():
    assert credit_gate(95.0, 100.0) is False


def test_gate_accepts_healthy_credit():
    # The Bear Call the system took: credit 50.18 on width 100
    assert credit_gate(50.18, 100.0) is True


def test_max_profit_never_exceeded():
    """Group P&L at TP must be below max profit (= credit)."""
    credit = 50.18 * 65
    tp, _ = managed_thresholds(credit)
    assert tp < credit


def test_slippage_direction():
    """BUY pays more, SELL receives less — mirror of tasks.py entry slippage."""
    prem = 100.0
    slip = max(0.25, prem * 0.005)
    buy_fill = prem + slip
    sell_fill = max(0.05, prem - slip)
    assert buy_fill > prem > sell_fill
