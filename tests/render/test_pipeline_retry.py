"""Tests for the per-step retry + backoff logic in
``tradefarm.render.pipeline._run_step``.

The retry loop wraps each ``step.run(argv)`` call. A transient
exception (``OSError``, ``httpx.HTTPError``, playwright errors)
retries up to ``max_attempts`` times with linear backoff. A
``SystemExit`` (deliberate failure from the inner CLI) is never
retried — it propagates immediately so the pipeline fails fast
on a real error.

We test by replacing the ``run`` attribute on a frozen
``Step`` dataclass (the project's pattern — see
``tests/render/test_pipeline.py::test_force_bypasses_idempotency``)
so the loop is exercised end-to-end without touching any real
CLIs. The retry's ``time.sleep`` is also patched to a no-op so
the test runs in milliseconds, not 30s.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from tradefarm.render import pipeline as pipeline_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_session(tmp_path: Path, session_id: str) -> Path:
    """Stage a minimal session dir so the runner's pre-checks pass."""
    sdir = tmp_path / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "manifest.json").write_text(json.dumps({"events": []}))
    (sdir / "beats.json").write_text(json.dumps([]))
    return sdir


def _make_step(key: str = "beats") -> pipeline_mod.Step:
    """Grab the real `beats` step from STEPS as a template.

    The runner iterates ``STEPS`` and resolves each step's run
    function via ``step.run(argv)``. We replace ``run`` (on a
    frozen dataclass — see the existing test pattern) with a
    test-controlled stub.
    """
    return next(s for s in pipeline_mod.STEPS if s.key == key)


def _opts(
    sessions_dir: Path, *, max_attempts: int = 2, retry_backoff_sec: float = 0.0
) -> pipeline_mod.PipelineOpts:
    return pipeline_mod.PipelineOpts(
        sessions_dir=sessions_dir,
        music=None,
        tts_provider="auto",
        tts_voice="alloy",
        upload_dry_run=True,
        stitch_xfade=0.4,
        force=False,
        max_attempts=max_attempts,
        retry_backoff_sec=retry_backoff_sec,
    )


# ---------------------------------------------------------------------------
# Success on first try
# ---------------------------------------------------------------------------


def test_step_succeeds_on_first_try(tmp_path: Path) -> None:
    """When the inner call succeeds immediately, there's no retry
    and no sleep."""
    _stub_session(tmp_path, "s_ok")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        print("ok")

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        pipeline_mod._run_step(step, "s_ok", _opts(tmp_path), lambda m: None)
    assert calls["n"] == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Success on second try
# ---------------------------------------------------------------------------


def test_step_succeeds_on_second_try(tmp_path: Path) -> None:
    """A transient ``OSError`` on the first try, success on the
    second try. The retry loop catches, sleeps, and re-invokes."""
    _stub_session(tmp_path, "s_recover")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient: chromium crashed")
        print("ok")

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        # Use a non-zero backoff so the sleep call is observable
        # in the mock; the default 0.0 would skip the sleep branch.
        pipeline_mod._run_step(
            step,
            "s_recover",
            _opts(tmp_path, retry_backoff_sec=0.5),
            lambda m: None,
        )
    assert calls["n"] == 2
    # One backoff sleep between attempt 1 and attempt 2.
    assert mock_sleep.call_count == 1
    assert mock_sleep.call_args.args[0] == 0.5


def test_step_succeeds_on_second_try_httpx(tmp_path: Path) -> None:
    """Same as above but with ``httpx.HTTPError`` — proves the
    retry tuple includes the httpx class (not just OSError)."""
    _stub_session(tmp_path, "s_recover_httpx")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("server closed connection")
        print("ok")

    object.__setattr__(step, "run", stub)

    pipeline_mod._run_step(step, "s_recover_httpx", _opts(tmp_path), lambda m: None)
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Failure after max_attempts
# ---------------------------------------------------------------------------


def test_step_fails_after_max_attempts(tmp_path: Path) -> None:
    """When the inner call keeps raising a transient exception,
    the loop tries ``max_attempts`` times then raises SystemExit
    so the pipeline fails fast (the "first failure wins" contract)."""
    _stub_session(tmp_path, "s_exhaust")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        raise OSError(f"crash {calls['n']}")

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        with pytest.raises(SystemExit) as exc_info:
            pipeline_mod._run_step(
                step,
                "s_exhaust",
                _opts(tmp_path, max_attempts=3, retry_backoff_sec=0.5),
                lambda m: None,
            )
    # max_attempts=3 → 3 calls, 2 backoff sleeps between them.
    assert calls["n"] == 3
    assert mock_sleep.call_count == 2
    msg = str(exc_info.value)
    assert "beats" in msg
    assert "3 attempts" in msg
    assert "OSError" in msg


def test_step_fails_after_max_attempts_one(tmp_path: Path) -> None:
    """``max_attempts=1`` means no retries — the first transient
    error becomes a SystemExit immediately."""
    _stub_session(tmp_path, "s_one")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        raise httpx.ConnectError("nope")

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        with pytest.raises(SystemExit):
            pipeline_mod._run_step(
                step,
                "s_one",
                _opts(tmp_path, max_attempts=1),
                lambda m: None,
            )
    assert calls["n"] == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# SystemExit is NOT retried
# ---------------------------------------------------------------------------


def test_system_exit_is_not_retried(tmp_path: Path) -> None:
    """``SystemExit`` from the inner CLI is a real failure, not a
    transient blip — the loop propagates it immediately. Without
    this guard, a deliberate ``raise SystemExit(1)`` from a CLI
    on bad input would sleep + retry before failing."""
    _stub_session(tmp_path, "s_sysexit")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        raise SystemExit(1)

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        with pytest.raises(SystemExit) as exc_info:
            pipeline_mod._run_step(
                step,
                "s_sysexit",
                _opts(tmp_path, max_attempts=5),
                lambda m: None,
            )
    # Called exactly once — no retry.
    assert calls["n"] == 1
    mock_sleep.assert_not_called()
    # The original SystemExit's code (1) is preserved in the new
    # message but the SystemExit type is the same — operators see
    # the "step 'X' failed (exit 1)" message.
    assert "beats" in str(exc_info.value)
    assert "exit 1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Backoff is configurable + linear
# ---------------------------------------------------------------------------


def test_retry_backoff_uses_configured_value(tmp_path: Path) -> None:
    """``retry_backoff_sec`` is passed to ``time.sleep`` between
    attempts. The runner doesn't exponential-back (per-step cost
    is already minutes); 30s of settle time is plenty."""
    _stub_session(tmp_path, "s_backoff")
    step = _make_step()

    def stub(argv):
        raise OSError("always fails")

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        with pytest.raises(SystemExit):
            pipeline_mod._run_step(
                step,
                "s_backoff",
                _opts(tmp_path, max_attempts=3, retry_backoff_sec=12.5),
                lambda m: None,
            )
    # Two sleeps (between attempt 1→2 and 2→3), each 12.5s.
    assert mock_sleep.call_count == 2
    for call in mock_sleep.call_args_list:
        assert call.args[0] == 12.5


# ---------------------------------------------------------------------------
# Non-transient exception is not retried
# ---------------------------------------------------------------------------


def test_non_transient_exception_is_not_retried(tmp_path: Path) -> None:
    """A ``ValueError`` from the inner CLI is a real bug, not a
    transient blip — the loop propagates it as SystemExit
    immediately (no retry, no backoff)."""
    _stub_session(tmp_path, "s_valerr")
    step = _make_step()
    calls = {"n": 0}

    def stub(argv):
        calls["n"] += 1
        raise ValueError("bad input")

    object.__setattr__(step, "run", stub)

    with patch("tradefarm.render.pipeline.time.sleep") as mock_sleep:
        with pytest.raises(SystemExit) as exc_info:
            pipeline_mod._run_step(
                step,
                "s_valerr",
                _opts(tmp_path, max_attempts=5),
                lambda m: None,
            )
    assert calls["n"] == 1
    mock_sleep.assert_not_called()
    assert "ValueError" in str(exc_info.value)
