"""Per-agent virtual book on top of a shared broker account.

100 agents × $1k can't each hold their own Alpaca account. We pool into one
real paper account, but each agent has an isolated book of positions, cash,
and P&L computed locally. Fills from the real broker get attributed back to
the agent that placed the parent order.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from tradefarm.runtime.clock import now_utc

# Round-5 audit fix (Z): bound the per-book reconciliation dedup set.
# 100 agents × 10k fills each = 1M ids max, but each is small (string).
# Acceptable; the cap is per-book so a single book never exceeds 10k.
_RECONCILED_IDS_LRU_CAP = 10_000


def _utcnow() -> datetime:
    return now_utc()


@dataclass
class VirtualPosition:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    # Set when qty goes from 0 to non-zero; cleared when qty returns to 0.
    # Drives the RiskManager time-stop.
    opened_at: datetime | None = None

    def apply_fill(self, side: str, qty: float, price: float, at: datetime | None = None) -> float:
        """Returns realized PnL from this fill."""
        at = at or _utcnow()
        was_zero = self.qty == 0
        signed = qty if side == "buy" else -qty
        new_qty = self.qty + signed
        realized = 0.0
        if was_zero or (self.qty > 0) == (signed > 0):
            if new_qty != 0:
                self.avg_price = (self.avg_price * self.qty + price * signed) / new_qty
        else:
            closing = min(abs(signed), abs(self.qty))
            realized = closing * (price - self.avg_price) * (1 if self.qty > 0 else -1)
            if abs(signed) > abs(self.qty):
                self.avg_price = price
        self.qty = new_qty
        if self.qty == 0:
            self.avg_price = 0.0
            self.opened_at = None
        elif was_zero:
            self.opened_at = at
        return realized


@dataclass
class VirtualBook:
    agent_id: int
    cash: float
    realized_pnl: float = 0.0
    # Plain dict (not defaultdict) — the previous defaultdict auto-vivified
    # entries with `VirtualPosition("")` for unseen symbols, leaving the
    # symbol field empty for any code path that read `pos.symbol`. Forced
    # all positions through `record_fill` / `_get_or_create` instead.
    positions: dict[str, VirtualPosition] = field(default_factory=dict)
    # Broker order ids already reconciled — prevents double-counting on
    # reconciler restart or retry. Round-5 audit fix (Z): bounded LRU
    # so a long-running broadcast can't accumulate every order_id
    # forever. Replaces the unbounded set.
    _reconciled_ids: OrderedDict[str, None] = field(default_factory=OrderedDict)

    def _add_reconciled_id(self, broker_order_id: str) -> None:
        """LRU-bounded insert into the dedup set."""
        self._reconciled_ids[broker_order_id] = None
        while len(self._reconciled_ids) > _RECONCILED_IDS_LRU_CAP:
            self._reconciled_ids.popitem(last=False)

    def _get_or_create(self, symbol: str) -> VirtualPosition:
        pos = self.positions.get(symbol)
        if pos is None:
            pos = VirtualPosition(symbol)
            self.positions[symbol] = pos
        return pos

    def record_fill(
        self, symbol: str, side: str, qty: float, price: float, at: datetime | None = None
    ) -> float:
        """Apply a fill to this book. Returns the realized PnL produced by
        this fill alone (zero for opening fills / same-side adds, non-zero
        for fills that close or flip part/all of a position). The
        book's ``realized_pnl`` running total is updated by the same amount.
        """
        pos = self._get_or_create(symbol)
        notional = qty * price
        self.cash += notional if side == "sell" else -notional
        realized = pos.apply_fill(side, qty, price, at=at)
        self.realized_pnl += realized
        return realized

    def apply_reconciled_fill(
        self,
        symbol: str,
        side: str,
        qty: float,
        mark_price: float,
        actual_price: float,
        broker_order_id: str,
        at: datetime | None = None,
    ) -> bool:
        """Replace an optimistic fill (already booked at ``mark_price``)
        with the actual fill at ``actual_price``.

        Idempotent on ``broker_order_id`` — duplicate calls are silent
        no-ops. Returns True when applied, False when skipped.

        Net effect of the correction:
          - cash adjusted by ``-delta * qty`` for buys (paid more/less
            than recorded), ``+delta * qty`` for sells.
          - For the *opening* portion of the fill: avg_price's
            contribution from this fill is corrected from mark to actual.
          - For the *closing* portion of the fill: realized_pnl's
            contribution from this fill is corrected from
            ``closing_qty * (mark - prev_avg)`` to
            ``closing_qty * (actual - prev_avg)``.

        The earlier reverse-then-reapply approach was wrong: by the
        time the reverse runs, the post-fill ``avg_price`` already
        reflects the optimistic mark, so the synthetic opposite-side
        fill closed against the new avg (not the pre-fill avg) and
        booked phantom realized PnL on adds-to-existing-position.

        This implementation works directly from the delta + the
        ``opening_qty / closing_qty`` split derived from the pre-fill
        position state. We don't have that state at reconcile time;
        the closest we have is the post-fill state. Recover the
        pre-fill state by reversing the fill in math (not in record):
        from (post_qty, post_avg) and the known fill (side, qty,
        mark_price), the pre-fill (prev_qty, prev_avg) is the unique
        solution that ``apply_fill`` would have stepped from.
        """
        if broker_order_id in self._reconciled_ids:
            return False
        self._add_reconciled_id(broker_order_id)
        if abs(mark_price - actual_price) < 1e-9:
            return True  # nothing to correct, but still consume the id
        delta = actual_price - mark_price  # signed
        pos = self.positions.get(symbol)
        if pos is None:
            # No position to correct against; just adjust cash.
            cash_delta = -delta * qty if side == "buy" else delta * qty
            self.cash += cash_delta
            return True

        # Reverse `apply_fill` arithmetic to recover pre-fill state.
        signed = qty if side == "buy" else -qty
        post_qty = pos.qty
        post_avg = pos.avg_price
        prev_qty = post_qty - signed
        if abs(prev_qty) < 1e-9:
            # Position was opened by this fill from flat.
            prev_qty = 0.0
            prev_avg = 0.0
        elif (prev_qty > 0) == (signed > 0):
            # Same-side as the fill: an add-to-position. Recover prev_avg
            # from the weighted-mean update:
            #     post_avg = (prev_avg * prev_qty + mark * signed) / post_qty
            prev_avg = (post_avg * post_qty - mark_price * signed) / prev_qty
        else:
            # Opposite-side: a (partial) close or flip. apply_fill keeps
            # avg_price unchanged on partial closes; on a flip the new
            # avg is the fill price. Either way, prev_avg == post_avg
            # only for the partial-close case. For a flip,
            # `abs(signed) > abs(prev_qty)`, so we detect via sign-flip
            # of (prev_qty, post_qty).
            if (post_qty > 0) != (prev_qty > 0) and post_qty != 0:
                # Flip happened: post_avg was set to mark_price.
                # Pre-fill avg is whatever it was before this fill; we
                # can't recover it from post-state alone, but the only
                # consumer that cares about prev_avg here is the
                # realized-PnL correction for the closing portion,
                # which uses prev_avg directly. Best-effort fall-back:
                # treat avg as post_avg (= mark) so the closing portion's
                # realized was originally `closing_qty * (mark - mark) = 0`,
                # which matches the fact that on a flip apply_fill
                # books realized = closing_qty * (mark - prev_avg)
                # using the actual prev_avg. We don't have it.
                # Apply only the cash + remaining-opening-portion
                # correction.
                prev_avg = post_avg
            else:
                # Pure partial close: avg unchanged.
                prev_avg = post_avg

        # Now split the qty into closing vs opening portions relative
        # to the pre-fill position.
        if prev_qty == 0:
            closing_qty, opening_qty = 0.0, qty
        elif (prev_qty > 0) == (signed > 0):
            closing_qty, opening_qty = 0.0, qty
        else:
            closing_qty = min(qty, abs(prev_qty))
            opening_qty = qty - closing_qty

        # 1. Cash adjustment for the full qty.
        cash_delta = -delta * qty if side == "buy" else delta * qty
        self.cash += cash_delta

        # 2. Realized-PnL correction for the closing portion. The
        #    closing direction is the SIGN OF prev_qty (closing a long
        #    is a sell, closing a short is a buy). On a sell that
        #    closes a long, realized was originally
        #        closing_qty * (mark - prev_avg)
        #    and should be
        #        closing_qty * (actual - prev_avg).
        #    Difference: closing_qty * delta with the right sign.
        if closing_qty > 0:
            direction = 1.0 if prev_qty > 0 else -1.0
            self.realized_pnl += closing_qty * delta * direction

        # 3. avg_price correction for the opening portion. avg's
        #    contribution from this fill is the price × opening_qty
        #    blended into the post-fill total. Recompute post_avg from
        #    the actual price for the opening_qty.
        if opening_qty > 0 and post_qty != 0:
            # Closing reduces |prev_qty| toward zero, regardless of
            # which side opened the prior position.
            if closing_qty > 0:
                prev_sign = 1.0 if prev_qty > 0 else -1.0
                mid_qty = prev_qty - prev_sign * closing_qty
            else:
                mid_qty = prev_qty
            # Apply the opening portion at actual price.
            opening_signed = opening_qty if signed > 0 else -opening_qty
            final_qty = mid_qty + opening_signed
            if abs(final_qty) > 1e-9:
                mid_avg = prev_avg if abs(mid_qty) > 1e-9 else 0.0
                pos.avg_price = (mid_avg * mid_qty + actual_price * opening_signed) / final_qty
        return True

    # Kept for backwards compatibility — used by older call sites. New
    # code should use apply_reconciled_fill which handles all sign cases.
    def apply_fill_delta(
        self,
        symbol: str,
        side: str,
        qty: float,
        delta: float,
        broker_order_id: str,
    ) -> bool:
        """DEPRECATED. Forwards to apply_reconciled_fill by deriving the
        mark price. Use apply_reconciled_fill directly."""
        # Reconstruct mark_price from actual_price = mark_price + delta.
        # Without the actual_price we can only invent one — caller must
        # use the new API for correctness; this shim covers fills where
        # delta is exactly 0 (no-op) without breaking the test suite.
        if abs(delta) < 1e-9:
            return broker_order_id not in self._reconciled_ids and bool(
                self._add_reconciled_id(broker_order_id) or True
            )
        # Best-effort for non-zero delta callers that haven't migrated:
        # treat delta as a cash-only correction (the old buggy behavior).
        # Real callers should switch to apply_reconciled_fill.
        if broker_order_id in self._reconciled_ids:
            return False
        self._add_reconciled_id(broker_order_id)
        if side == "buy":
            self.cash -= delta * qty
            pos = self.positions.get(symbol)
            if pos and pos.qty > 0:
                pos.avg_price += delta * qty / pos.qty
        else:
            self.cash += delta * qty
            self.realized_pnl += delta * qty
        return True

    def equity(self, marks: dict[str, float]) -> float:
        mtm = sum(p.qty * marks.get(s, p.avg_price) for s, p in self.positions.items())
        return self.cash + mtm

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        return sum(
            p.qty * (marks.get(s, p.avg_price) - p.avg_price)
            for s, p in self.positions.items()
            if p.qty != 0
        )
