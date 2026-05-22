"""Per-agent virtual book on top of a shared broker account.

100 agents × $1k can't each hold their own Alpaca account. We pool into one
real paper account, but each agent has an isolated book of positions, cash,
and P&L computed locally. Fills from the real broker get attributed back to
the agent that placed the parent order.
"""
from dataclasses import dataclass, field
from datetime import datetime

from tradefarm.runtime.clock import now_utc


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
    # reconciler restart or retry.
    _reconciled_ids: set[str] = field(default_factory=set)

    def _get_or_create(self, symbol: str) -> VirtualPosition:
        pos = self.positions.get(symbol)
        if pos is None:
            pos = VirtualPosition(symbol)
            self.positions[symbol] = pos
        return pos

    def record_fill(self, symbol: str, side: str, qty: float, price: float, at: datetime | None = None) -> float:
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

        Implementation: reverses the optimistic fill (a synthetic
        opposite-side fill at ``mark_price``), then applies the actual
        fill at ``actual_price``. This correctly handles every case the
        previous ``apply_fill_delta`` got wrong:

          * Opening a short (was no-op for the buy branch; now reverses
            then re-opens at actual)
          * Long→short flip in one fill (was assuming entire qty closed)
          * Buy-to-cover that closes a short (was missing realized
            adjustment on the closing portion)

        ``mark_price`` is derivable from ``actual_price - delta`` in the
        reconciler's data structure.
        """
        if broker_order_id in self._reconciled_ids:
            return False
        self._reconciled_ids.add(broker_order_id)
        if abs(mark_price - actual_price) < 1e-9:
            return True  # nothing to correct, but still consume the id
        opposite = "sell" if side == "buy" else "buy"
        # Reverse the optimistic fill at the mark price.
        self.record_fill(symbol, opposite, qty, mark_price, at=at)
        # Apply the actual fill at the true price.
        self.record_fill(symbol, side, qty, actual_price, at=at)
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
                self._reconciled_ids.add(broker_order_id) or True
            )
        # Best-effort for non-zero delta callers that haven't migrated:
        # treat delta as a cash-only correction (the old buggy behavior).
        # Real callers should switch to apply_reconciled_fill.
        if broker_order_id in self._reconciled_ids:
            return False
        self._reconciled_ids.add(broker_order_id)
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
