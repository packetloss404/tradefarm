"""Money helper + Decimal-exactness regression tests.

The whole point of moving money to Decimal is that repeated fractional
arithmetic stays exact and the abs()<1e-9 epsilon guards can't misclassify
a genuinely-flat position. These tests pin that behavior.
"""

from __future__ import annotations

from decimal import Decimal

from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.runtime.money import D, quantize_money, quantize_qty, to_float


def test_D_routes_float_through_str_no_binary_artifact():
    # 0.1 + 0.2 in binary float is 0.30000000000000004; D() must reflect
    # the printed value so money math stays exact.
    assert D(0.1) == Decimal("0.1")
    assert D(0.1) + D(0.2) == Decimal("0.3")
    assert D(Decimal("5")) == Decimal("5")
    assert D(7) == Decimal("7")
    assert D("3.14") == Decimal("3.14")


def test_quantizers_round_half_even():
    assert quantize_money(Decimal("1.00005")) == Decimal("1.0000")  # banker's
    assert quantize_money(Decimal("1.00015")) == Decimal("1.0002")
    assert quantize_qty(Decimal("1.00005")) == Decimal("1.0000")
    assert quantize_qty(Decimal("2.123456")) == Decimal("2.1235")


def test_to_float_passes_none_and_converts_decimal():
    assert to_float(None) is None
    assert to_float(Decimal("9000.00")) == 9000.0
    assert isinstance(to_float(Decimal("1.5")), float)


def test_book_money_is_decimal_typed():
    book = VirtualBook(agent_id=1, cash=1000.0)
    assert isinstance(book.cash, Decimal)
    assert isinstance(book.realized_pnl, Decimal)
    book.record_fill("SPY", "buy", 3, 100.0)
    pos = book.positions["SPY"]
    assert isinstance(pos.qty, Decimal)
    assert isinstance(pos.avg_price, Decimal)
    assert isinstance(book.equity({"SPY": 100.0}), Decimal)
    assert isinstance(book.unrealized_pnl({"SPY": 100.0}), Decimal)


def test_repeated_fractional_fills_stay_exact():
    # Float accumulation drifts; Decimal does not. Buy 0.1 shares @ $0.10
    # ten times → exactly $0.10 of notional, cash exactly 1000 - 0.10.
    book = VirtualBook(agent_id=1, cash=1000.0)
    for _ in range(10):
        book.record_fill("PNY", "buy", 0.1, 0.10)
    # 10 × 0.1 × 0.10 = 0.10 of notional, exactly.
    assert book.cash == Decimal("999.90")
    assert book.positions["PNY"].qty == Decimal("1.0")
    assert book.positions["PNY"].avg_price == Decimal("0.10")


def test_round_trip_returns_to_exact_flat_no_epsilon_drift():
    # A full close returns the position to EXACTLY flat — the equality
    # check is exact (no 1e-9 fudge) under Decimal.
    book = VirtualBook(agent_id=1, cash=1000.0)
    book.record_fill("AAA", "buy", 7, 12.34)
    realized = book.record_fill("AAA", "sell", 7, 12.34)
    assert realized == Decimal("0")
    assert book.positions["AAA"].qty == Decimal("0")
    assert book.positions["AAA"].avg_price == Decimal("0")
    # Cash is exactly back to the start (no float drift on 7 × 12.34 twice).
    assert book.cash == Decimal("1000")


def test_equity_and_unrealized_accept_float_marks():
    book = VirtualBook(agent_id=1, cash=500.0)
    book.record_fill("AAPL", "buy", 3, 200.0)
    # float marks in, Decimal out.
    assert book.equity({"AAPL": 210.0}) == Decimal("530")
    assert book.unrealized_pnl({"AAPL": 210.0}) == Decimal("30")
    # Missing mark falls back to avg_price → zero unrealized.
    assert book.unrealized_pnl({}) == Decimal("0")
