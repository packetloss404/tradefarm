"""Per-agent virtual book on top of a shared broker account.

100 agents × $1k can't each hold their own Alpaca account. We pool into one
real paper account, but each agent has an isolated book of positions, cash,
and P&L computed locally. Fills from the real broker get attributed back to
the agent that placed the parent order.
"""
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class VirtualPosition:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0

    def apply_fill(self, side: str, qty: float, price: float) -> float:
        """Returns realized PnL from this fill."""
        signed = qty if side == "buy" else -qty
        new_qty = self.qty + signed
        realized = 0.0
        if self.qty == 0 or (self.qty > 0) == (signed > 0):
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

    def record_fill(self, symbol: str, side: str, qty: float, price: float) -> None:
        pos = self.positions.get(symbol) or VirtualPosition(symbol)
        self.positions[symbol] = pos
        notional = qty * price
        self.cash += notional if side == "sell" else -notional
        self.realized_pnl += pos.apply_fill(side, qty, price)

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
