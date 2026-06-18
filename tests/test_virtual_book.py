from tradefarm.execution.virtual_book import VirtualBook


def test_buy_sell_roundtrip_realizes_pnl():
    book = VirtualBook(agent_id=1, cash=1000.0)
    book.record_fill("SPY", "buy", 2, 100.0)
    assert book.cash == 800.0
    assert book.positions["SPY"].qty == 2
    assert book.positions["SPY"].avg_price == 100.0

    book.record_fill("SPY", "sell", 2, 110.0)
    assert book.cash == 1020.0
    assert book.positions["SPY"].qty == 0
    assert book.realized_pnl == 20.0


def test_record_fill_clamps_through_zero_flip_to_flat():
    # Flat-only invariant: a sell exceeding the held long closes only to
    # flat — it never opens a short on the residual.
    book = VirtualBook(agent_id=1, cash=1000.0)
    book.record_fill("SPY", "buy", 5, 100.0)
    assert book.positions["SPY"].qty == 5

    realized = book.record_fill("SPY", "sell", 8, 110.0)  # would flip to -3
    assert realized == 5 * (110.0 - 100.0)  # only the 5 held closed
    assert book.positions["SPY"].qty == 0
    assert book.positions["SPY"].avg_price == 0.0
    # Cash reflects only the executed 5 shares (clamped), not 8.
    assert book.cash == 1000.0 - 5 * 100.0 + 5 * 110.0


def test_record_fill_clamps_buy_through_short_to_flat():
    # Symmetric guard on the short side: a buy exceeding the held short
    # covers only to flat, never opening a long.
    book = VirtualBook(agent_id=1, cash=1000.0)
    book.record_fill("SPY", "sell", 4, 100.0)  # open short 4
    assert book.positions["SPY"].qty == -4

    realized = book.record_fill("SPY", "buy", 7, 90.0)  # would flip to +3
    assert realized == 4 * (100.0 - 90.0)  # only the 4 short covered
    assert book.positions["SPY"].qty == 0
    assert book.positions["SPY"].avg_price == 0.0


def test_equity_marks_to_market():
    book = VirtualBook(agent_id=1, cash=500.0)
    book.record_fill("AAPL", "buy", 3, 200.0)
    assert book.equity({"AAPL": 210.0}) == 500.0 - 600.0 + 630.0
    assert book.unrealized_pnl({"AAPL": 210.0}) == 30.0


def test_apply_fill_delta_buy_slippage():
    # Paid 0.05/sh more than the optimistic mark.
    book = VirtualBook(agent_id=1, cash=1000.0)
    book.record_fill("SPY", "buy", 4, 100.0)  # recorded at mark
    assert book.cash == 600.0
    assert book.positions["SPY"].avg_price == 100.0

    applied = book.apply_fill_delta("SPY", "buy", 4, delta=0.05, broker_order_id="abc")
    assert applied is True
    assert book.cash == 599.8  # 600 - 0.05*4
    assert book.positions["SPY"].avg_price == 100.05

    # Re-applying the same broker_order_id is a no-op.
    applied = book.apply_fill_delta("SPY", "buy", 4, delta=0.05, broker_order_id="abc")
    assert applied is False
    assert book.cash == 599.8


def test_apply_fill_delta_sell_better_price():
    # Received 0.10/sh more than expected on the exit.
    book = VirtualBook(agent_id=1, cash=1000.0)
    book.record_fill("QQQ", "buy", 2, 500.0)
    book.record_fill("QQQ", "sell", 2, 510.0)
    assert book.cash == 1020.0
    assert book.realized_pnl == 20.0

    book.apply_fill_delta("QQQ", "sell", 2, delta=0.10, broker_order_id="sell-1")
    assert book.cash == 1020.2
    assert book.realized_pnl == 20.2
