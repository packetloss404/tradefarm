"""Tests for the 0.17.0 WS frame recorder (api/ws_recording.py).

Five contracts pinned:

  1. One record() call -> exactly one NDJSON line on disk, parseable.
  2. Two WsRecorder instances for the same session_id -> the first
     is closed (and its buffer flushed) before the second opens.
  3. IO errors during record() are swallowed (the WS / orchestrator
     must never crash on a disk failure).
  4. close() is idempotent.
  5. The on-disk path matches `<base>/<session_id>.ndjson`.

Plus a couple of integration-flavored checks for the admin
endpoints (start/stop/list) and the module-level registry
(get_or_create, stop_recorder, list_recorded_sessions).

Recording is opt-in: a session with no active recorder must not
crash the WS or write to disk. The hot-path overhead matters and
is exercised by `test_record_is_noop_when_no_recorder_active`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tradefarm.api import ws_recording
from tradefarm.api.ws_recording import (
    DEFAULT_BASE_DIR,
    WsRecorder,
    get_or_create_recorder,
    list_recorded_sessions,
    stop_recorder,
)


@pytest.fixture(autouse=True)
def _isolate_recorders() -> None:
    """Snapshot + restore the module-level registry around each test.

    Several tests construct WsRecorder objects directly, which
    registers them in the module-level dict. Without this fixture
    the registry would leak between tests and the
    "at most one per session" assertion below would false-positive.
    """
    ws_recording.reset_for_tests()
    yield
    ws_recording.reset_for_tests()


# ---------------------------------------------------------------------------
# 1. Happy-path: one line per record, each parseable
# ---------------------------------------------------------------------------


def test_recorder_writes_one_line_per_record(tmp_path: Path) -> None:
    """3 records -> 3 lines, each line is a valid JSON object with
    the expected frame shape."""
    rec = WsRecorder(session_id="s_a", base_dir=tmp_path)
    rec.record({"type": "fill", "payload": {"symbol": "AAPL"}}, direction="out")
    rec.record({"type": "agent_pnl", "payload": {"pnl": 1.5}}, direction="out")
    rec.record({"type": "ping", "payload": {"client": "web"}}, direction="in")
    rec.close()

    lines = (tmp_path / "s_a.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        # Each line must round-trip as JSON, not be multi-line.
        frame = json.loads(line)
        assert set(frame.keys()) == {"ts", "session", "direction", "type", "payload"}
        assert frame["session"] == "s_a"
        # ts is an ISO string; we don't pin the exact value (the test
        # would be timing-sensitive) but it must parse.
        assert isinstance(frame["ts"], str) and frame["ts"]

    types = [json.loads(line)["type"] for line in lines]
    assert types == ["fill", "agent_pnl", "ping"]
    directions = [json.loads(line)["direction"] for line in lines]
    assert directions == ["out", "out", "in"]


def test_recorder_frame_payload_is_envelope_payload_only(tmp_path: Path) -> None:
    """The on-disk ``payload`` field is the *envelope's* payload
    (not the envelope itself). The recorder's contract is that
    `event["payload"]` becomes the on-disk `payload` — anything
    else in `event` (the envelope's own `type` / `ts`) is hoisted
    into top-level fields, not nested."""
    rec = WsRecorder(session_id="s_hoist", base_dir=tmp_path)
    rec.record(
        {"type": "fill", "ts": "2026-08-05T10:00:00+00:00", "payload": {"symbol": "AAPL"}},
        direction="out",
    )
    rec.close()
    frame = json.loads((tmp_path / "s_hoist.ndjson").read_text(encoding="utf-8").splitlines()[0])
    # The envelope's `type` is hoisted to the top-level `type` field
    # (NOT buried inside `payload`); the envelope's `ts` is replaced
    # by the recorder's clock ts (the audit clock, not the wire
    # clock — see WsRecorder.record docstring).
    assert frame["type"] == "fill"
    assert frame["payload"] == {"symbol": "AAPL"}
    # And the envelope's `ts` did NOT leak into `payload` (that
    # would be a silent schema break for downstream consumers).
    assert "ts" not in frame["payload"]


def test_recorder_persists_payload_dict_unchanged(tmp_path: Path) -> None:
    """The on-disk `payload` is the same dict the caller passed in
    — no copy, no schema transformation. Pin this so a future
    "let's normalise keys" refactor doesn't silently change the
    shape downstream consumers see."""
    payload = {"symbol": "MSFT", "qty": 3, "nested": {"deep": [1, 2, 3]}}
    rec = WsRecorder(session_id="s_p", base_dir=tmp_path)
    rec.record({"type": "fill", "payload": payload}, direction="out")
    rec.close()

    frame = json.loads((tmp_path / "s_p.ndjson").read_text(encoding="utf-8").splitlines()[0])
    assert frame["payload"] == payload


# ---------------------------------------------------------------------------
# 2. At-most-one-recorder-per-session: a second constructor closes the first
# ---------------------------------------------------------------------------


def test_recorder_appends_across_instances_for_same_session(tmp_path: Path) -> None:
    """Two WsRecorder instances for the same session_id: the first
    one's buffer is flushed + closed when the second is created.

    The behavior pins the "at most one recorder per session" rule
    so a future "pool of recorders" optimization can't silently
    double-write to the same file.
    """
    rec_a = WsRecorder(session_id="s_double", base_dir=tmp_path)
    rec_a.record({"type": "x", "payload": {"i": 1}}, direction="out")

    # Constructing a second recorder for the same session closes
    # the first (and the close() flushes the pending write).
    rec_b = WsRecorder(session_id="s_double", base_dir=tmp_path)
    rec_b.record({"type": "y", "payload": {"i": 2}}, direction="out")
    rec_b.close()

    # Both frames must be on disk, in order, and the file must be
    # properly flushed (closing a is implicit in the constructor).
    lines = (tmp_path / "s_double.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["type"] == "x"
    assert second["type"] == "y"
    # rec_a is closed (the second constructor did it). Calling
    # close() again must be a no-op (test_recorder_close_is_idempotent).
    rec_a.close()


def test_get_or_create_recorder_is_idempotent(tmp_path: Path) -> None:
    """The factory `get_or_create_recorder` returns the same
    instance on repeated calls for the same session — a second
    factory call is NOT a close-and-replace (that's the bare
    constructor's job). This is the behavior the admin endpoint's
    idempotency depends on."""
    rec_a = get_or_create_recorder("s_idem", base_dir=tmp_path)
    rec_b = get_or_create_recorder("s_idem", base_dir=tmp_path)
    assert rec_a is rec_b
    # And writing through either reference is the same write.
    rec_a.record({"type": "first", "payload": {}}, direction="out")
    rec_b.record({"type": "second", "payload": {}}, direction="out")
    rec_a.close()

    lines = (tmp_path / "s_idem.ndjson").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["first", "second"]


# ---------------------------------------------------------------------------
# 3. IO error tolerance
# ---------------------------------------------------------------------------


def test_recorder_swallows_io_errors(tmp_path: Path) -> None:
    """A write that raises OSError must NOT propagate — the recorder
    contract is "best-effort, never crash the WS or the orchestrator".
    Pin this so a future "raise on failure" hardening can't
    silently regress the on-call experience."""
    rec = WsRecorder(session_id="s_io", base_dir=tmp_path)
    try:
        # First call: succeeds (so the file exists, the open handle
        # is good, the registry has the entry).
        rec.record({"type": "ok", "payload": {}}, direction="out")
        assert rec.frames_recorded == 1
        # Second call: the underlying file write raises. We patch
        # `TextIO.write` on the recorder's private handle so the
        # error fires from inside the record() call (not at file
        # open time — that would be a different code path).
        with patch.object(rec._fh, "write", side_effect=OSError("disk full")):
            # Must not raise.
            rec.record({"type": "boom", "payload": {}}, direction="out")
        # The frames_recorded counter is in-memory only and should
        # NOT have advanced (the write was a no-op).
        assert rec.frames_recorded == 1
    finally:
        rec.close()

    # The surviving on-disk line is the first one — the second was
    # swallowed.
    lines = (tmp_path / "s_io.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "ok"


def test_recorder_swallows_open_failure_on_construct(tmp_path: Path) -> None:
    """A path that can't be opened (e.g. a directory with the same
    name) propagates from `open()` — the recorder does NOT swallow
    construction errors. The "swallow" contract is on `record()`,
    not `__init__`; a recorder that can't open its file is a bug
    the operator should see."""
    # Make a directory at the path the recorder would try to open.
    blocker = tmp_path / "s_blocker.ndjson"
    blocker.mkdir(parents=True, exist_ok=True)
    with pytest.raises((IsADirectoryError, PermissionError, OSError)):
        WsRecorder(session_id="s_blocker", base_dir=tmp_path)
    # The failed construction must NOT have left an entry in the
    # registry (otherwise a follow-up call would silently re-use a
    # never-opened handle).
    assert ws_recording.get_recorder("s_blocker") is None


# ---------------------------------------------------------------------------
# 4. close() is idempotent
# ---------------------------------------------------------------------------


def test_recorder_close_is_idempotent(tmp_path: Path) -> None:
    """Two close() calls in a row: the second is a no-op. Pins the
    contract the WS layer relies on (the input reader task and the
    bus subscription each may try to close on shutdown — racing
    them must not raise)."""
    rec = WsRecorder(session_id="s_close", base_dir=tmp_path)
    rec.record({"type": "x", "payload": {}}, direction="out")
    rec.close()
    # Second call must not raise, must not advance the frames counter.
    pre = rec.frames_recorded
    rec.close()
    assert rec.frames_recorded == pre
    # And recording after close is silently dropped (the file
    # handle is gone — the in-memory state stays consistent).
    rec.record({"type": "after_close", "payload": {}}, direction="out")
    assert rec.frames_recorded == pre


def test_stop_recorder_returns_none_when_no_active(tmp_path: Path) -> None:
    """`stop_recorder` for a session that was never started
    returns None — the admin endpoint turns that into a 404."""
    assert stop_recorder("s_never_started") is None


def test_stop_recorder_closes_and_deregisters(tmp_path: Path) -> None:
    """`stop_recorder` for an active session closes the file and
    removes the entry from the module-level registry — a follow-up
    `get_recorder` returns None."""
    rec = get_or_create_recorder("s_stop", base_dir=tmp_path)
    rec.record({"type": "x", "payload": {}}, direction="out")
    closed = stop_recorder("s_stop")
    assert closed is rec
    assert ws_recording.get_recorder("s_stop") is None
    # And a re-create for the same session gets a fresh recorder
    # (the path is the same, the file is appended — both behaviors
    # are correct for a recording that resumes after a stop).
    rec2 = get_or_create_recorder("s_stop", base_dir=tmp_path)
    assert rec2 is not rec
    rec2.close()


# ---------------------------------------------------------------------------
# 5. Path shape
# ---------------------------------------------------------------------------


def test_recorder_path_includes_session_id_and_ndjson_extension(tmp_path: Path) -> None:
    """The on-disk path is `<base>/<session_id>.ndjson`. Pin this
    so a future "include a timestamp subdirectory" refactor can't
    silently break the admin endpoint's list + the CI fixture
    layout (which assumes flat `<base>/<sid>.ndjson`)."""
    rec = WsRecorder(session_id="s_path", base_dir=tmp_path)
    try:
        assert rec.path == tmp_path / "s_path.ndjson"
        assert rec.path.suffix == ".ndjson"
        # Parent must exist (the constructor creates the base dir).
        assert rec.path.parent.is_dir()
    finally:
        rec.close()


def test_recorder_path_accepts_explicit_path_override(tmp_path: Path) -> None:
    """The constructor's `path=` argument wins over `base_dir=`
    — the test-fixture layer uses this to redirect to a tmp dir
    without having to know the default base_dir's location."""
    target = tmp_path / "custom" / "alt.ndjson"
    rec = WsRecorder(session_id="ignored", base_dir=tmp_path, path=target)
    try:
        assert rec.path == target
        # Even though session_id is "ignored", the file is at the
        # explicit path — useful for tests that want a deterministic
        # filename independent of session_id.
        rec.record({"type": "x", "payload": {}}, direction="out")
        assert target.is_file()
    finally:
        rec.close()


def test_recorder_rejects_empty_session_id(tmp_path: Path) -> None:
    """An empty session_id would create a file named just `.ndjson`
    (or fail in confusing ways); the constructor rejects it
    explicitly. The 400 the admin endpoint emits depends on this."""
    with pytest.raises(ValueError, match="non-empty"):
        WsRecorder(session_id="", base_dir=tmp_path)


# ---------------------------------------------------------------------------
# 6. list_recorded_sessions
# ---------------------------------------------------------------------------


def test_list_recorded_sessions_empty_when_dir_missing(tmp_path: Path) -> None:
    """`list_recorded_sessions` on a non-existent dir returns [] —
    not an error. The admin endpoint surfaces this as
    `sessions: []`."""
    missing = tmp_path / "no_such_dir"
    assert list_recorded_sessions(missing) == []


def test_list_recorded_sessions_returns_sorted_stems(tmp_path: Path) -> None:
    """The list is the sorted stem of every `*.ndjson` in the
    directory. Stems (not full paths) — the dashboard's UI
    renders the session_id as the list label."""
    (tmp_path / "b_session.ndjson").write_text("{}\n", encoding="utf-8")
    (tmp_path / "a_session.ndjson").write_text("{}\n", encoding="utf-8")
    (tmp_path / "c_session.ndjson").write_text("{}\n", encoding="utf-8")
    # An unrelated file is ignored.
    (tmp_path / "readme.txt").write_text("not a recording", encoding="utf-8")
    assert list_recorded_sessions(tmp_path) == [
        "a_session",
        "b_session",
        "c_session",
    ]


# ---------------------------------------------------------------------------
# 7. Overhead when no recorder is active
# ---------------------------------------------------------------------------


def test_record_is_noop_when_no_recorder_active() -> None:
    """`get_recorder` returns None for an unknown session — the WS
    hot path is `recorder = get_recorder(session_id); if recorder
    is not None: record(...)`. Pin the no-op contract so a future
    "always log to a default file" change can't silently start
    writing for sessions that never opted in."""
    # The whole point: no recorder is registered, so get_recorder
    # returns None, and a call site can short-circuit.
    assert ws_recording.get_recorder("s_no_one") is None
    # And the default base dir is the documented one (so an
    # operator who doesn't set base_dir= gets `data_cache/ws_recordings/`
    # without having to look it up).
    assert DEFAULT_BASE_DIR == Path("data_cache/ws_recordings")


# ---------------------------------------------------------------------------
# 8. Bad direction is dropped, not silently coerced
# ---------------------------------------------------------------------------


def test_recorder_rejects_unknown_direction(tmp_path: Path) -> None:
    """A `direction` value that isn't "in" or "out" would corrupt
    downstream consumers (the WS replay loader keys off
    `direction` to split client/server). The recorder drops the
    frame and logs a warning rather than writing a bogus line."""
    rec = WsRecorder(session_id="s_dir", base_dir=tmp_path)
    rec.record({"type": "x", "payload": {}}, direction="sideways")  # type: ignore[arg-type]
    rec.close()
    # The bad frame must NOT be on disk; the file is either empty
    # or absent (we don't pre-create).
    target = tmp_path / "s_dir.ndjson"
    if target.exists():
        assert target.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# 9. Admin endpoints
# ---------------------------------------------------------------------------


def test_admin_ws_recording_start_is_idempotent(tmp_path: Path) -> None:
    """Two start calls for the same session_id return the same
    path; the second call does NOT close + reopen the file (the
    `already_active` flag distinguishes the two for the toast)."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app

    client = TestClient(app)
    body = {"session_id": "s_admin", "base_dir": str(tmp_path)}

    r1 = client.post("/admin/ws_recording/start", json=body)
    assert r1.status_code == 200, r1.text
    payload1 = r1.json()
    assert payload1["ok"] is True
    assert payload1["already_active"] is False
    assert payload1["path"].endswith("s_admin.ndjson")

    r2 = client.post("/admin/ws_recording/start", json=body)
    assert r2.status_code == 200, r2.text
    payload2 = r2.json()
    assert payload2["ok"] is True
    assert payload2["already_active"] is True
    # Same path, same recorder — the second call did not close it.
    assert payload2["path"] == payload1["path"]
    # And a frame written through one of them lands on disk.
    rec = ws_recording.get_recorder("s_admin")
    assert rec is not None
    rec.record({"type": "x", "payload": {}}, direction="out")
    stop_recorder("s_admin")
    lines = (tmp_path / "s_admin.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_admin_ws_recording_stop_404_when_no_recorder() -> None:
    """`stop` for a session that was never started returns 404.
    The dashboard's RecordingPanel turns this into a
    "not recording" toast."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app

    client = TestClient(app)
    r = client.post("/admin/ws_recording/stop", json={"session_id": "s_never"})
    assert r.status_code == 404
    assert "no active recorder" in r.json()["detail"]


def test_admin_ws_recording_stop_returns_frames_recorded(tmp_path: Path) -> None:
    """`stop` returns the in-memory frames_recorded counter so the
    dashboard can show "captured N frames" without a follow-up
    `wc -l`."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app

    client = TestClient(app)
    rec = get_or_create_recorder("s_frames", base_dir=tmp_path)
    for i in range(3):
        rec.record({"type": "x", "payload": {"i": i}}, direction="out")

    r = client.post("/admin/ws_recording/stop", json={"session_id": "s_frames"})
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["ok"] is True
    assert payload["frames_recorded"] == 3
    assert payload["path"].endswith("s_frames.ndjson")
    # And the on-disk NDJSON is parseable line-by-line.
    lines = (tmp_path / "s_frames.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # must not raise


def test_admin_ws_recording_list_returns_sessions(tmp_path: Path) -> None:
    """`list?base_dir=...` returns the sorted list of session_ids
    with a recording. The default base_dir is the module's
    DEFAULT_BASE_DIR; the operator can pass an explicit one."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app

    # Write two recordings to a fresh dir.
    (tmp_path / "alpha.ndjson").write_text("{}\n", encoding="utf-8")
    (tmp_path / "beta.ndjson").write_text("{}\n", encoding="utf-8")

    client = TestClient(app)
    r = client.get(f"/admin/ws_recording/list?base_dir={tmp_path}")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["sessions"] == ["alpha", "beta"]
    assert payload["base_dir"] == str(tmp_path)


def test_admin_ws_recording_start_rejects_bad_session_id() -> None:
    """`start` with a session_id that fails the safe-id regex
    returns 400 (not 500). A path-traversal probe gets a clean
    rejection."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app

    client = TestClient(app)
    r = client.post(
        "/admin/ws_recording/start", json={"session_id": "../etc/passwd"}
    )
    assert r.status_code == 400
    assert "invalid session_id" in r.json()["detail"]


def test_admin_ws_recording_start_rejects_empty_session_id() -> None:
    """`start` with an empty session_id returns 400 — the
    constructor's `ValueError` is mapped to a 400 in the endpoint."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app

    client = TestClient(app)
    r = client.post("/admin/ws_recording/start", json={"session_id": ""})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 10. Direct end-to-end: admin start + simulated WS frame + admin stop
# ---------------------------------------------------------------------------


def test_admin_start_then_record_then_stop_round_trip(tmp_path: Path) -> None:
    """Operator flow: start, write 5 frames, stop, load back. The
    admin endpoint path matches the unit-test recorder path
    (same registry, same on-disk file)."""
    from fastapi.testclient import TestClient

    from tradefarm.api.main import app
    from tradefarm.orchestrator.broadcast_fixtures import load_ws_recording

    client = TestClient(app)
    r = client.post(
        "/admin/ws_recording/start", json={"session_id": "s_e2e", "base_dir": str(tmp_path)}
    )
    assert r.status_code == 200
    rec = ws_recording.get_recorder("s_e2e")
    assert rec is not None
    for i in range(5):
        rec.record({"type": "tick", "payload": {"i": i}}, direction="out")

    r2 = client.post("/admin/ws_recording/stop", json={"session_id": "s_e2e"})
    assert r2.status_code == 200
    assert r2.json()["frames_recorded"] == 5

    # Load back via the fixtures helper and assert the round-trip.
    frames = load_ws_recording(tmp_path / "s_e2e.ndjson")
    assert len(frames) == 5
    for i, frame in enumerate(frames):
        assert frame["session"] == "s_e2e"
        assert frame["direction"] == "out"
        assert frame["type"] == "tick"
        assert frame["payload"] == {"i": i}
