from __future__ import annotations

import re
from datetime import datetime

import structlog
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

from tradefarm.config import settings
from tradefarm.execution.broker import Fill
from tradefarm.market.hours import is_market_open

log = structlog.get_logger()

# client_order_id convention: "agent{agent_id}-{client_tag}"
_AGENT_PREFIX_RE = re.compile(r"^agent(\d+)-")


class AlpacaBroker:
    """Single paper-trading account shared across all agents.

    Order attribution back to an agent is done via client_order_id convention:
    f"agent{agent_id}-{client_tag}".

    NOTE: paper market orders fill async on Alpaca's side. We return a Fill
    optimistically at the provided `mark`; reconciliation against actual
    Alpaca fills happens later (see execution.order_reconciler).
    """

    def __init__(self, allow_extended_hours: bool = False) -> None:
        if not (settings.alpaca_api_key and settings.alpaca_api_secret):
            raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not configured")
        self.client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
            paper="paper-api" in settings.alpaca_base_url,
        )
        # RTH-only gate for now. If someone explicitly opts in to extended hours,
        # we skip the is_market_open() check (the Alpaca order itself still needs
        # to be constructed with extended_hours=True, which we don't do here —
        # this flag is currently a placeholder for future wiring).
        self.allow_extended_hours = allow_extended_hours

    def submit_market(
        self,
        symbol: str,
        side: str,
        qty: float,
        agent_id: int,
        client_tag: str,
        mark: float,
    ) -> Fill | None:
        # RTH-only pre-check. Refuse off-hours unless explicitly allowed.
        if not self.allow_extended_hours and not is_market_open():
            log.info(
                "broker_skip_off_hours",
                symbol=symbol,
                side=side,
                qty=qty,
                agent_id=agent_id,
                client_tag=client_tag,
            )
            return None

        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=f"agent{agent_id}-{client_tag}",
        )
        order = self.client.submit_order(req)
        return Fill(
            symbol=symbol,
            side=side,
            qty=float(qty),
            price=mark,
            broker_order_id=str(order.id),
        )

    def cancel_all(self) -> None:
        self.client.cancel_orders()

    def account(self) -> dict:
        a = self.client.get_account()
        return {
            "equity": float(a.equity),
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "status": str(a.status),
        }

    def get_orders(self, since_iso: str) -> list[dict]:
        """Return recent orders submitted after `since_iso` (ISO-8601 string).

        Used by the reconciler to walk newly-filled Alpaca orders and
        attribute them back to agents via client_order_id.
        """
        after_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        req = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            after=after_dt,
            limit=500,
        )
        orders = self.client.get_orders(filter=req)
        out: list[dict] = []
        for o in orders:
            out.append(
                {
                    "broker_order_id": str(o.id),
                    "client_order_id": o.client_order_id,
                    "symbol": o.symbol,
                    "side": o.side.value if o.side is not None else None,
                    "qty": float(o.qty) if o.qty is not None else None,
                    "filled_qty": float(o.filled_qty) if o.filled_qty else 0.0,
                    "filled_avg_price": (
                        float(o.filled_avg_price) if o.filled_avg_price else None
                    ),
                    "status": o.status.value if o.status is not None else None,
                    "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                    "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                }
            )
        return out

    @staticmethod
    def parse_agent_id(client_order_id: str) -> int | None:
        """Extract the agent id from a client_order_id like 'agent42-deadbeef'.

        Returns None if the prefix doesn't match (e.g. orders placed outside
        this system, or malformed ids).
        """
        if not client_order_id:
            return None
        m = _AGENT_PREFIX_RE.match(client_order_id)
        return int(m.group(1)) if m else None
