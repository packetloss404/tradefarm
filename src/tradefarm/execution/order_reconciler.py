from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog

from tradefarm.execution.alpaca_broker import AlpacaBroker

log = structlog.get_logger()


@dataclass
class ReconciledFill:
    """A single agent-attributed actual fill from Alpaca.

    `delta` is the per-share price difference vs the optimistic mark the
    scheduler already recorded: positive means the agent paid more than
    expected on a buy (or received more than expected on a sell).
    The virtual book should apply `delta * qty` as a cash adjustment
    (signed appropriately by side).
    """

    agent_id: int
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    delta: float  # actual_fill_price - optimistic_mark
    broker_order_id: str
    client_order_id: str
    actual_price: float
    filled_at: str


class OrderReconciler:
    """Poll Alpaca for recently-filled orders, attribute them to agents via
    client_order_id, and surface the price delta vs the optimistic mark.

    Usage pattern:

        recon = OrderReconciler(broker, optimistic_marks)
        asyncio.create_task(recon.run(interval_sec=10))

    where `optimistic_marks` is a per-order-id mapping the scheduler is
    expected to populate at submit time (client_order_id -> optimistic mark
    price used when the scheduler already applied the fill locally).

    RESTART BEHAVIOR / KNOWN GAP: last_poll_ts is held in memory only. On
    process restart we re-initialise to `now - startup_lookback_sec` which
    means fills that happened more than `startup_lookback_sec` before
    restart will be silently missed. Fills that completed between the
    scheduler's last local write and the restart will be re-emitted as
    deltas; the virtual book's apply method should be idempotent on
    broker_order_id to prevent double-counting. A persistent
    last_poll_ts (DB column) is the proper fix; out of scope here.
    """

    def __init__(
        self,
        broker: AlpacaBroker,
        optimistic_marks: dict[str, float],
        startup_lookback_sec: int = 300,
    ) -> None:
        self.broker = broker
        # Shared dict: the scheduler writes client_order_id -> mark at submit
        # time; we read (and pop) it here after we've produced a delta.
        self.optimistic_marks = optimistic_marks
        self._last_poll_ts: datetime = datetime.now(timezone.utc) - timedelta(
            seconds=startup_lookback_sec
        )
        self._seen_order_ids: set[str] = set()
        self._task: asyncio.Task | None = None

    def poll_once(self) -> list[ReconciledFill]:
        """One reconciliation pass. Returns new ReconciledFill records."""
        since_iso = self._last_poll_ts.isoformat()
        try:
            orders = self.broker.get_orders(since_iso)
        except Exception as e:
            log.warning("reconcile_fetch_failed", error=str(e))
            return []

        out: list[ReconciledFill] = []
        newest_seen = self._last_poll_ts
        for o in orders:
            submitted_at = o.get("submitted_at")
            if submitted_at:
                try:
                    ts = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
                    if ts > newest_seen:
                        newest_seen = ts
                except ValueError:
                    pass

            if o["status"] != "filled":
                continue
            broker_oid = o["broker_order_id"]
            if broker_oid in self._seen_order_ids:
                continue

            coid = o["client_order_id"] or ""
            agent_id = self.broker.parse_agent_id(coid)
            if agent_id is None:
                # Not one of ours (external order, or manual trade).
                self._seen_order_ids.add(broker_oid)
                continue

            actual = o["filled_avg_price"]
            if actual is None:
                continue  # paper sometimes reports 0/None pre-settle; retry later
            mark = self.optimistic_marks.pop(coid, None)
            if mark is None:
                # Scheduler didn't register a mark for this coid (restart gap,
                # or order placed out-of-band). Skip silently — nothing to delta.
                self._seen_order_ids.add(broker_oid)
                continue

            out.append(
                ReconciledFill(
                    agent_id=agent_id,
                    symbol=o["symbol"],
                    side=o["side"],
                    qty=float(o["filled_qty"]),
                    delta=float(actual) - float(mark),
                    broker_order_id=broker_oid,
                    client_order_id=coid,
                    actual_price=float(actual),
                    filled_at=o.get("filled_at") or "",
                )
            )
            self._seen_order_ids.add(broker_oid)

        self._last_poll_ts = newest_seen
        return out

    async def run(self, interval_sec: int = 10) -> None:
        log.info("reconciler_started", interval_sec=interval_sec)
        while True:
            try:
                fills = self.poll_once()
                if fills:
                    log.info("reconciler_deltas", count=len(fills))
                    for f in fills:
                        log.info(
                            "reconciled_fill",
                            agent_id=f.agent_id,
                            sym=f.symbol,
                            side=f.side,
                            qty=f.qty,
                            delta=f.delta,
                            actual=f.actual_price,
                        )
            except Exception as e:
                log.exception("reconciler_tick_failed", error=str(e))
            await asyncio.sleep(interval_sec)
