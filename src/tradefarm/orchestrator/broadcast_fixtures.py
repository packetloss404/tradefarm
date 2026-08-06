"""Moment-timeline replay fixtures for the Broadcast OS scheduler.

Fixtures are NDJSON files — one ``BroadcastMoment.to_payload()`` per line —
stored in ``tests/fixtures/moments/``. This module loads them into
``BroadcastMoment`` objects and replays them against a fresh
``BroadcastScheduler`` so tests can assert on the resulting slot transitions
without spinning up the live orchestrator.

The win is concrete: tuning ``max_queue_size`` and preemption thresholds goes
from a 5-10 minute live orchestrator loop to a 1-second pytest run.

See ``docs/research/replay-fixtures.md`` for the design rationale and
``tests/fixtures/moments/README.md`` for the per-fixture breakdown.

0.17.0 — WS recording replay helpers. ``load_ws_recording`` reads
a session's recorded NDJSON (the per-frame log written by
``api/ws_recording.py``) into a list of dicts; ``replay_ws_recording``
yields one frame at a time with a configurable tick. These let a
test or a future "replay mode" iterate a recorded session
deterministically without standing up a real orchestrator.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from time import monotonic
from typing import Any

import structlog

from tradefarm.orchestrator.broadcast_os import BroadcastMoment
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler, ScheduledMoment

log = structlog.get_logger()


class FakeClock:
    """A controllable clock for deterministic scheduler tests.

    ``.now`` is the current time. Calling the instance returns ``.now``.
    Tests can advance time by setting ``.now`` directly or by calling
    ``advance(delta)``. Used as the ``clock`` argument to
    ``BroadcastScheduler`` so TTL transitions fire on demand instead of
    waiting for wall-clock seconds.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now: float = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        """Shift ``.now`` forward by ``delta`` seconds."""

        self.now += float(delta)


def load_fixture(
    path: str | Path,
    *,
    max_queue_size: int = 32,
    clock: Callable[[], float] | None = None,
) -> tuple[list[BroadcastMoment], BroadcastScheduler]:
    """Load a moment-timeline fixture from an NDJSON file.

    Returns ``(moments, scheduler)``: the parsed moment list in file order and
    a fresh ``BroadcastScheduler`` wired with the optional injectable clock
    for deterministic TTL transitions. Caller submits the moments in order
    (typically via :func:`replay_against`) and asserts on the slot
    transitions per moment.

    Skips any line that fails to parse as a ``BroadcastMoment`` and logs a
    warning per skipped line so a corrupted fixture is visible in pytest
    output. Blank lines and lines starting with ``#`` are treated as
    comments and ignored. A missing file returns an empty moment list plus a
    fresh scheduler (no raise) so tests can opt into "fixture optional"
    patterns.

    Choice: return order is ``(moments, scheduler)`` (list first) so the
    caller can destructure in submission order. The original design doc
    proposed the opposite order; we kept the more readable one.
    """
    moments: list[BroadcastMoment] = []
    p = Path(path)
    if not p.is_file():
        log.warning("fixture_load_missing", path=str(p))
        return moments, BroadcastScheduler(max_queue_size=max_queue_size, clock=clock or monotonic)
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                payload: dict[str, Any] = json.loads(line)
                moment = BroadcastMoment(**payload)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                log.warning("fixture_load_skipped", path=str(p), line=line_no, error=str(exc))
                continue
            moments.append(moment)
    return moments, BroadcastScheduler(max_queue_size=max_queue_size, clock=clock or monotonic)


def replay_against(
    scheduler: BroadcastScheduler,
    moments: list[BroadcastMoment],
    *,
    tick_sec: float = 1.0,
    clock: Callable[[], float] | None = None,
) -> list[tuple[BroadcastMoment, tuple[ScheduledMoment, ...]]]:
    """Submit each moment against ``scheduler`` with ``tick_sec`` of clock
    advancement between submissions.

    Returns a parallel list of ``(moment, slot_transitions)`` tuples. Tests
    assert on the transitions per moment — that's the unit. The scheduler
    is mutated in place; capture ``scheduler.queued`` /
    ``scheduler.active_slots`` afterwards for end-state assertions.

    The ``clock`` parameter seeds the base time (defaults to wall-clock
    ``monotonic``). The per-moment ``now`` is computed as
    ``base + i * tick_sec`` and passed explicitly to
    ``scheduler.submit_slots`` so submission times are deterministic
    regardless of how slow the test machine is.
    """
    transitions: list[tuple[BroadcastMoment, tuple[ScheduledMoment, ...]]] = []
    cur_clock = clock or monotonic
    base = cur_clock()
    for i, moment in enumerate(moments):
        now = base + (i * float(tick_sec))
        slots = scheduler.submit_slots(moment, now=now)
        transitions.append((moment, slots))
    return transitions


# ---------------------------------------------------------------------------
# 0.17.0 — WS recording replay helpers.
#
# A WS recording is an NDJSON file with one frame per line, written
# by `tradefarm.api.ws_recording.WsRecorder`. The frame shape is::
#
#     {"ts": iso, "session": sid, "direction": "in"|"out",
#      "type": ev_type, "payload": {...}}
#
# `load_ws_recording` parses the file into a list of those dicts
# (skipping corrupted lines, the same way `load_fixture` does).
# `replay_ws_recording` yields them one at a time with a configurable
# wall-clock tick — letting a test or a future "replay mode" iterate
# a recorded session deterministically.
# ---------------------------------------------------------------------------


def load_ws_recording(path: str | Path) -> list[dict[str, Any]]:
    """Load a WS recording NDJSON into a list of frame dicts.

    Each returned dict has the shape ``{ts, session, direction, type,
    payload}`` matching the recorder's on-disk format. Blank lines
    and lines starting with ``#`` are treated as comments. A
    corrupted JSON line is logged and skipped (matching
    ``load_fixture``'s NDJSON resilience contract). A missing file
    returns an empty list (no raise) so callers can opt into
    "fixture optional" patterns.

    The list is in file order — the recorder appends, so the
    ordering is monotonic by the recording clock (with the usual
    caveat that concurrent WS subscribers may interleave slightly
    out of order; ``replay_ws_recording`` uses a flat tick, not the
    inter-frame delta).
    """
    out: list[dict[str, Any]] = []
    p = Path(path)
    if not p.is_file():
        log.warning("ws_recording_load_missing", path=str(p))
        return out
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                frame: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(
                    "ws_recording_load_skipped", path=str(p), line=line_no, error=str(exc)
                )
                continue
            out.append(frame)
    return out


def replay_ws_recording(
    frames: list[dict[str, Any]],
    *,
    tick_sec: float = 0.05,
    sleeper: Callable[[float], None] | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield one recorded frame at a time, ``tick_sec`` apart.

    The first frame is yielded immediately; subsequent frames sleep
    for ``tick_sec`` seconds (default 0.05 — a 20Hz pump, matching
    the live ``auto_tick_interval_sec`` of 0.5 / 10 ticks per
    second for the dashboard's most-zoomed view). ``tick_sec <= 0``
    collapses the sleep entirely and yields frames as fast as the
    consumer drains them (useful in tests).

    A test that wants deterministic timing can pass ``sleeper`` to
    inject a fake clock (e.g. a function that bumps a ``FakeClock``
    instead of calling ``time.sleep``). The default sleeper is
    ``time.sleep`` which is monotonic and respects OS scheduling.

    Why yield instead of returning a list? Because the live replay
    case (a future "play this recording" mode in the stream app)
    wants frame-by-frame streaming; a generator is the right shape
    even though our tests only iterate it once.
    """
    sleep = sleeper if sleeper is not None else time.sleep
    delay = max(0.0, float(tick_sec))
    it: Iterator[dict[str, Any]] = iter(frames)
    try:
        first = next(it)
    except StopIteration:
        return
    yield first
    for frame in it:
        if delay > 0:
            sleep(delay)
        yield frame
