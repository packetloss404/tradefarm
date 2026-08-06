"""Tests for the BroadcastSuite extraction (issue #6).

The suite owns the presentation sidecars + the broadcast arbiter. These tests
assert that start() installs everything in dependency order and stop() tears it
all down (sidecars first, arbiter last), plus that the shared crash-logger
catches a hard inner-loop crash.
"""

from __future__ import annotations

import asyncio

import pytest

from tradefarm.orchestrator import broadcast_os as bos
from tradefarm.orchestrator import broadcast_suite as bs
from tradefarm.orchestrator.broadcast_suite import BroadcastSuite, attach_crash_logger

_SUITE = "tradefarm.orchestrator.broadcast_suite"


class _RecordingSidecar:
    """Stand-in that records start/stop ordering across all instances."""

    events: list[str] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        # The audience coordinator is built with predictions=<board>; capture
        # whatever link it was handed so we can assert the dependency order.
        self.predictions = kwargs.get("predictions")
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True
        _RecordingSidecar.events.append(f"start:{type(self).__name__}")

    async def stop(self) -> None:
        self.stopped = True
        _RecordingSidecar.events.append("stop")


class _StubOrch:
    agents: list = []


@pytest.fixture(autouse=True)
def _clean_arbiter():
    bos.install_broadcast_arbiter(None, None)
    _RecordingSidecar.events.clear()
    yield
    bos.install_broadcast_arbiter(None, None)


def _patch_all(monkeypatch) -> None:
    for name in (
        "AutoDirector",
        "StreakWatcher",
        "CommentaryLoop",
        "YouTubeChatPoller",
        "PredictionsBoard",
        "AudienceCoordinator",
    ):
        monkeypatch.setattr(f"{_SUITE}.{name}", _RecordingSidecar)


def test_suite_constructs_ledger_scheduler_without_installing():
    """The suite builds the ledger/scheduler eagerly but installs nothing
    until start() — symmetric to the orchestrator's audit-fix Q contract."""
    suite = BroadcastSuite(_StubOrch())
    assert suite.ledger is not None
    assert suite.scheduler is not None
    assert bos.get_broadcast_ledger() is None
    assert bos.get_broadcast_scheduler() is None


async def test_start_installs_arbiter_and_all_sidecars(monkeypatch):
    _patch_all(monkeypatch)
    suite = BroadcastSuite(_StubOrch())

    await suite.start()

    # Arbiter installed and points at the suite's own instances.
    assert bos.get_broadcast_ledger() is suite.ledger
    assert bos.get_broadcast_scheduler() is suite.scheduler

    # Every sidecar constructed + started.
    for sc in (
        suite.auto_director,
        suite.streak_watcher,
        suite.commentary_loop,
        suite.youtube_chat,
        suite.predictions,
        suite.audience,
    ):
        assert sc is not None
        assert sc.started is True

    # Dependency order: audience is linked to the already-built predictions.
    assert suite.audience.predictions is suite.predictions

    await suite.stop()


async def test_stop_drains_sidecars_then_uninstalls_arbiter(monkeypatch):
    _patch_all(monkeypatch)
    suite = BroadcastSuite(_StubOrch())

    await suite.start()
    _RecordingSidecar.events.clear()
    await suite.stop()

    # All six sidecars stopped, then the arbiter uninstalled (so the count of
    # stop events equals six and the arbiter is gone afterwards).
    assert _RecordingSidecar.events.count("stop") == 6
    assert bos.get_broadcast_ledger() is None
    assert bos.get_broadcast_scheduler() is None

    # Fields cleared so a subsequent start() rebuilds.
    assert suite.auto_director is None
    assert suite.audience is None
    assert suite.predictions is None


async def test_start_is_idempotent(monkeypatch):
    _patch_all(monkeypatch)
    suite = BroadcastSuite(_StubOrch())

    await suite.start()
    first = suite.auto_director
    await suite.start()  # second call must not re-construct
    assert suite.auto_director is first

    await suite.stop()


async def test_attach_crash_logger_logs_non_cancel_exception(monkeypatch):
    """A hard inner-loop crash logs `background_loop_crashed` rather than
    surfacing as a bare 'Task exception was never retrieved'."""
    logged: list[tuple[str, dict]] = []

    def _fake_error(event: str, **kw) -> None:
        logged.append((event, kw))

    monkeypatch.setattr(bs.log, "error", _fake_error)

    async def _boom() -> None:
        raise RuntimeError("loop exploded")

    task = attach_crash_logger(asyncio.ensure_future(_boom()), name="orch_test")
    # Let the task run + the done-callback fire.
    with pytest.raises(RuntimeError, match="loop exploded"):
        await task

    assert logged, "expected a crash log entry"
    event, kw = logged[0]
    assert event == "background_loop_crashed"
    assert kw["name"] == "orch_test"
    assert "loop exploded" in kw["error"]


async def test_attach_crash_logger_silent_on_cancel(monkeypatch):
    """A clean cancel must NOT be logged as a crash."""
    logged: list[str] = []
    monkeypatch.setattr(bs.log, "error", lambda event, **kw: logged.append(event))

    async def _sleeper() -> None:
        await asyncio.sleep(3600)

    task = attach_crash_logger(asyncio.ensure_future(_sleeper()), name="orch_test")
    await asyncio.sleep(0)  # let it start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert logged == []


# ---------------------------------------------------------------------------
# 0.16.0 — record_path plumbed through BroadcastSuite + close() idempotency
# ---------------------------------------------------------------------------


async def test_suite_constructs_ledger_with_record_path(monkeypatch, tmp_path):
    """``BroadcastSuite(orch, record_path=path)`` plumbs the path into the
    recap ledger so every moment the suite records is also written to disk."""
    _patch_all(monkeypatch)
    target = tmp_path / "suite-record.ndjson"
    suite = BroadcastSuite(_StubOrch(), record_path=target)

    assert suite.ledger.record_path == target
    assert suite.ledger._record_handle is not None

    # Recording a moment lands a line on disk.
    suite.ledger.record(
        bos.BroadcastMoment(
            id="suite-moment-1",
            kind="activity",
            title="from suite",
            outputs=("ticker",),
        )
    )
    suite.ledger.close()
    contents = target.read_text(encoding="utf-8").strip()
    assert '"id":"suite-moment-1"' in contents


async def test_suite_stop_closes_ledger_handle(monkeypatch, tmp_path):
    """``stop()`` flushes + closes the ledger's on-disk record handle so the
    file is durable after teardown."""
    _patch_all(monkeypatch)
    target = tmp_path / "suite-stop.ndjson"
    suite = BroadcastSuite(_StubOrch(), record_path=target)
    await suite.start()
    await suite.stop()

    # Handle is released; a second close() is a no-op (idempotent).
    assert suite.ledger._record_handle is None
    suite.ledger.close()  # must not raise
    assert suite.ledger._record_handle is None


async def test_suite_close_is_idempotent(monkeypatch):
    """``suite.close()`` can be called multiple times safely (handy for
    test teardown + crash recovery paths)."""
    _patch_all(monkeypatch)
    suite = BroadcastSuite(_StubOrch())
    suite.close()  # no record_path, handle is None — should not raise
    suite.close()  # idempotent
