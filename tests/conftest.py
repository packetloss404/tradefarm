"""Shared pytest fixtures for the tradefarm test suite.

Currently provides:
- ``record_path``: a tmp-directory path for ledger record-to-disk tests.
- ``fake_clock``: a controllable clock for deterministic scheduler TTL tests.
- ``pinned_vod_today``: pins the runtime clock to a known ET trading day
  (2026-08-04 17:00 ET) so the VOD scheduler's per-day idempotency check
  is deterministic regardless of which day the test happens to run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from tradefarm.orchestrator.broadcast_fixtures import FakeClock


@pytest.fixture
def record_path(tmp_path: Path) -> Iterator[Path]:
    """A tmp-directory path suitable for ``BroadcastRecapLedger(record_path=...)``.

    Yields ``tmp_path / "fixture.ndjson"``. The file is not pre-created; the
    ledger opens it in append mode (which creates it if missing).
    """
    target = tmp_path / "fixture.ndjson"
    yield target
    # Best-effort cleanup; tmp_path is already isolated but explicit is
    # cheaper than debugging a leaked handle in CI.
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass


@pytest.fixture
def fake_clock() -> FakeClock:
    """A fresh ``FakeClock`` starting at 0.0.

    Tests advance time by setting ``clock.now`` directly or calling
    ``clock.advance(delta)``. Passed to ``BroadcastScheduler(clock=...)``
    so TTL transitions fire on demand instead of waiting for wall-clock
    seconds.
    """
    return FakeClock(start=0.0)


@pytest.fixture
def pinned_vod_today():
    """Pin the runtime clock to 2026-08-04 17:00 ET (post-market-close).

    The VOD scheduler's per-day idempotency check (``_maybe_fire_vod_run``)
    uses ``runtime.clock.now_utc()`` to compute "today" in ET. Without a
    pinned clock, tests that hardcode ``2026-08-04`` as the row date only
    pass on that exact wall-clock day — by 2026-08-05, the scheduler thinks
    "today" is the 5th and fires despite the pre-existing 4th row.

    The pinned time is 17:00 ET, which is 5+ minutes past the 16:00 ET
    NYSE close, so ``is_market_closed_for_n_minutes(5)`` is True and the
    scheduler is eligible to fire. 2026-08-04 was a Tuesday (a real
    trading day in 2026) so the holiday check passes too.

    Yields a token to pass to :func:`tradefarm.runtime.clock.reset_replay_now`
    on teardown. Tests that only need the side effect can ignore the yield.
    """
    from datetime import datetime, timezone

    from tradefarm.runtime.clock import reset_replay_now, set_replay_now

    fixed_now_utc = datetime(2026, 8, 4, 21, 0, 0, tzinfo=timezone.utc)  # 17:00 ET
    token = set_replay_now(fixed_now_utc)
    try:
        yield fixed_now_utc
    finally:
        reset_replay_now(token)

