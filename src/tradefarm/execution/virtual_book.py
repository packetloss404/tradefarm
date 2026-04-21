"""Per-agent virtual book on top of a shared broker account.

100 agents × $1k can't each hold their own Alpaca account. We pool into one
real paper account, but each agent has an isolated book of positions, cash,
and P&L computed locally. Fills from the real broker get attributed back to
the agent that placed the parent order.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    positions: dict[str, VirtualPosition] = field(default_factory=lambda: defaultdict(lambda: VirtualPosition("")))
    # Broker order ids already reconciled — prevents double-counting on
    # reconciler restart or retry.
    _reconciled_ids: set[str] = field(default_factory=set)

    def record_fill(self, symbol: str, side: str, qty: float, price: float, at: datetime | None = None) -> float:
        """Apply a fill to this book. Returns the realized PnL produced by
        this fill alone (zero for opening fills / same-side adds, non-zero
        for fills that close or flip part/all of a position). The
        book's ``realized_pnl`` running total is updated by the same amount.
        """
        pos = self.positions.get(symbol) or VirtualPosition(symbol)
        self.positions[symbol] = pos
        notional = qty * price
        self.cash += notional if side == "sell" else -notional
        realized = pos.apply_fill(side, qty, price, at=at)
        self.realized_pnl += realized
        return realized

    def apply_fill_delta(
        self,
        symbol: str,
        side: str,
        qty: float,
        delta: float,
        broker_order_id: str,
    ) -> bool:
        """Reconcile the optimistic fill at `mark` with the actual fill at `mark+delta`.

        Positive `delta` = agent paid more (buy) or received more (sell) than recorded.
        Idempotent on `broker_order_id` — duplicate applications are silent no-ops.
        Returns True if applied, False if skipped (already seen).
        """
        if broker_order_id in self._reconciled_ids:
            return False
        self._reconciled_ids.add(broker_order_id)

        if side == "buy":
            # Paid delta*qty more than recorded → cash down by that much.
            self.cash -= delta * qty
            # Correct avg_price for the portion this fill represents. If the
            # position was already closed/flipped since the optimistic fill,
            # the avg_price correction no longer matters.
            pos = self.positions.get(symbol)
            if pos and pos.qty > 0:
                pos.avg_price += delta * qty / pos.qty
        else:  # sell
            # Received delta*qty more than recorded → cash and realized up.
            # (For a partial exit, the closing portion's realized is what
            #  moves; delta*qty still equals the correction on that portion.)
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
