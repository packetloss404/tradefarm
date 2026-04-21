from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Fill:
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    price: float
    broker_order_id: str = ""


class Broker(Protocol):
    def submit_market(
        self,
        symbol: str,
        side: str,
        qty: float,
        agent_id: int,
        client_tag: str,
        mark: float,
    ) -> Fill | None:
        ...


class SimulatedBroker:
    """Synchronous self-fill at the provided mark price. Zero cost, zero latency.

    Used for offline strategy iteration and tests."""

    def submit_market(
        self,
        symbol: str,
        side: str,
        qty: float,
        agent_id: int,
        client_tag: str,
        mark: float,
    ) -> Fill | None:
        return Fill(symbol=symbol, side=side, qty=qty, price=mark, broker_order_id=f"sim-{client_tag}")
