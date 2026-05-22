"""Reconciler ↔ virtual book correctness across short opens, flips,
partial closes — the cases the previous `apply_fill_delta` got wrong.
"""

from __future__ import annotations

import pytest

from tradefarm.execution.virtual_book import VirtualBook


def _book() -> VirtualBook:
    return VirtualBook(agent_id=1, cash=10000.0)


def test_apply_reconciled_add_to_position_does_not_book_phantom_pnl():
    """REGRESSION: an earlier reverse-then-reapply implementation booked
    phantom realized PnL when reconciling an add-to-existing-position
    fill because the reverse step closed against the *post-fill*
    avg_price (which already contained the optimistic price).

    Setup: 5 shares @ avg 90. Optimistic buy 10 @ mark 100 → 15 @
    96.67, no realized. Reconcile to actual 99: net effect is the
    agent paid $1 less per share on the 10 added → cash up by $10,
    avg should reflect the actual price for the opening portion, and
    realized_pnl MUST stay at 0 (no shares were closed)."""
    b = _book()
    b.record_fill("AAA", "buy", 5, 90.0)  # initial: qty=5, avg=90
    b.record_fill("AAA", "buy", 10, 100.0)  # optimistic add
    realized_before = b.realized_pnl
    cash_before = b.cash
    assert b.positions["AAA"].qty == 15
    assert b.positions["AAA"].avg_price == pytest.approx(96.6666666, rel=1e-4)

    applied = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=100.0,
        actual_price=99.0,
        broker_order_id="o1",
    )
    assert applied
    # Cash: paid $10 less than recorded → cash up by $10.
    assert b.cash == pytest.approx(cash_before + 10.0)
    # Realized PnL: still zero — no shares closed.
    assert b.realized_pnl == pytest.approx(realized_before)
    # avg_price: now reflects (90*5 + 99*10) / 15 = 96.0.
    assert b.positions["AAA"].avg_price == pytest.approx(96.0, rel=1e-4)


def test_apply_reconciled_buy_open_corrects_cash_and_avg_price():
    b = _book()
    # Optimistic fill at mark 100, actual at 100.10.
    b.record_fill("AAA", "buy", 10, 100.0)
    assert b.cash == 9000.0
    assert b.positions["AAA"].avg_price == 100.0

    applied = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=100.0,
        actual_price=100.10,
        broker_order_id="o1",
    )
    assert applied
    # Net effect: actually paid $1001 instead of $1000.
    assert b.cash == pytest.approx(8999.0)
    assert b.positions["AAA"].qty == 10
    assert b.positions["AAA"].avg_price == pytest.approx(100.10)


def test_apply_reconciled_short_open_was_broken_now_correct():
    """Selling from flat opens a short. Earlier code's sell branch did
    `cash += delta * qty` AND `realized_pnl += delta * qty` even though
    no shares were closed. avg_price stayed at the optimistic mark."""
    b = _book()
    # Optimistic short open at 200, actual at 200.10.
    b.record_fill("AAA", "sell", 10, 200.0)
    pre_realized = b.realized_pnl
    assert b.positions["AAA"].qty == -10
    assert b.positions["AAA"].avg_price == 200.0

    applied = b.apply_reconciled_fill(
        "AAA",
        "sell",
        10,
        mark_price=200.0,
        actual_price=200.10,
        broker_order_id="o1",
    )
    assert applied
    # No realized PnL (nothing closed), avg_price now reflects actual.
    assert b.realized_pnl == pytest.approx(pre_realized)
    assert b.positions["AAA"].qty == -10
    assert b.positions["AAA"].avg_price == pytest.approx(200.10)


def test_apply_reconciled_long_to_short_flip_in_one_fill():
    """Long 10 @ 100, sell 15 @ 110 actual (mark 110). Closes 10 with
    realized = 10 * (110 - 100) = +100. Opens short 5 @ 110."""
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    # Optimistic sell at mark 110.
    b.record_fill("AAA", "sell", 15, 110.0)
    pre_realized = b.realized_pnl
    pre_pos = b.positions["AAA"].qty
    pre_avg = b.positions["AAA"].avg_price
    assert pre_pos == -5  # flipped
    assert pre_realized == pytest.approx(100.0)
    assert pre_avg == pytest.approx(110.0)

    # Reconcile with actual 110.20 (paid 0.20 more per share on the
    # whole 15-qty fill, but only 10 closed and 5 opened a new short).
    applied = b.apply_reconciled_fill(
        "AAA",
        "sell",
        15,
        mark_price=110.0,
        actual_price=110.20,
        broker_order_id="o1",
    )
    assert applied
    # Closing portion realized: 10 * (110.20 - 100) = +102 (was +100).
    # Net realized correction: +2.
    assert b.realized_pnl == pytest.approx(102.0)
    # Position still short 5, but at avg 110.20 (actual fill price).
    assert b.positions["AAA"].qty == -5
    assert b.positions["AAA"].avg_price == pytest.approx(110.20)


def test_apply_reconciled_buy_to_cover_short():
    """Short 10 @ 200, buy back 10 @ 190 (mark). Realized = 10*(200-190)=+100.
    Reconcile to actual 189 → realized should be +110."""
    b = _book()
    b.record_fill("AAA", "sell", 10, 200.0)
    b.record_fill("AAA", "buy", 10, 190.0)
    pre_realized = b.realized_pnl
    assert pre_realized == pytest.approx(100.0)
    assert b.positions["AAA"].qty == 0

    applied = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=190.0,
        actual_price=189.0,
        broker_order_id="o1",
    )
    assert applied
    # Realized correction: actually closed at 189, so +110 instead of +100.
    assert b.realized_pnl == pytest.approx(110.0)
    # Position still flat.
    assert b.positions["AAA"].qty == 0


def test_apply_reconciled_is_idempotent_on_broker_id():
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    first = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=100.0,
        actual_price=100.10,
        broker_order_id="o1",
    )
    second = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=100.0,
        actual_price=100.10,
        broker_order_id="o1",
    )
    assert first is True
    assert second is False
    # Cash only adjusted once.
    assert b.cash == pytest.approx(8999.0)


def test_apply_reconciled_no_op_when_mark_equals_actual():
    """No correction needed but still record the broker_order_id so
    a later non-zero delta with the same id doesn't double-apply."""
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    cash_before = b.cash
    applied = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=100.0,
        actual_price=100.0,
        broker_order_id="o1",
    )
    assert applied
    assert b.cash == cash_before


def test_positions_dict_does_not_autovivify_empty_symbol():
    """The previous defaultdict factory created `VirtualPosition("")`
    on a missing key — auto-vivifying entries whose `pos.symbol` was
    empty. Anyone iterating positions saw bogus rows."""
    b = _book()
    # Reading a missing key should NOT add it to the dict.
    assert b.positions.get("MISSING") is None
    assert "MISSING" not in b.positions


def test_record_fill_creates_position_with_correct_symbol():
    """When a fill is recorded for a fresh symbol the position's
    `symbol` field matches the dict key (previous code's autovivified
    entries had empty `symbol`)."""
    b = _book()
    b.record_fill("XYZ", "buy", 5, 50.0)
    pos = b.positions["XYZ"]
    assert pos.symbol == "XYZ"
    assert pos.qty == 5
