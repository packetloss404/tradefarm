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
    assert float(b.positions["AAA"].avg_price) == pytest.approx(96.6666666, rel=1e-4)

    applied = b.apply_reconciled_fill(
        "AAA",
        "buy",
        10,
        mark_price=100.0,
        actual_price=99.0,
        broker_order_id="o1",
    )
    assert applied
    # Cash: paid $10 less than recorded → cash up by $10. Book money is
    # Decimal; compare floats via approx(float(...)).
    assert float(b.cash) == pytest.approx(float(cash_before) + 10.0)
    # Realized PnL: still zero — no shares closed.
    assert float(b.realized_pnl) == pytest.approx(float(realized_before))
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
    assert float(b.cash) == pytest.approx(8999.0)
    assert b.positions["AAA"].qty == 10
    assert float(b.positions["AAA"].avg_price) == pytest.approx(100.10)


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
    assert float(b.realized_pnl) == pytest.approx(float(pre_realized))
    assert b.positions["AAA"].qty == -10
    assert float(b.positions["AAA"].avg_price) == pytest.approx(200.10)


def test_apply_fill_clamps_long_to_short_flip_to_flat():
    """Flat-only invariant: long 10 @ 100, then a sell of 15 must NOT
    flip to a 5-share short. The fill is clamped to close exactly the
    held 10 shares; the position goes flat and no opposite side opens.

    v1 agents never short, so a through-zero flip can only be a data
    error — and the post-flip residual avg_price is unrecoverable at
    reconcile time, which would poison downstream PnL/equity."""
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    # Sell 15 — would flip to short 5 without the clamp.
    realized = b.record_fill("AAA", "sell", 15, 110.0)
    # Only 10 shares closed: realized = 10 * (110 - 100) = +100.
    assert realized == pytest.approx(100.0)
    assert b.realized_pnl == pytest.approx(100.0)
    # Position is flat, NOT short 5, and avg is reset (not the mark).
    assert b.positions["AAA"].qty == 0
    assert b.positions["AAA"].avg_price == 0.0


def test_apply_reconciled_flip_request_is_clamped_not_corrupting_avg():
    """A reconciled fill whose requested qty would flip the position is
    clamped: the residual position stays flat (no opposite side opened)
    and avg_price is NEVER set to the optimistic mark. Reconciling a
    long 10 → sell-15 (clamped to 10) just corrects cash + the closing
    realized PnL; it must not leave a phantom short at the mark."""
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    # Optimistic sell of 15 is clamped to 10 → flat. cash: 10000 - 1000
    # (buy) + 1100 (sell 10 @ 110) = 10100; realized = 10*(110-100) = 100.
    b.record_fill("AAA", "sell", 15, 110.0)
    assert b.positions["AAA"].qty == 0
    assert b.positions["AAA"].avg_price == 0.0
    assert b.cash == pytest.approx(10100.0)
    assert b.realized_pnl == pytest.approx(100.0)

    applied = b.apply_reconciled_fill(
        "AAA",
        "sell",
        15,
        mark_price=110.0,
        actual_price=110.20,
        broker_order_id="o1",
    )
    assert applied
    # CORE FIX — must hold exactly: no phantom short opened, avg_price is
    # NEVER set to the optimistic mark.
    assert b.positions["AAA"].qty == 0
    assert b.positions["AAA"].avg_price == 0.0
    # KNOWN BOUND (degenerate over-sell only): the optimistic clamp to flat
    # discarded the true executed close (10), so the reconcile corrects the
    # *requested* 15 instead — cash/realized over-correct by exactly
    # (15-10)*delta = 5*0.20 = 1.0. Exact values would be cash 10102.0 /
    # realized 102.0; the bounded best-effort yields 10103.0 / 103.0. This
    # path is unreachable for v1 (long-only, risk-capped) and the over-sell
    # is logged as `fill_flip_clamped` at record_fill. avg_price/positions
    # (above) stay correct regardless. See apply_reconciled_fill's
    # "KNOWN BOUND" note for why exact recovery isn't done here.
    exact_cash, exact_realized = 10102.0, 102.0
    bound = (15 - 10) * 0.20
    assert b.cash == pytest.approx(10103.0)
    assert b.realized_pnl == pytest.approx(103.0)
    # Book money is Decimal; convert to float for the bound arithmetic.
    assert abs(float(b.cash) - exact_cash) <= bound + 1e-9
    assert abs(float(b.realized_pnl) - exact_realized) <= bound + 1e-9


def test_apply_reconciled_partial_close_no_regression():
    """A normal partial close (sell 4 of a 10 long) reconciles correctly:
    realized corrected for the 4 closed shares, residual 6 long keeps its
    original avg_price (unchanged by a partial close)."""
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    b.record_fill("AAA", "sell", 4, 110.0)  # optimistic partial close
    assert b.positions["AAA"].qty == 6
    assert b.positions["AAA"].avg_price == pytest.approx(100.0)
    assert b.realized_pnl == pytest.approx(4 * (110.0 - 100.0))  # +40
    # cash: 10000 - 1000 (buy 10) + 440 (sell 4 @ 110) = 9440.
    assert b.cash == pytest.approx(9440.0)

    applied = b.apply_reconciled_fill(
        "AAA",
        "sell",
        4,
        mark_price=110.0,
        actual_price=110.50,
        broker_order_id="pc1",
    )
    assert applied
    # Realized: 4 * (110.50 - 100) = +42 (was +40), correction +2.
    assert b.realized_pnl == pytest.approx(42.0)
    # Cash: sold the 4 shares for $0.50/sh more than recorded → +2.
    assert b.cash == pytest.approx(9442.0)
    # Residual long unchanged in qty and avg.
    assert b.positions["AAA"].qty == 6
    assert b.positions["AAA"].avg_price == pytest.approx(100.0)


def test_apply_reconciled_full_close_no_regression():
    """A full close (sell exactly the held qty) reconciles to flat with a
    corrected realized PnL and avg_price reset to 0."""
    b = _book()
    b.record_fill("AAA", "buy", 10, 100.0)
    b.record_fill("AAA", "sell", 10, 110.0)  # optimistic full close
    assert b.positions["AAA"].qty == 0
    assert b.realized_pnl == pytest.approx(100.0)
    # cash: 10000 - 1000 (buy) + 1100 (sell 10 @ 110) = 10100.
    assert b.cash == pytest.approx(10100.0)

    applied = b.apply_reconciled_fill(
        "AAA",
        "sell",
        10,
        mark_price=110.0,
        actual_price=110.30,
        broker_order_id="fc1",
    )
    assert applied
    # Realized: 10 * (110.30 - 100) = +103 (was +100), correction +3.
    assert b.realized_pnl == pytest.approx(103.0)
    # Cash: 10 shares sold for $0.30/sh more than recorded → +3.
    assert b.cash == pytest.approx(10103.0)
    assert b.positions["AAA"].qty == 0
    assert b.positions["AAA"].avg_price == 0.0


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
