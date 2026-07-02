"""Unit tests — NSE F&O charges calculator."""
import pytest

from app.core.charges import calculate_charges


def test_buy_roundtrip_components():
    c = calculate_charges(entry_premium=100.0, exit_premium=120.0, quantity=65, action="BUY")
    assert c.total > 0
    # STT 0.1% applies on sell side only — for a BUY open, the exit is the sell
    assert c.stt == pytest.approx(120.0 * 65 * 0.001, rel=1e-6)
    # Stamp duty applies on buy side only — the entry
    assert c.stamp_duty == pytest.approx(100.0 * 65 * 0.00003, rel=1e-6)
    assert c.gst == pytest.approx((c.brokerage + c.exchange_txn) * 0.18, rel=1e-2)


def test_sell_roundtrip_stt_on_entry():
    c = calculate_charges(entry_premium=100.0, exit_premium=50.0, quantity=65, action="SELL")
    # SELL open: entry is the sell side → STT on entry premium
    assert c.stt == pytest.approx(100.0 * 65 * 0.001, rel=1e-6)


def test_total_is_sum_of_components():
    c = calculate_charges(entry_premium=200.0, exit_premium=180.0, quantity=30, action="SELL")
    assert c.total == pytest.approx(
        c.brokerage + c.stt + c.exchange_txn + c.gst + c.sebi + c.stamp_duty, abs=0.05)


def test_charges_scale_with_quantity():
    small = calculate_charges(100.0, 100.0, 30, "BUY")
    big   = calculate_charges(100.0, 100.0, 300, "BUY")
    assert big.total > small.total


def test_zero_premium_no_crash():
    c = calculate_charges(0.0, 0.0, 65, "BUY")
    assert c.total >= 0
