from __future__ import annotations

from unittest.mock import patch

import pytest

from tradefarm.orchestrator import broadcast_os as bos
from tradefarm.orchestrator.scheduler import Orchestrator


class _RaisingSidecar:
    """Stand-in whose start() raises, mimicking a boot-time failure."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    async def start(self) -> None:
        raise RuntimeError("sidecar boot failed")

    async def stop(self) -> None:
        return None


class _RecordingSidecar:
    """Stand-in that records whether start() was actually awaited."""

    instances: list["_RecordingSidecar"] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.started = False
        _RecordingSidecar.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_loops(monkeypatch):
    """Disable the long-running scheduler loops so the test isolates sidecars."""
    from tradefarm.config import settings

    monkeypatch.setattr(settings, "auto_tick_interval_sec", 0)
    monkeypatch.setattr(settings, "academy_eval_interval_sec", 0)
    yield
    # Always leave the module-global arbiter clean for the next test.
    bos.install_broadcast_arbiter(None, None)


async def test_sidecar_start_failure_surfaces_at_boot():
    """A sidecar whose start() raises must propagate out of start_background
    rather than being swallowed by a discarded create_task."""
    orch = Orchestrator(agents=[])

    with patch("tradefarm.orchestrator.scheduler.AutoDirector", _RaisingSidecar):
        with pytest.raises(RuntimeError, match="sidecar boot failed"):
            await orch.start_background()


async def test_sidecars_are_actually_started():
    """Each sidecar's start() is awaited (not fire-and-forget), so the
    instance records that it ran by the time start_background returns."""
    _RecordingSidecar.instances.clear()
    orch = Orchestrator(agents=[])

    with (
        patch("tradefarm.orchestrator.scheduler.AutoDirector", _RecordingSidecar),
        patch("tradefarm.orchestrator.scheduler.StreakWatcher", _RecordingSidecar),
        patch("tradefarm.orchestrator.scheduler.CommentaryLoop", _RecordingSidecar),
        patch("tradefarm.orchestrator.scheduler.YouTubeChatPoller", _RecordingSidecar),
        patch("tradefarm.orchestrator.scheduler.PredictionsBoard", _RecordingSidecar),
        patch("tradefarm.orchestrator.scheduler.AudienceCoordinator", _RecordingSidecar),
    ):
        await orch.start_background()

    assert len(_RecordingSidecar.instances) == 6
    assert all(s.started for s in _RecordingSidecar.instances)
    # Idempotent: a second call doesn't re-construct already-started sidecars.
    with patch("tradefarm.orchestrator.scheduler.AutoDirector", _RecordingSidecar):
        await orch.start_background()
    assert len(_RecordingSidecar.instances) == 6
