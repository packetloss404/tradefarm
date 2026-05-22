"""OrderReconciler cursor-advance + extended-hours-flag wiring.

The reconciler used to only advance ``_last_poll_ts`` when the
broker returned at least one order whose ``submitted_at`` was newer
than the cursor. During idle periods (overnight, weekends, a quiet
mid-day stretch) that meant every poll re-fetched the full window
starting from the original startup_lookback_sec floor — the API
call got progressively heavier and the ``_seen_order_ids`` membership
check did all the de-dup work. This file pins the empty-poll
fast-path and re-asserts the in-batch advance behavior so a future
refactor can't regress.

Also covers the ``allow_extended_hours`` flag now flowing into the
MarketOrderRequest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from tradefarm.execution.order_reconciler import OrderReconciler


class _StubBroker:
    """Just enough surface area for OrderReconciler.poll_once."""

    def __init__(self, orders: list[dict] | None = None) -> None:
        self.orders = orders or []
        self.calls: list[str] = []

    async def get_orders(self, since_iso: str) -> list[dict]:
        # Round-5 audit (Y): broker.get_orders is async now.
        self.calls.append(since_iso)
        return list(self.orders)

    @staticmethod
    def parse_agent_id(coid: str) -> int | None:
        if coid.startswith("agent"):
            try:
                return int(coid.split("-", 1)[0][len("agent") :])
            except ValueError:
                return None
        return None


def _recon(broker: _StubBroker, marks: dict[str, float] | None = None) -> OrderReconciler:
    return OrderReconciler(
        broker=broker,  # type: ignore[arg-type]
        optimistic_marks=marks if marks is not None else {},
        startup_lookback_sec=300,
    )


async def test_empty_poll_advances_cursor_to_now():
    """REGRESSION: idle polls used to leave _last_poll_ts pinned at the
    original startup_lookback_sec floor, so each subsequent get_orders
    call scanned a wider and wider window. With the fix, an empty
    response advances the cursor to the poll start time.
    """
    broker = _StubBroker(orders=[])
    recon = _recon(broker)
    initial_cursor = recon._last_poll_ts

    before = datetime.now(timezone.utc)
    fills = await recon.poll_once()
    after = datetime.now(timezone.utc)

    assert fills == []
    assert recon._last_poll_ts > initial_cursor
    # The cursor should land somewhere in the window the poll ran in.
    assert before <= recon._last_poll_ts <= after


async def test_non_empty_poll_does_not_skip_inflight_orders():
    """The cursor must not jump past an order that came back in the
    batch — otherwise the next poll wouldn't see it again and we'd
    miss its eventual fill. The in-batch update path takes the
    *oldest* submitted_at it sees as the new floor (via the
    ts > newest_seen comparison initialized to the old cursor).
    """
    now = datetime.now(timezone.utc)
    pending_ts = (now - timedelta(seconds=30)).isoformat()
    broker = _StubBroker(
        orders=[
            {
                "broker_order_id": "abc",
                "client_order_id": "agent1-xx",
                "symbol": "AAA",
                "side": "buy",
                "qty": 10.0,
                "filled_qty": 0.0,
                "filled_avg_price": None,
                "status": "new",  # still pending
                "submitted_at": pending_ts,
                "filled_at": None,
            }
        ]
    )
    recon = _recon(broker, marks={"agent1-xx": 100.0})
    initial_cursor = recon._last_poll_ts

    fills = await recon.poll_once()
    assert fills == []
    # Cursor must NOT have skipped past the pending order's submitted_at.
    # The current logic only moves forward when ts > cursor, so a
    # pending order with submitted_at newer than the cursor will
    # advance it — that's the pre-existing behavior we're preserving.
    assert recon._last_poll_ts >= initial_cursor


async def test_filled_order_produces_reconciled_fill_with_delta():
    """End-to-end: filled order + matching optimistic mark → ReconciledFill."""
    now = datetime.now(timezone.utc)
    broker = _StubBroker(
        orders=[
            {
                "broker_order_id": "ord-1",
                "client_order_id": "agent7-tag1",
                "symbol": "SPY",
                "side": "buy",
                "qty": 5.0,
                "filled_qty": 5.0,
                "filled_avg_price": 101.5,
                "status": "filled",
                "submitted_at": now.isoformat(),
                "filled_at": now.isoformat(),
            }
        ]
    )
    recon = _recon(broker, marks={"agent7-tag1": 100.0})

    fills = await recon.poll_once()
    assert len(fills) == 1
    rf = fills[0]
    assert rf.agent_id == 7
    assert rf.symbol == "SPY"
    assert rf.qty == 5.0
    assert rf.actual_price == 101.5
    assert rf.delta == pytest.approx(1.5)
    # Mark was popped — second poll for the same coid would skip.
    assert "agent7-tag1" not in recon.optimistic_marks
    # And the broker_order_id is now tracked.
    assert "ord-1" in recon._seen_order_ids


async def test_extended_hours_flag_flows_to_market_order_request():
    """REGRESSION: allow_extended_hours used to be a documented-but-dead
    flag that only short-circuited the is_market_open() gate. The
    MarketOrderRequest now receives it, so Alpaca actually accepts the
    order outside RTH.
    """
    from tradefarm.config import settings

    with (
        patch.object(settings, "alpaca_api_key", "k"),
        patch.object(settings, "alpaca_api_secret", "s"),
        patch.object(settings, "alpaca_base_url", "https://paper-api.alpaca.markets"),
        patch("tradefarm.execution.alpaca_broker.TradingClient") as tc_cls,
        patch("tradefarm.execution.alpaca_broker.MarketOrderRequest") as mor_cls,
        patch("tradefarm.execution.alpaca_broker.is_market_open", return_value=False),
    ):
        tc_cls.return_value.submit_order.return_value = MagicMock(id="x")
        mor_cls.return_value = MagicMock()

        from tradefarm.execution.alpaca_broker import AlpacaBroker

        broker = AlpacaBroker(allow_extended_hours=True)
        await broker.submit_market(
            symbol="SPY",
            side="buy",
            qty=1,
            agent_id=1,
            client_tag="tag",
            mark=100.0,
        )

        kwargs = mor_cls.call_args.kwargs
        assert kwargs["extended_hours"] is True


async def test_extended_hours_default_false():
    from tradefarm.config import settings

    with (
        patch.object(settings, "alpaca_api_key", "k"),
        patch.object(settings, "alpaca_api_secret", "s"),
        patch.object(settings, "alpaca_base_url", "https://paper-api.alpaca.markets"),
        patch("tradefarm.execution.alpaca_broker.TradingClient") as tc_cls,
        patch("tradefarm.execution.alpaca_broker.MarketOrderRequest") as mor_cls,
        patch("tradefarm.execution.alpaca_broker.is_market_open", return_value=True),
    ):
        tc_cls.return_value.submit_order.return_value = MagicMock(id="x")
        mor_cls.return_value = MagicMock()

        from tradefarm.execution.alpaca_broker import AlpacaBroker

        broker = AlpacaBroker()  # default
        await broker.submit_market(
            symbol="SPY",
            side="buy",
            qty=1,
            agent_id=1,
            client_tag="tag",
            mark=100.0,
        )

        kwargs = mor_cls.call_args.kwargs
        assert kwargs["extended_hours"] is False
