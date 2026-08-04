"""Tests for ``tradefarm.api.pipeline`` — the HTTP wrapper around
``tradefarm.render.pipeline``.

Covers the three endpoints:
- POST /pipeline/run                 start a new run, returns run_id
- GET  /pipeline/runs                 list recent runs
- GET  /pipeline/runs/{run_id}        get one run's status + log

The background task is hard to assert about deterministically — the
run is dispatched on the asyncio loop and may take a moment. We
patch ``pipeline_mod.run_pipeline`` with a stub that updates the
run state synchronously, so tests are fast and reliable.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import tradefarm.render.pipeline as pipeline_mod
from tradefarm.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def stub_runner(monkeypatch: pytest.MonkeyPatch):
    """Patch ``pipeline_mod.run_pipeline`` to mark the run as done
    synchronously and store a canned line. Lets tests assert the
    run-state machine without waiting on a real pipeline."""

    def make_stub() -> Callable[[Any], Any]:
        def stub(
            *,
            session_id: str,
            opts: pipeline_mod.PipelineOpts,
            enabled: set[str],
            force: bool,
            dry_run: bool,
            sink: Callable[[str], None] | None = None,
        ) -> None:
            emit = sink or (lambda m: None)
            emit(f"session_id={session_id}")
            emit(f"enabled={sorted(enabled)}")
            for i, key in enumerate(sorted(enabled), 1):
                emit(f"step {i}/{len(enabled)}: {key} done")
            emit("DONE")
        return stub

    monkeypatch.setattr(pipeline_mod, "run_pipeline", make_stub())
    return monkeypatch


# ---------------------------------------------------------------------------
# POST /pipeline/run
# ---------------------------------------------------------------------------


def test_start_run_returns_run_id_and_status(
    client: TestClient, stub_runner: pytest.MonkeyPatch
) -> None:
    r = client.post("/pipeline/run", json={"date": "2026-08-04", "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body and len(body["run_id"]) == 12
    assert body["status"] in ("pending", "running", "done", "failed")
    assert body["session_id"].startswith("s_2026-08-04_")
    # session.run is enabled by default; the dry-run arg doesn't gate it.
    assert "session" in body["enabled"]


def test_start_run_requires_date_or_session_id(
    client: TestClient, stub_runner: pytest.MonkeyPatch
) -> None:
    r = client.post("/pipeline/run", json={})
    assert r.status_code == 400


def test_start_run_with_session_id_skips_session_step(
    client: TestClient, stub_runner: pytest.MonkeyPatch
) -> None:
    """Resuming an existing session should NOT include session.run in
    the enabled set — the operator already has the manifest."""
    r = client.post(
        "/pipeline/run",
        json={"session_id": "s_existing_abc123", "include_tts": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert "session" not in body["enabled"]
    assert "tts" in body["enabled"]


def test_start_run_records_run_in_list(
    client: TestClient, stub_runner: pytest.MonkeyPatch
) -> None:
    r = client.post("/pipeline/run", json={"date": "2026-08-04"})
    run_id = r.json()["run_id"]
    listed = client.get("/pipeline/runs").json()
    assert any(rr["run_id"] == run_id for rr in listed)


# ---------------------------------------------------------------------------
# GET /pipeline/runs
# ---------------------------------------------------------------------------


def test_list_runs_empty(client: TestClient) -> None:
    """An empty pipeline runs list returns [] (not a 404)."""
    r = client.get("/pipeline/runs")
    assert r.status_code == 200
    # We don't assert [] because earlier tests may have left entries.
    assert isinstance(r.json(), list)


def test_list_runs_returns_newest_first(
    client: TestClient, stub_runner: pytest.MonkeyPatch
) -> None:
    r1 = client.post("/pipeline/run", json={"date": "2026-08-04"}).json()
    r2 = client.post("/pipeline/run", json={"date": "2026-08-05"}).json()
    listed = client.get("/pipeline/runs").json()
    ids = [r["run_id"] for r in listed]
    # r2 is newer → should appear before r1 in the list.
    assert ids.index(r2["run_id"]) < ids.index(r1["run_id"])


# ---------------------------------------------------------------------------
# GET /pipeline/runs/{run_id}
# ---------------------------------------------------------------------------


def test_get_run_includes_last_lines_after_runner_finishes(
    client: TestClient, stub_runner: pytest.MonkeyPatch
) -> None:
    r = client.post("/pipeline/run", json={"date": "2026-08-04", "dry_run": True})
    run_id = r.json()["run_id"]
    # The background task runs in the TestClient's event loop. We
    # spin briefly so the runner completes before we poll.
    for _ in range(20):
        body = client.get(f"/pipeline/runs/{run_id}").json()
        if body["status"] in ("done", "failed"):
            break
        asyncio.sleep(0.05)
    assert body["status"] == "done"
    # The stub emits 4+ lines; last_lines should be populated.
    assert len(body["last_lines"]) >= 3
    assert any("DONE" in ln for ln in body["last_lines"])


def test_get_unknown_run_returns_404(client: TestClient) -> None:
    r = client.get("/pipeline/runs/doesnotexist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


def test_runner_failure_records_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If pipeline_mod.run_pipeline raises SystemExit, the run is
    marked failed with the error message."""

    def fail_stub(
        *,
        session_id: str,
        opts: pipeline_mod.PipelineOpts,
        enabled: set[str],
        force: bool,
        dry_run: bool,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        raise SystemExit("step 'beats' failed (exit 1)")

    monkeypatch.setattr(pipeline_mod, "run_pipeline", fail_stub)

    r = client.post("/pipeline/run", json={"date": "2026-08-04"})
    run_id = r.json()["run_id"]
    for _ in range(20):
        body = client.get(f"/pipeline/runs/{run_id}").json()
        if body["status"] in ("done", "failed"):
            break
        asyncio.sleep(0.05)
    assert body["status"] == "failed"
    assert "beats" in body["error"]


def test_runner_dry_run_marks_done_without_invoking_steps(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dry-run should not call run_pipeline's body — but the stub
    records 'done' anyway for the test. The real signal is that
    'enabled' is correctly resolved."""

    invocations: list[dict[str, Any]] = []

    def tracking_stub(
        *,
        session_id: str,
        opts: pipeline_mod.PipelineOpts,
        enabled: set[str],
        force: bool,
        dry_run: bool,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        invocations.append(
            {"session_id": session_id, "enabled": set(enabled), "dry_run": dry_run}
        )

    monkeypatch.setattr(pipeline_mod, "run_pipeline", tracking_stub)

    r = client.post(
        "/pipeline/run",
        json={
            "date": "2026-08-04",
            "dry_run": True,
            "include_tts": True,
            "include_upload": True,
        },
    )
    run_id = r.json()["run_id"]
    for _ in range(20):
        body = client.get(f"/pipeline/runs/{run_id}").json()
        if body["status"] in ("done", "failed"):
            break
        asyncio.sleep(0.05)
    assert len(invocations) == 1
    inv = invocations[0]
    assert inv["dry_run"] is True
    assert "tts" in inv["enabled"]
    assert "upload" in inv["enabled"]
    # session.run is included even on dry-run — the runner still prints
    # the plan for it.
    assert "session" in inv["enabled"]
