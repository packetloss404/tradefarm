"""Broadcast OS primitives.

This module is the small producer/director layer between TradeFarm's raw
orchestrator events and the stream presentation surfaces. It emits one
canonical ``broadcast_moment`` event, then fans out to legacy stream events
that today's frontend already understands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from tradefarm.api.events import publish_event

BroadcastColor = Literal["profit", "loss", "neutral"]
BroadcastKind = Literal[
    "agent_pnl",
    "market_move",
    "rank_change",
    "streak",
    "day_leader",
    "activity",
    "commentary",
]
BroadcastOutput = Literal[
    "macro_burst",
    "lower_third",
    "ticker",
    "recap_log",
    "audio",
]
PublishEvent = Callable[[str, dict[str, Any]], Awaitable[None]]

DEFAULT_OUTPUTS: tuple[BroadcastOutput, ...] = ("macro_burst", "ticker", "recap_log")

KIND_BY_TRIGGER: dict[str, BroadcastKind] = {
    "big_win": "agent_pnl",
    "crash": "agent_pnl",
    "market_surge": "market_move",
    "market_crash": "market_move",
    "promotion": "rank_change",
    "fill_of_tick": "activity",
    "win_streak": "streak",
    "loss_streak": "streak",
    "awake": "activity",
    "bigwin_day": "day_leader",
    "bigloss_day": "day_leader",
}

PRIORITY_BY_TRIGGER: dict[str, int] = {
    "promotion": 90,
    "big_win": 78,
    "crash": 78,
    "bigwin_day": 74,
    "bigloss_day": 74,
    "market_surge": 70,
    "market_crash": 70,
    "fill_of_tick": 62,
    "win_streak": 64,
    "loss_streak": 64,
    "awake": 52,
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_priority(priority: int) -> int:
    return max(0, min(100, int(priority)))


@dataclass(frozen=True)
class BroadcastMoment:
    """Canonical unit of stream-worthy presentation.

    ``title`` and ``subtitle`` are audience-facing copy. ``trigger`` is the
    machine-facing detector name. ``outputs`` says which presentation adapters
    should react now; long-lived consumers can also store every canonical
    ``broadcast_moment`` for recaps and tuning.
    """

    id: str
    kind: BroadcastKind
    title: str
    subtitle: str | None = None
    priority: int = 50
    color: BroadcastColor = "neutral"
    agent_id: int | None = None
    trigger: str | None = None
    outputs: tuple[BroadcastOutput, ...] = DEFAULT_OUTPUTS
    ttl_sec: int = 8
    created_at: str = field(default_factory=_utcnow_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "priority": _clamp_priority(self.priority),
            "color": self.color,
            "outputs": list(self.outputs),
            "ttl_sec": max(1, int(self.ttl_sec)),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
        if self.subtitle:
            payload["subtitle"] = self.subtitle
        if self.agent_id is not None:
            payload["agent_id"] = self.agent_id
        if self.trigger:
            payload["trigger"] = self.trigger
        return payload

    def to_macro_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.title,
            "color": self.color,
        }
        if self.subtitle:
            payload["subtitle"] = self.subtitle
        return payload

    def to_banner_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": self.title,
            "ttl_sec": max(1, int(self.ttl_sec)),
        }
        if self.subtitle:
            payload["subtitle"] = self.subtitle
        return payload


def moment_from_macro(
    macro: dict[str, Any],
    *,
    default_kind: BroadcastKind = "activity",
    outputs: tuple[BroadcastOutput, ...] = DEFAULT_OUTPUTS,
) -> BroadcastMoment:
    """Translate an existing macro dict into a canonical broadcast moment."""

    trigger = str(macro.get("trigger") or "")
    kind = KIND_BY_TRIGGER.get(trigger, default_kind)
    priority = PRIORITY_BY_TRIGGER.get(trigger, 50)
    color: BroadcastColor = "neutral"
    raw_color = macro.get("color")
    if raw_color in ("profit", "loss", "neutral"):
        color = raw_color
    agent_id = macro.get("agent_id")
    if not isinstance(agent_id, int):
        agent_id = None
    title = str(macro.get("label") or macro.get("title") or macro.get("id") or "Broadcast moment")
    subtitle_raw = macro.get("subtitle")
    subtitle = str(subtitle_raw) if subtitle_raw is not None else None

    metadata: dict[str, Any] = {}
    for key in ("symbol", "pct", "pnl", "source"):
        if key in macro:
            metadata[key] = macro[key]

    return BroadcastMoment(
        id=str(macro["id"]),
        kind=kind,
        title=title,
        subtitle=subtitle,
        priority=priority,
        color=color,
        agent_id=agent_id,
        trigger=trigger or None,
        outputs=outputs,
        metadata=metadata,
    )


# Audit fix (C15): module-level ledger + scheduler so every producer
# automatically gets recap-history + slot-arbitration without each one
# having to plumb them in. The Orchestrator wires its own instances at
# boot (see _broadcast_ledger / _broadcast_scheduler attrs) and routes
# moments through here; if the caller forgot to install them, fall
# back to the legacy direct-publish path so today's behavior is
# preserved.
_broadcast_ledger: "Any | None" = None
_broadcast_scheduler: "Any | None" = None


def install_broadcast_arbiter(ledger: Any | None, scheduler: Any | None) -> None:
    """Called by Orchestrator.start_background to register the ledger
    + slot scheduler. Pass None for both to uninstall (Orchestrator.
    stop_background does this so the next publish_broadcast_moment
    falls back to the legacy direct-publish path).

    Subsequent publish_broadcast_moment calls route through the
    installed arbiter, recording recap history + multiplexing onto
    UI output slots."""
    global _broadcast_ledger, _broadcast_scheduler
    _broadcast_ledger = ledger
    _broadcast_scheduler = scheduler


def get_broadcast_ledger() -> Any | None:
    return _broadcast_ledger


def get_broadcast_scheduler() -> Any | None:
    return _broadcast_scheduler


async def publish_broadcast_moment(
    moment: BroadcastMoment,
    *,
    publish: PublishEvent = publish_event,
    emit_legacy: bool = True,
) -> None:
    """Publish a canonical moment and any current frontend adapter events.

    ``broadcast_moment`` is the source-of-truth event. The legacy fan-out keeps
    the existing stream app alive while it migrates from ad-hoc macro events to
    the broadcast OS contract.

    Audit fix (C15): if a ledger + scheduler have been installed via
    install_broadcast_arbiter(), the moment is recorded for recap and
    arbitrated against in-flight UI slots — multiple producers can no
    longer trample the same output. Without the arbiter installed,
    behavior matches the legacy direct-publish path.
    """

    if _broadcast_ledger is not None:
        try:
            _broadcast_ledger.record(moment)
        except Exception:
            pass
    if _broadcast_scheduler is not None:
        try:
            scheduled = _broadcast_scheduler.submit_slots(moment)
        except Exception:
            scheduled = ()
        # The scheduler tells us, per moment, whether it went live, was
        # queued behind a higher-priority slot, or got preempted. Fan each
        # out as a `broadcast_slot` event so the dashboard's queue/preemption
        # indicator reflects reality. Always publish the canonical moment too.
        for sm in scheduled:
            try:
                await publish(
                    "broadcast_slot",
                    {
                        "moment_id": sm.moment.id,
                        "kind": sm.moment.kind,
                        "outputs": list(sm.moment.outputs),
                        "state": sm.state,
                    },
                )
            except Exception:
                pass

    await publish("broadcast_moment", moment.to_payload())
    if not emit_legacy:
        return
    if "macro_burst" in moment.outputs:
        await publish("stream_macro_fired", moment.to_macro_payload())
    if "lower_third" in moment.outputs:
        await publish("stream_banner", moment.to_banner_payload())
