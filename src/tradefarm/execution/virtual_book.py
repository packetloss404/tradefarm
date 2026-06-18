"""Per-agent virtual book on top of a shared broker account.

100 agents × $1k can't each hold their own Alpaca account. We pool into one
real paper account, but each agent has an isolated book of positions, cash,
and P&L computed locally. Fills from the real broker get attributed back to
the agent that placed the parent order.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from tradefarm.runtime.clock import now_utc

log = structlog.get_logger(__name__)

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
        """Apply a fill, returning the realized PnL it produces.

        Flat-only invariant: a fill that would carry the position THROUGH
        zero to the opposite sign in a single step is clamped so it can
        only close down to flat (never open the opposite side). v1 agents
        never short, so a flip can only be a data error — and the
        post-flip residual avg_price is unrecoverable at reconcile time,
        which would poison downstream PnL/equity for the symbol.
        """
        at = at or _utcnow()
        qty = self._clamp_flip(side, qty)
        if qty <= 0:
            return 0.0
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
            # No flip is possible after `_clamp_flip`, so the closing
            # branch never opens the opposite side; avg_price is left
            # unchanged on a partial close and reset to flat below.
        self.qty = new_qty
        if self.qty == 0:
            self.avg_price = 0.0
            self.opened_at = None
        elif was_zero:
            self.opened_at = at
        return realized

    def _clamp_flip(self, side: str, qty: float) -> float:
        """Clamp ``qty`` so an opposite-side fill can only close to flat.

        Returns the executable qty (== requested qty unless a through-zero
        flip was detected, in which case it is reduced to ``abs(self.qty)``).
        """
        signed = qty if side == "buy" else -qty
        if self.qty == 0 or (self.qty > 0) == (signed > 0):
            return qty  # opening / same-side add — never a flip
        if abs(signed) <= abs(self.qty):
            return qty  # (partial) close that stays same-sign or hits flat
        clamped = abs(self.qty)
        log.warning(
            "fill_flip_clamped",
            symbol=self.symbol,
            side=side,
            requested_qty=qty,
            clamped_qty=clamped,
            held_qty=self.qty,
        )
        return clamped


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
        # Clamp flat-only BEFORE moving cash so the cash delta reflects the
        # executed (possibly clamped) qty, never the requested qty.
        qty = pos._clamp_flip(side, qty)
        if qty <= 0:
            return 0.0
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

        Flat-only invariant: because ``record_fill`` clamps any
        through-zero flip to flat (see ``VirtualPosition._clamp_flip``),
        the booked fill never opened an opposite-side position. The
        reconcile path mirrors that clamp so it never corrects more than
        the executed close — the old unrecoverable-flip fallback (which
        left ``prev_avg`` pinned to the optimistic mark) is gone.
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

        signed = qty if side == "buy" else -qty
        post_qty = pos.qty
        post_avg = pos.avg_price

        # Reverse `apply_fill` arithmetic to recover pre-fill state.
        #
        # The optimistic fill was clamped flat-only at `record_fill` time
        # (see `VirtualPosition._clamp_flip`), so the booked fill never
        # opened an opposite-side position. A naive `post_qty - signed`
        # recovery would mistake a clamped full-close (post flat) for a
        # flip; we guard against that by never letting the recovered
        # pre-fill cross zero in the direction of `signed`.
        prev_qty = post_qty - signed
        if abs(prev_qty) < 1e-9:
            # Position was opened (or fully closed) by this fill from/to flat.
            prev_qty = 0.0
            prev_avg = 0.0
        elif (prev_qty > 0) == (signed > 0):
            # Same-side as the fill: an add-to-position. Recover prev_avg
            # from the weighted-mean update:
            #     post_avg = (prev_avg * prev_qty + mark * signed) / post_qty
            prev_avg = (post_avg * post_qty - mark_price * signed) / prev_qty
        else:
            # Opposite-side partial close. Flat-only clamping guarantees no
            # through-zero flip survives to here, so avg_price is unchanged
            # by the close and prev_avg == post_avg.
            prev_avg = post_avg

        # Detect a clamped flip: the requested qty would have carried the
        # pre-fill position THROUGH zero to the opposite sign. Because the
        # booked fill was clamped to flat, the executed close was only
        # `abs(prev_qty)` and no opposite side was ever opened. Correct
        # against the executed (clamped) qty, not the requested qty, so we
        # never poison avg_price or open a phantom position.
        if prev_qty != 0 and (prev_qty > 0) != (signed > 0) and qty > abs(prev_qty):
            executed = abs(prev_qty)
            log.warning(
                "reconciled_fill_flip_clamped",
                symbol=symbol,
                side=side,
                requested_qty=qty,
                clamped_qty=executed,
                held_qty=prev_qty,
                broker_order_id=broker_order_id,
            )
            qty = executed

        # Now split the (possibly clamped) qty into closing vs opening
        # portions relative to the pre-fill position.
        if prev_qty == 0:
            # Pure open from flat — nothing to close.
            closing_qty, opening_qty = 0.0, qty
        elif (prev_qty > 0) == (signed > 0):
            # Same-side add — nothing to close.
            closing_qty, opening_qty = 0.0, qty
        else:
            # Opposite-side fill. The flat-only invariant guarantees the
            # booked fill NEVER opened an opposite-side position, so the
            # opening portion is always zero — the whole executed fill was
            # a close against the pre-fill holding.
            closing_qty = min(qty, abs(prev_qty))
            opening_qty = 0.0
            # KNOWN BOUND (degenerate input only): when the optimistic fill
            # landed the book exactly flat (post_qty == 0) we cannot tell an
            # exact full close (qty == held) apart from an over-sell that
            # `record_fill` clamped to flat (qty > held) — the clamp
            # discards the true executed qty, so `prev_qty` is recovered as
            # the *requested* qty and `closing_qty == qty`. For every
            # consistent (qty <= held) fill — which is all v1 ever produces
            # (long-only + risk-capped) — the cash/realized correction below
            # is EXACT. For the should-never-happen over-sell the correction
            # is best-effort, bounded by `(requested - held) * |delta|`;
            # avg_price and positions stay correct (flat) regardless. The
            # over-sell itself is logged at source as `fill_flip_clamped`
            # in `record_fill`. Exact resolution of that path would require
            # threading the executed qty through record_fill (see
            # `_clamp_flip`), which we deliberately don't do for a guard
            # path that also can't survive a mid-settlement restart.

        # 1. Cash adjustment for the executed (closing + opening) qty. With
        #    the flat-only invariant opening_qty is 0 on opposite-side
        #    fills, so cash never corrects an opening that never happened.
        executed_qty = closing_qty + opening_qty
        cash_delta = -delta * executed_qty if side == "buy" else delta * executed_qty
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
