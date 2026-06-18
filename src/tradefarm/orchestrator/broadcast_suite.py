"""BroadcastSuite — the orchestrator's presentation/interactivity layer.

Extracted from the ``Orchestrator`` god-object (issue #6). The suite OWNS every
always-on presentation sidecar that used to live as a separate field on the
orchestrator:

- ``AutoDirector``    — auto-fires broadcast moments from agent/market state
- ``StreakWatcher``   — broadcasts macros from trade-history patterns
- ``CommentaryLoop``  — Bloomberg-style LLM one-liner every ~45s
- ``YouTubeChatPoller`` — surfaces real audience chat onto the WS bus
- ``PredictionsBoard`` — audience prediction rounds
- ``AudienceCoordinator`` — sentiment + pins + predictions wiring

plus the broadcast recap ledger + slot scheduler (installed as the module-global
arbiter while the suite is running).

The orchestrator keeps a single ``self._broadcast_suite`` and calls
``start()`` / ``stop()`` on it as a unit. Behavior is identical to the prior
inline implementation:

* arbiter is installed on ``start()`` (not at construction), so unit tests that
  build a bare orchestrator don't pollute the module globals;
* dependency order on start — predictions is constructed *before* the audience
  coordinator so the latter can link to it;
* teardown order on stop — sidecars are drained first (they may still emit
  moments during ``stop()``), then the arbiter is uninstalled last so those
  in-flight moments still route through the ledger/scheduler;
* each sidecar's ``start()`` is awaited (not fire-and-forget) so a boot-time
  failure surfaces instead of being swallowed by a discarded ``create_task``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, TypeVar

import structlog

from tradefarm.orchestrator.audience import AudienceCoordinator
from tradefarm.orchestrator.auto_director import AutoDirector
from tradefarm.orchestrator.broadcast_recap import BroadcastRecapLedger
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler
from tradefarm.orchestrator.commentary_loop import CommentaryLoop
from tradefarm.orchestrator.predictions import PredictionsBoard
from tradefarm.orchestrator.streak_watcher import StreakWatcher
from tradefarm.orchestrator.youtube_chat import YouTubeChatPoller

if TYPE_CHECKING:
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()


class _Sidecar(Protocol):
    """Minimal contract for an always-on background coordinator.

    Every sidecar's ``start()`` is a short coroutine that kicks off its own
    internal loop task and returns; awaiting it surfaces any boot-time
    exception instead of stranding it on a discarded ``create_task``.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


_SidecarT = TypeVar("_SidecarT", bound=_Sidecar)


def attach_crash_logger(task: asyncio.Task, *, name: str) -> asyncio.Task:
    """Attach a done-callback that logs a hard loop crash.

    Issue #6 (low-severity nit): each sidecar's inner ``self._run()`` task is
    spawned fire-and-forget. Without an observer, a crash (rather than a clean
    cancel) surfaces only as a bare "Task exception was never retrieved" warning
    at GC time, with no structured context. This callback logs
    ``background_loop_crashed`` for any non-cancel exception so the failure is
    attributable. Shared so every loop task the suite owns is supervised
    identically.
    """

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("background_loop_crashed", name=name, error=str(exc))

    task.add_done_callback(_on_done)
    return task


class BroadcastSuite:
    """Owns the presentation sidecars + the broadcast arbiter as a unit."""

    def __init__(self, orch: "Orchestrator") -> None:
        self._orch = orch
        # Broadcast recap ledger + slot scheduler. Constructed here but only
        # INSTALLED as module globals when start() runs (see Orchestrator
        # audit fix C15 — installing at construction polluted test globals).
        self.ledger = BroadcastRecapLedger()
        self.scheduler = BroadcastScheduler()
        # Presentation/interactivity sidecars (None until start()).
        self.auto_director: AutoDirector | None = None
        self.streak_watcher: StreakWatcher | None = None
        self.commentary_loop: CommentaryLoop | None = None
        self.youtube_chat: YouTubeChatPoller | None = None
        self.predictions: PredictionsBoard | None = None
        self.audience: AudienceCoordinator | None = None

    async def _start_sidecar(
        self,
        current: _SidecarT | None,
        factory: Callable[[], _SidecarT],
    ) -> _SidecarT:
        """Construct (if absent) and start one always-on sidecar.

        Issue #6: each ``start()`` is AWAITED directly rather than wrapped in
        a discarded ``asyncio.create_task``. The old pattern swallowed any
        exception raised before the sidecar's inner loop spawned ("Task
        exception was never retrieved") and left that sidecar silently dead;
        awaiting lets the error propagate out of ``start()`` at boot.
        ``start()`` itself only kicks off the internal loop task, so awaiting
        does not block on the loop body.
        """
        if current is not None:
            return current
        sidecar = factory()
        await sidecar.start()
        return sidecar

    async def start(self) -> None:
        """Install the arbiter and start every sidecar as a unit. Idempotent.

        Predictions is constructed before the audience coordinator so the
        latter can link to it.
        """
        # Audit fix (Q): install the broadcast arbiter here (not at
        # construction) so unit tests that build a bare suite/orchestrator
        # don't silently pollute the module-global state.
        from tradefarm.orchestrator import broadcast_os as _bos

        _bos.install_broadcast_arbiter(self.ledger, self.scheduler)

        orch = self._orch
        self.auto_director = await self._start_sidecar(
            self.auto_director, lambda: AutoDirector(orch=orch)
        )
        self.streak_watcher = await self._start_sidecar(
            self.streak_watcher, lambda: StreakWatcher(orch=orch)
        )
        self.commentary_loop = await self._start_sidecar(
            self.commentary_loop, lambda: CommentaryLoop(orch=orch)
        )
        # YouTube Live Chat poller — always constructed; the poller itself
        # checks ``settings.youtube_chat_enabled`` and stays dormant when off.
        self.youtube_chat = await self._start_sidecar(
            self.youtube_chat, lambda: YouTubeChatPoller(orch=orch)
        )
        # Audience predictions board — depends on agent list being final.
        self.predictions = await self._start_sidecar(
            self.predictions, lambda: PredictionsBoard(orch=orch)
        )
        # Audience coordinator — wires chat commands into sentiment + pins
        # + predictions. Built AFTER predictions so the link is in place.
        self.audience = await self._start_sidecar(
            self.audience,
            lambda: AudienceCoordinator(orch=orch, predictions=self.predictions),
        )

    async def stop(self) -> None:
        """Drain every sidecar then uninstall the arbiter. Idempotent.

        Each coordinator may still emit broadcast moments during its
        ``stop()`` (e.g. a "stream offline" banner). Those need the arbiter to
        still be installed, so the arbiter is uninstalled LAST — symmetric to
        ``start()``.
        """
        if self.auto_director is not None:
            await self.auto_director.stop()
            self.auto_director = None
        if self.streak_watcher is not None:
            await self.streak_watcher.stop()
            self.streak_watcher = None
        if self.commentary_loop is not None:
            await self.commentary_loop.stop()
            self.commentary_loop = None
        if self.youtube_chat is not None:
            await self.youtube_chat.stop()
            self.youtube_chat = None
        if self.audience is not None:
            await self.audience.stop()
            self.audience = None
        if self.predictions is not None:
            await self.predictions.stop()
            self.predictions = None

        # Audit fix (round 3 U): uninstall the broadcast arbiter AFTER every
        # sidecar has stopped. Uninstalling first would mean in-flight
        # ``publish_broadcast_moment`` calls during stop() bypass the
        # ledger/scheduler. Symmetric to start().
        from tradefarm.orchestrator import broadcast_os as _bos

        _bos.install_broadcast_arbiter(None, None)
