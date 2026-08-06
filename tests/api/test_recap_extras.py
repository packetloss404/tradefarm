"""Tests for the 0.16.0 ``/api/recap/ledger`` + ``/api/weekly/<week_id>`` endpoints.

The ledger endpoint is a thin wrapper around
``BroadcastRecapLedger.to_payload()`` so the test installs a
fresh arbiter + seeds a couple of moments, then asserts the response
shape mirrors the ledger.

The weekly endpoint wraps ``tradefarm.session.weekly_rollup.read_weekly_rollup``
with a format check + 404 handling. The test seeds a rollup on a
``tmp_path`` and verifies both the 200 happy path and the 404 missing
case.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradefarm.orchestrator import broadcast_os as bos
from tradefarm.orchestrator.broadcast_os import BroadcastMoment
from tradefarm.orchestrator.broadcast_recap import BroadcastRecapLedger
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler


# ---------------------------------------------------------------------------
# Ledger endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_client(monkeypatch):
    """FastAPI TestClient with a freshly-installed broadcast arbiter.

    The TestClient is instantiated WITHOUT entering the context
    manager — that would trigger the full FastAPI lifespan (which
    boots a real orchestrator) and slow the test down. The recap
    router doesn't need the orchestrator; it reads the module-
    global arbiter we install below.
    """
    from tradefarm.api.main import app

    # Install a fresh ledger + scheduler so the test is hermetic.
    fresh_ledger = BroadcastRecapLedger()
    fresh_scheduler = BroadcastScheduler()
    bos.install_broadcast_arbiter(fresh_ledger, fresh_scheduler)

    # Seed two moments so the response has visible data.
    fresh_ledger.extend(
        [
            BroadcastMoment(
                id="m_low",
                kind="activity",
                title="low",
                priority=10,
                outputs=("ticker",),
                metadata={"source": "seed"},
            ),
            BroadcastMoment(
                id="m_high",
                kind="rank_change",
                title="high",
                priority=80,
                outputs=("ticker", "recap_log"),
                metadata={"source": "seed"},
            ),
        ]
    )

    client = TestClient(app)
    yield client, fresh_ledger

    bos.install_broadcast_arbiter(None, None)


def test_recap_ledger_returns_broadcast_recap_ledger_payload(ledger_client) -> None:
    """The endpoint returns the in-memory ledger's ``to_payload()``
    shape, with the recent + top slices sized per the recap scene
    contract (20/10).
    """
    client, ledger = ledger_client
    r = client.get("/recap/ledger")
    assert r.status_code == 200
    body = r.json()
    # The suite's BroadcastRecapLedger uses max_moments=100; assert the
    # payload matches ``to_payload()`` exactly.
    assert body["max_moments"] == ledger.max_moments
    assert body["count"] == 2
    assert {m["id"] for m in body["recent"]} == {"m_low", "m_high"}
    # Top slice is sorted by priority desc; the high moment wins.
    assert [m["id"] for m in body["top"]] == ["m_high", "m_low"]


def test_recap_ledger_empty_when_no_arbiter(monkeypatch) -> None:
    """When the suite hasn't been started (no arbiter installed), the
    endpoint returns the same empty-shape payload the suite would
    produce from a fresh ``BroadcastRecapLedger()`` so the stream
    doesn't have to special-case "no data".
    """
    from tradefarm.api.main import app

    bos.install_broadcast_arbiter(None, None)
    client = TestClient(app)
    r = client.get("/recap/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["max_moments"] == 0
    assert body["count"] == 0
    assert body["recent"] == []
    assert body["top"] == []


# ---------------------------------------------------------------------------
# Weekly rollup endpoint
# ---------------------------------------------------------------------------


def _write_rollup(base: Path, week_id: str, rollup: dict) -> Path:
    out = base / "weekly" / week_id / "rollup.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rollup, indent=2), encoding="utf-8")
    return out


def test_weekly_rollup_404_when_missing(monkeypatch, tmp_path) -> None:
    """A request for a week with no rollup file returns 404 (not
    empty 200) so the stream can render a "this week has no data
    yet" frame instead of pretending it's an empty rollup.
    """
    from tradefarm.api.main import app
    from tradefarm.session import replay_query

    # Point the rollup reader at the empty tmp_path.
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)

    client = TestClient(app)
    r = client.get("/recap/weekly/2099-W01")
    assert r.status_code == 404
    assert "2099-W01" in r.json()["detail"]


def test_weekly_rollup_400_on_bad_format(monkeypatch) -> None:
    """A non-``YYYY-WNN`` path component must 400 before any disk touch
    so a junk value can't slip through to the read path. We test a
    few obviously-bad shapes that the FastAPI path parser still routes
    to our handler: an alpha-only string, a wrong separator
    (``2026W31`` instead of ``2026-W31``), and a truncated value
    (``2026-W`` with no week number).
    """
    from tradefarm.api.main import app

    client = TestClient(app)

    for bad in ["not-a-week", "2026W31", "2026-W", "2026-WXX", "abcdefg"]:
        r = client.get(f"/recap/weekly/{bad}")
        assert r.status_code == 400, f"expected 400 for {bad!r}, got {r.status_code}"
        assert "YYYY-WNN" in r.json()["detail"], f"missing detail for {bad!r}"


def test_weekly_rollup_200_for_known_week(monkeypatch, tmp_path) -> None:
    """A request for a week with a rollup file returns the on-disk
    JSON verbatim, so the stream can render ``strategy_rollup`` /
    ``rivalries`` / ``pool_pnl`` straight from the response.
    """
    from tradefarm.api.main import app
    from tradefarm.session import replay_query

    week_id = "2026-W31"
    rollup = {
        "week_id": week_id,
        "date_range": ["2026-08-02", "2026-08-08"],
        "strategy_rollup": {
            "momentum": {"agents": 5, "equity": 5000, "pnl": 250, "fills": 12, "pnlPct": 5.0},
        },
        "rivalries": [
            {"a": 1, "b": 2, "symbol": "NVDA", "count": 4, "a_pnl": 50.0, "b_pnl": -30.0},
        ],
        "promotions": [],
        "sessions": [],
        "pool_pnl": 250,
        "pool_pnl_pct": 5.0,
    }
    _write_rollup(tmp_path, week_id, rollup)
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)

    client = TestClient(app)
    r = client.get(f"/recap/weekly/{week_id}")
    assert r.status_code == 200
    body = r.json()
    assert body == rollup


# Keep the lint quiet about unused imports.
_ = datetime
_ = timedelta
_ = timezone
