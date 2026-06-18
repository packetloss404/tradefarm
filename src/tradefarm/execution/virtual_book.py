"""Per-agent virtual book on top of a shared broker account.

100 agents × $1k can't each hold their own Alpaca account. We pool into one
real paper account, but each agent has an isolated book of positions, cash,
and P&L computed locally. Fills from the real broker get attributed back to
the agent that placed the parent order.

Money is held as :class:`~decimal.Decimal` for exactness (cash, realized
P&L, avg price, qty). Inputs (marks/prices/qty) arrive as ``float`` from
market data / the broker and are coerced at the boundary via
:func:`tradefarm.runtime.money.D`. Output boundaries (WS payloads, REST
responses, ``json.dumps``) must convert back to ``float`` — see
``runtime.money.to_float``.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import structlog

from tradefarm.runtime.clock import now_utc
from tradefarm.runtime.money import D

log = structlog.get_logger(__name__)

# Round-5 audit fix (Z): bound the per-book reconciliation dedup set.
# 100 agents × 10k fills each = 1M ids max, but each is small (string).
# Acceptable; the cap is per-book so a single book never exceeds 10k.
_RECONCILED_IDS_LRU_CAP = 10_000

_ZERO = Decimal("0")


def _utcnow() -> datetime:
    return now_utc()


@dataclass
class VirtualPosition:
    symbol: str
    qty: Decimal = field(default_factory=lambda: Decimal("0"))
    avg_price: Decimal = field(default_factory=lambda: Decimal("0"))
    # Set when qty goes from 0 to non-zero; cleared when qty returns to 0.
    # Drives the RiskManager time-stop.
    opened_at: datetime | None = None

    def __post_init__(self) -> None:
        # Allow construction with float/int literals (tests, legacy callers).
        self.qty = D(self.qty)
        self.avg_price = D(self.avg_price)

    def apply_fill(
        self, side: str, qty: float | Decimal, price: float | Decimal, at: datetime | None = None
    ) -> Decimal:
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
        price = D(price)
        if qty <= _ZERO:
            return _ZERO
        was_zero = self.qty == _ZERO
        signed = qty if side == "buy" else -qty
        new_qty = self.qty + signed
        realized = _ZERO
        if was_zero or (self.qty > _ZERO) == (signed > _ZERO):
            if new_qty != _ZERO:
                self.avg_price = (self.avg_price * self.qty + price * signed) / new_qty
        else:
            closing = min(abs(signed), abs(self.qty))
            realized = (
                closing
                * (price - self.avg_price)
                * (Decimal(1) if self.qty > _ZERO else Decimal(-1))
            )
            # No flip is possible after `_clamp_flip`, so the closing
            # branch never opens the opposite side; avg_price is left
            # unchanged on a partial close and reset to flat below.
        self.qty = new_qty
        if self.qty == _ZERO:
            self.avg_price = _ZERO
            self.opened_at = None
        elif was_zero:
            self.opened_at = at
        return realized

    def _clamp_flip(self, side: str, qty: float | Decimal) -> Decimal:
        """Clamp ``qty`` so an opposite-side fill can only close to flat.

        Returns the executable qty (== requested qty unless a through-zero
        flip was detected, in which case it is reduced to ``abs(self.qty)``).
        """
        qty = D(qty)
        signed = qty if side == "buy" else -qty
        if self.qty == _ZERO or (self.qty > _ZERO) == (signed > _ZERO):
            return qty  # opening / same-side add — never a flip
        if abs(signed) <= abs(self.qty):
            return qty  # (partial) close that stays same-sign or hits flat
        clamped = abs(self.qty)
        log.warning(
            "fill_flip_clamped",
            symbol=self.symbol,
            side=side,
            requested_qty=float(qty),
            clamped_qty=float(clamped),
            held_qty=float(self.qty),
        )
        return clamped


@dataclass
class VirtualBook:
    agent_id: int
    cash: Decimal
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
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

    def __post_init__(self) -> None:
        # Coerce constructor inputs (tests/callers pass float literals).
        self.cash = D(self.cash)
        self.realized_pnl = D(self.realized_pnl)

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
        self,
        symbol: str,
        side: str,
        qty: float | Decimal,
        price: float | Decimal,
        at: datetime | None = None,
    ) -> Decimal:
        """Apply a fill to this book. Returns the realized PnL produced by
        this fill alone (zero for opening fills / same-side adds, non-zero
        for fills that close or flip part/all of a position). The
        book's ``realized_pnl`` running total is updated by the same amount.

        ``qty``/``price`` may arrive as ``float`` (broker boundary); they
        are coerced to Decimal internally.
        """
        pos = self._get_or_create(symbol)
        price = D(price)
        # Clamp flat-only BEFORE moving cash so the cash delta reflects the
        # executed (possibly clamped) qty, never the requested qty.
        qty = pos._clamp_flip(side, qty)
        if qty <= _ZERO:
            return _ZERO
        notional = qty * price
        self.cash += notional if side == "sell" else -notional
        realized = pos.apply_fill(side, qty, price, at=at)
        self.realized_pnl += realized
        return realized

    def apply_reconciled_fill(
        self,
        symbol: str,
        side: str,
        qty: float | Decimal,
        mark_price: float | Decimal,
        actual_price: float | Decimal,
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

        Money is exact (Decimal) so the pre-fill recovery / clamp checks
        compare against ``Decimal("0")`` exactly — no epsilon fudge needed.
        """
        if broker_order_id in self._reconciled_ids:
            return False
        self._add_reconciled_id(broker_order_id)
        qty = D(qty)
        mark_price = D(mark_price)
        actual_price = D(actual_price)
        if mark_price == actual_price:
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
        if prev_qty == _ZERO:
            # Position was opened (or fully closed) by this fill from/to flat.
            prev_avg = _ZERO
        elif (prev_qty > _ZERO) == (signed > _ZERO):
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
        if prev_qty != _ZERO and (prev_qty > _ZERO) != (signed > _ZERO) and qty > abs(prev_qty):
            executed = abs(prev_qty)
            log.warning(
                "reconciled_fill_flip_clamped",
                symbol=symbol,
                side=side,
                requested_qty=float(qty),
                clamped_qty=float(executed),
                held_qty=float(prev_qty),
                broker_order_id=broker_order_id,
            )
            qty = executed

        # Now split the (possibly clamped) qty into closing vs opening
        # portions relative to the pre-fill position.
        if prev_qty == _ZERO:
            # Pure open from flat — nothing to close.
            closing_qty, opening_qty = _ZERO, qty
        elif (prev_qty > _ZERO) == (signed > _ZERO):
            # Same-side add — nothing to close.
            closing_qty, opening_qty = _ZERO, qty
        else:
            # Opposite-side fill. The flat-only invariant guarantees the
            # booked fill NEVER opened an opposite-side position, so the
            # opening portion is always zero — the whole executed fill was
            # a close against the pre-fill holding.
            closing_qty = min(qty, abs(prev_qty))
            opening_qty = _ZERO
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
        if closing_qty > _ZERO:
            direction = Decimal(1) if prev_qty > _ZERO else Decimal(-1)
            self.realized_pnl += closing_qty * delta * direction

        # 3. avg_price correction for the opening portion. avg's
        #    contribution from this fill is the price × opening_qty
        #    blended into the post-fill total. Recompute post_avg from
        #    the actual price for the opening_qty.
        if opening_qty > _ZERO and post_qty != _ZERO:
            # Closing reduces |prev_qty| toward zero, regardless of
            # which side opened the prior position.
            if closing_qty > _ZERO:
                prev_sign = Decimal(1) if prev_qty > _ZERO else Decimal(-1)
                mid_qty = prev_qty - prev_sign * closing_qty
            else:
                mid_qty = prev_qty
            # Apply the opening portion at actual price.
            opening_signed = opening_qty if signed > _ZERO else -opening_qty
            final_qty = mid_qty + opening_signed
            if final_qty != _ZERO:
                mid_avg = prev_avg if mid_qty != _ZERO else _ZERO
                pos.avg_price = (mid_avg * mid_qty + actual_price * opening_signed) / final_qty
        return True

    # Kept for backwards compatibility — used by older call sites. New
    # code should use apply_reconciled_fill which handles all sign cases.
    def apply_fill_delta(
        self,
        symbol: str,
        side: str,
        qty: float | Decimal,
        delta: float | Decimal,
        broker_order_id: str,
    ) -> bool:
        """DEPRECATED. Forwards to apply_reconciled_fill by deriving the
        mark price. Use apply_reconciled_fill directly."""
        # Reconstruct mark_price from actual_price = mark_price + delta.
        # Without the actual_price we can only invent one — caller must
        # use the new API for correctness; this shim covers fills where
        # delta is exactly 0 (no-op) without breaking the test suite.
        qty = D(qty)
        delta = D(delta)
        if delta == _ZERO:
            already_seen = broker_order_id in self._reconciled_ids
            self._add_reconciled_id(broker_order_id)
            return not already_seen
        # Best-effort for non-zero delta callers that haven't migrated:
        # treat delta as a cash-only correction (the old buggy behavior).
        # Real callers should switch to apply_reconciled_fill.
        if broker_order_id in self._reconciled_ids:
            return False
        self._add_reconciled_id(broker_order_id)
        if side == "buy":
            self.cash -= delta * qty
            pos = self.positions.get(symbol)
            if pos and pos.qty > _ZERO:
                pos.avg_price += delta * qty / pos.qty
        else:
            self.cash += delta * qty
            self.realized_pnl += delta * qty
        return True

    def equity(self, marks: dict[str, float]) -> Decimal:
        """Mark-to-market equity as an exact Decimal.

        ``marks`` arrive as ``float`` market data; they are coerced to
        Decimal here. Callers that emit this on a JSON/WS/REST boundary
        must convert with ``runtime.money.to_float``.
        """
        mtm = sum(
            (p.qty * D(marks[s]) if s in marks else p.qty * p.avg_price)
            for s, p in self.positions.items()
        )
        return self.cash + (mtm if mtm else _ZERO)

    def unrealized_pnl(self, marks: dict[str, float]) -> Decimal:
        """Unrealized P&L as an exact Decimal (float marks in, Decimal out)."""
        total = sum(
            (p.qty * ((D(marks[s]) if s in marks else p.avg_price) - p.avg_price))
            for s, p in self.positions.items()
            if p.qty != _ZERO
        )
        return total if total else _ZERO
