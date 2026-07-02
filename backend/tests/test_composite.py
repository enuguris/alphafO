"""Unit tests — composite strategy builder (live trading structures)."""
import pytest

from app.core.strategies.composite import (
    build_composite, net_credit, net_debit, max_loss, strategy_name, _build_symbol,
)

EXPIRIES = [
    {"date": "2026-07-14", "display": "14 Jul 2026 (Tue)", "dte": 12, "series": "weekly", "short": "26714"},
    {"date": "2026-07-28", "display": "28 Jul 2026 (Tue)", "dte": 26, "series": "monthly", "short": "26JUL"},
]


def _build(direction, pattern="max_pain", ivr=0.3):
    return build_composite(
        underlying="NIFTY", spot=24100.0, direction=direction,
        iv_rank=ivr, iv=0.15, pattern_name=pattern,
        available_expiries=EXPIRIES, step=50,
    )


def test_bull_put_structure():
    legs = _build("long")
    assert len(legs) == 2
    assert strategy_name(legs) == "Bull Put Spread"
    sell = next(l for l in legs if l.action == "SELL")
    buy  = next(l for l in legs if l.action == "BUY")
    assert sell.option_type == buy.option_type == "PE"
    assert buy.strike < sell.strike          # wing is below the short put
    assert net_credit(legs) > 0              # always net credit


def test_bear_call_structure():
    legs = _build("short")
    sell = next(l for l in legs if l.action == "SELL")
    buy  = next(l for l in legs if l.action == "BUY")
    assert sell.option_type == buy.option_type == "CE"
    assert buy.strike > sell.strike          # wing is above the short call
    assert net_credit(legs) > 0


def test_same_expiry_both_legs():
    legs = _build("long")
    assert legs[0].expiry_iso == legs[1].expiry_iso


def test_iron_condor_for_sell_patterns():
    legs = _build("short", pattern="iv_crush", ivr=0.7)
    assert len(legs) == 4
    assert strategy_name(legs) == "Iron Condor"
    sells = [l for l in legs if l.action == "SELL"]
    buys  = [l for l in legs if l.action == "BUY"]
    assert len(sells) == 2 and len(buys) == 2
    assert net_credit(legs) > 0


def test_max_loss_positive_and_bounded():
    legs = _build("long")
    ml = max_loss(legs, 50)
    assert 0 < ml <= 100   # 2-step width on NIFTY = 100


def test_net_debit_is_negative_of_credit():
    legs = _build("long")
    assert net_debit(legs) == pytest.approx(-net_credit(legs))


def test_symbol_weekly_format():
    # 2026-07-14 is a Tuesday but NOT the last Tuesday of July 2026
    sym = _build_symbol("NIFTY", "2026-07-14", 24100, "PE")
    assert sym == "NIFTY2671424100PE"


def test_symbol_monthly_format():
    # 2026-07-28 IS the last Tuesday of July 2026 → monthly format
    sym = _build_symbol("BANKNIFTY", "2026-07-28", 57000, "CE")
    assert sym == "BANKNIFTY26JUL57000CE"


def test_no_valid_expiry_returns_empty():
    near_only = [{"date": "2026-07-03", "display": "x", "dte": 1, "series": "weekly", "short": "s"}]
    assert build_composite("NIFTY", 24100.0, "long", 0.3, 0.15, "max_pain", near_only, 50) == []
