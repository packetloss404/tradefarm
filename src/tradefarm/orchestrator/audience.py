"""Audience interactivity coordinator — sentiment + pin requests.

Wired into the YouTube chat poller via :meth:`AudienceCoordinator.on_chat_message`;
each incoming chat payload is parsed for commands and routed to the right
sub-system:

- ``!vote up|down``    → sentiment aggregator (rolling 5-minute window)
- ``!pin <agent>``     → pin-request queue (operator-approved spotlight)
- ``!pick <agent>``    → predictions board ("today's winner")
- ``!spy up|down``     → predictions board ("SPY close direction")

Sentiment heartbeats are emitted every 10s (or sooner, debounced to at most
1 publish/sec, whenever votes change the score). Pin requests publish a single
``audience_pin_request`` event on arrival and an ``audience_pin_resolved``
event when the operator approves or rejects.

State is in-memory only — predictions and sentiment are lost on backend
restart. That's an explicit v1 choice (a single-day broadcast).
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Deque

import structlog

from tradefarm.api.events import publish_event
from tradefarm.orchestrator.chat_commands import (
    PickCommand,
    PinCommand,
    SpyCommand,
    VoteCommand,
    parse_command,
)

if TYPE_CHECKING:
    from tradefarm.orchestrator.predictions import PredictionsBoard
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()

# Rolling sentiment window — votes older than this stop counting.
SENTIMENT_WINDOW = timedelta(minutes=5)

# At most one sentiment publish per second (debounce). The background loop
# additionally emits a heartbeat at this cadence so dashboards see a fresh
# value even when chat is silent.
SENTIMENT_DEBOUNCE_SEC: float = 1.0
SENTIMENT_HEARTBEAT_SEC: float = 10.0

# Hard cap on pending pin requests (oldest evicted past this).
PIN_QUEUE_CAP: int = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Vote:
    """A single ``!vote`` event in the rolling sentiment window."""

    direction: str  # "up" | "down"
    at: datetime


@dataclass
class _PinRequest:
    """A pending ``!pin <agent>`` request awaiting operator approval."""

    id: str
    requester: str
    agent_id: int | None
    agent_name_query: str
    requested_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requester": self.requester,
            "agent_id": self.agent_id,
            "agent_name_query": self.agent_name_query,
            "requested_at": self.requested_at.isoformat(),
        }


@dataclass
class AudienceCoordinator:
    """Routes chat commands and emits audience-driven WS events.

    Owns:
    - A rolling 5-minute deque of votes (sentiment).
    - A capped FIFO of pending pin requests.
    - A reference to the orchestrator (for agent name → id resolution and
      for forwarding pin approvals to ``stream_scene``).
    - An optional :class:`PredictionsBoard` for ``!pick`` / ``!spy`` routing.

    The background ``_run`` loop is the heartbeat publisher; chat-driven
    publishes happen synchronously inside :meth:`on_chat_message` /
    :meth:`approve_pin_request` / :meth:`reject_pin_request`.
    """

    orch: "Orchestrator"
    predictions: "PredictionsBoard | None" = None
    heartbeat_sec: float = SENTIMENT_HEARTBEAT_SEC
    debounce_sec: float = SENTIMENT_DEBOUNCE_SEC
    window: timedelta = SENTIMENT_WINDOW
    queue_cap: int = PIN_QUEUE_CAP

    _votes: Deque[_Vote] = field(default_factory=deque, init=False, repr=False)
    _pin_requests: Deque[_PinRequest] = field(default_factory=deque, init=False, repr=False)
    _pin_by_id: dict[str, _PinRequest] = field(default_factory=dict, init=False, repr=False)
    _last_sentiment_publish: datetime | None = field(default=None, init=False, repr=False)
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Lifecycle.
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background heartbeat loop. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="orch_audience")
        log.info("audience_started", heartbeat_sec=self.heartbeat_sec)

    async def stop(self) -> None:
        """Cancel the heartbeat loop and await its exit."""
        self._stopped = True
        t = self._task
        if t is None:
            return
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                await self._publish_sentiment(force=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("audience_heartbeat_failed", error=str(e))
            await asyncio.sleep(self.heartbeat_sec)

    # ------------------------------------------------------------------
    # Chat ingestion entry point.
    # ------------------------------------------------------------------

    async def on_chat_message(self, payload: dict[str, Any]) -> None:
        """Route a single chat-message payload through the command parser.

        The payload shape matches the YouTube poller's ``chat_message`` event:
        ``{id, user, text, color, source, at}``. Non-command messages are
        silently ignored — the parser returns ``None`` for those.
        """
        text = payload.get("text")
        user = payload.get("user") or "anonymous"
        if not isinstance(text, str):
            return
        cmd = parse_command(text)
        if cmd is None:
            return
        if isinstance(cmd, VoteCommand):
            await self._handle_vote(cmd)
        elif isinstance(cmd, PinCommand):
            await self._handle_pin(cmd, requester=str(user))
        elif isinstance(cmd, PickCommand):
            await self._handle_pick(cmd, voter=str(user))
        elif isinstance(cmd, SpyCommand):
            await self._handle_spy(cmd, voter=str(user))
        # UnknownCommand: deliberately silent — chat is full of typos.

    # ------------------------------------------------------------------
    # Sentiment aggregator.
    # ------------------------------------------------------------------

    async def _handle_vote(self, cmd: VoteCommand) -> None:
        now = _utcnow()
        self._votes.append(_Vote(direction=cmd.direction, at=now))
        self._evict_expired(now)
        await self._publish_sentiment(force=False)

    def _evict_expired(self, now: datetime) -> None:
        cutoff = now - self.window
        while self._votes and self._votes[0].at < cutoff:
            self._votes.popleft()

    def sentiment_snapshot(self) -> dict[str, Any]:
        """Return the current sentiment payload (used by tests + heartbeat)."""
        now = _utcnow()
        self._evict_expired(now)
        up = sum(1 for v in self._votes if v.direction == "up")
        down = sum(1 for v in self._votes if v.direction == "down")
        total = up + down
        score = (up - down) / total if total > 0 else 0.0
        return {
            "score": score,
            "up": up,
            "down": down,
            "window_sec": int(self.window.total_seconds()),
        }

    async def _publish_sentiment(self, *, force: bool) -> None:
        """Publish the sentiment payload, honoring the debounce.

        ``force=True`` bypasses the debounce — used by the heartbeat loop.
        """
        now = _utcnow()
        if not force and self._last_sentiment_publish is not None:
            elapsed = (now - self._last_sentiment_publish).total_seconds()
            if elapsed < self.debounce_sec:
                return
        payload = self.sentiment_snapshot()
        self._last_sentiment_publish = now
        await publish_event("audience_sentiment", payload)

    # ------------------------------------------------------------------
    # Pin requests.
    # ------------------------------------------------------------------

    async def _handle_pin(self, cmd: PinCommand, *, requester: str) -> None:
        agent_id = self._resolve_agent_query(cmd.agent_query)
        req = _PinRequest(
            id=uuid.uuid4().hex[:12],
            requester=requester,
            agent_id=agent_id,
            agent_name_query=cmd.agent_query,
            requested_at=_utcnow(),
        )
        # Evict the oldest if we're at cap.
        while len(self._pin_requests) >= self.queue_cap:
            dropped = self._pin_requests.popleft()
            self._pin_by_id.pop(dropped.id, None)
        self._pin_requests.append(req)
        self._pin_by_id[req.id] = req
        await publish_event("audience_pin_request", req.to_payload())
        log.info(
            "audience_pin_request",
            id=req.id,
            requester=req.requester,
            agent_id=req.agent_id,
            agent_name_query=req.agent_name_query,
        )

    def _resolve_agent_query(self, query: str) -> int | None:
        """Resolve an agent query string to an agent_id.

        Supported forms:
        - Bare integer string ("42") — matches ``agent.state.id``.
        - Substring match against ``agent.state.name`` (case-insensitive,
          first match wins).

        Returns ``None`` if nothing matches.
        """
        q = query.strip()
        if not q:
            return None
        # Try id-as-string first.
        try:
            as_int = int(q)
        except ValueError:
            as_int = None
        if as_int is not None:
            for a in self.orch.agents:
                if a.state.id == as_int:
                    return as_int
        # Fall back to case-insensitive name substring.
        needle = q.lower()
        for a in self.orch.agents:
            if needle in a.state.name.lower():
                return a.state.id
        return None

    def pending_requests(self) -> list[dict[str, Any]]:
        """Return all pending pin requests, newest first."""
        return [r.to_payload() for r in reversed(self._pin_requests)]

    async def approve_pin_request(
        self, request_id: str, agent_id_override: int | None = None,
    ) -> bool:
        """Approve a pending pin request.

        ``agent_id_override`` lets the operator manually resolve a request
        whose original ``agent_query`` didn't match any agent. The override
        wins over the queue's stored ``agent_id`` when provided.

        Side effects (only on success):
        - Removes the request from the queue.
        - Publishes ``audience_pin_resolved`` with ``status="approved"``.
        - Publishes ``stream_scene`` with ``pin_agent_id`` so the broadcast
          app spotlights the chosen agent (skipped when neither the request
          nor the override resolves to an agent).
        """
        req = self._pop_request(request_id)
        if req is None:
            return False
        resolved = agent_id_override if agent_id_override is not None else req.agent_id
        await publish_event(
            "audience_pin_resolved",
            {"id": req.id, "status": "approved", "agent_id": resolved},
        )
        if resolved is not None:
            await publish_event(
                "stream_scene",
                {"pin_agent_id": resolved},
            )
        log.info(
            "audience_pin_approved",
            id=req.id,
            agent_id=resolved,
            via_override=agent_id_override is not None,
        )
        return True

    async def reject_pin_request(self, request_id: str) -> bool:
        """Reject a pending pin request.

        Returns ``True`` on success, ``False`` for unknown ids.
        """
        req = self._pop_request(request_id)
        if req is None:
            return False
        await publish_event(
            "audience_pin_resolved",
            {"id": req.id, "status": "rejected", "agent_id": req.agent_id},
        )
        log.info("audience_pin_rejected", id=req.id, agent_id=req.agent_id)
        return True

    def _pop_request(self, request_id: str) -> _PinRequest | None:
        req = self._pin_by_id.pop(request_id, None)
        if req is None:
            return None
        # Rebuild the deque without the popped element (O(N) on a 20-cap
        # deque — fine).
        self._pin_requests = deque(r for r in self._pin_requests if r.id != request_id)
        return req

    # ------------------------------------------------------------------
    # Prediction routing — delegated to PredictionsBoard.
    # ------------------------------------------------------------------

    async def _handle_pick(self, cmd: PickCommand, *, voter: str) -> None:
        if self.predictions is None:
            return
        await self.predictions.record_vote("pick-winner", voter, cmd.agent_query)

    async def _handle_spy(self, cmd: SpyCommand, *, voter: str) -> None:
        if self.predictions is None:
            return
        await self.predictions.record_vote("spy-direction", voter, cmd.direction)
