"""Tests for the stream Vite liveness probe in
``tradefarm.render.headless.render_session``.

The probe runs ``httpx.get(stream_base, timeout=2.0)`` at the very
top of ``render_session`` and raises a clear ``RuntimeError`` if the
dev server isn't reachable. This trades a 30s/beat hang for a 2s
fast-fail with an actionable error message — operator forgets to
start ``cd stream && npm run dev``, the run dies in 2s instead of 5
minutes per beat.

We patch ``httpx.get`` (the module-level reference) so the test
doesn't actually need a running Vite server. The two cases:

- **stream up**: probe returns 200, ``render_session`` proceeds to
  the path-traversal guard (and the rest of the planning logic).
  We exercise this by reaching the FileNotFoundError raised when
  ``beats.json`` is missing — proves the probe passed and the
  function didn't short-circuit on the probe.
- **stream down**: probe raises ``httpx.ConnectError``, the
  function raises ``RuntimeError`` with the stream base URL in
  the message and the "start `cd stream && npm run dev`" hint.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from tradefarm.render.headless import render_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest_and_beats(tmp_path: Path, session_id: str = "s_probe") -> None:
    """Stage a minimal session dir so the post-probe path can find
    the files it needs to continue past the probe."""
    sdir = tmp_path / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "manifest.json").write_text(json.dumps({"events": []}))
    (sdir / "beats.json").write_text(json.dumps([]))


class _FakeResponse:
    """Mimics the ``httpx.Response`` shape ``render_session`` reads.

    The probe only inspects ``status_code``, so a tiny stub is
    enough — we don't need to fake the full response protocol.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Stream up → probe passes
# ---------------------------------------------------------------------------


async def test_probe_passes_when_stream_returns_200(tmp_path: Path) -> None:
    """A 200 from the probe lets the function continue past it. We
    verify by reaching the next gate (beats.json lookup), which
    raises FileNotFoundError because the test didn't stage one.

    The point of this test isn't the FileNotFoundError per se;
    it's that the probe didn't raise first.
    """
    _write_manifest_and_beats(tmp_path)

    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        mock_get.return_value = _FakeResponse(200)
        with pytest.raises(FileNotFoundError, match="beats.json"):
            await render_session(
                "s_no_beats",  # different session id → beats.json missing
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=True,
            )
    # The probe was called once, with the expected URL and a tight
    # timeout. We don't assert the URL is exactly the base (the
    # function normalises trailing slash), just that the call
    # happened and used a 2s timeout.
    assert mock_get.call_count == 1
    assert mock_get.call_args.kwargs.get("timeout") == 2.0
    assert "5180" in mock_get.call_args.args[0]


async def test_probe_accepts_redirects(tmp_path: Path) -> None:
    """A 3xx (Vite sometimes 301s /index.html → /) is acceptable.

    Only 4xx/5xx raise; 2xx and 3xx both pass.
    """
    _write_manifest_and_beats(tmp_path)

    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        mock_get.return_value = _FakeResponse(304)  # Not Modified
        with pytest.raises(FileNotFoundError):
            await render_session(
                "s_no_beats_2",
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=True,
            )


async def test_probe_skipped_when_disabled(tmp_path: Path) -> None:
    """``_probe=False`` skips the probe entirely (test escape hatch
    for the unit-test suite that runs without a real Vite)."""
    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        with pytest.raises(FileNotFoundError):
            await render_session(
                "s_no_beats_3",
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=False,
            )
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Stream down → clear error
# ---------------------------------------------------------------------------


async def test_probe_raises_runtime_error_on_connection_error(
    tmp_path: Path,
) -> None:
    """``httpx.HTTPError`` (connect refused, timeout, DNS, …)
    surfaces as a ``RuntimeError`` with the URL in the message
    and the npm-run-dev hint."""
    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(RuntimeError) as exc_info:
            await render_session(
                "s_x",
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=True,
            )
    msg = str(exc_info.value)
    assert "5180" in msg
    assert "npm run dev" in msg
    assert "Vite" in msg
    # The original ConnectError is the cause (preserved via ``from exc``).
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


async def test_probe_raises_runtime_error_on_timeout(tmp_path: Path) -> None:
    """A 2s timeout (the Vite dev server took too long to respond)
    also becomes a ``RuntimeError`` with the same actionable message."""
    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        mock_get.side_effect = httpx.TimeoutException("read timeout")
        with pytest.raises(RuntimeError) as exc_info:
            await render_session(
                "s_x",
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=True,
            )
    assert "npm run dev" in str(exc_info.value)


async def test_probe_raises_on_5xx(tmp_path: Path) -> None:
    """A 5xx response (Vite is up but erroring) is treated as
    'not reachable' and raises the same actionable error."""
    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        mock_get.return_value = _FakeResponse(500)
        with pytest.raises(RuntimeError) as exc_info:
            await render_session(
                "s_x",
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=True,
            )
    msg = str(exc_info.value)
    assert "500" in msg
    assert "npm run dev" in msg


async def test_probe_raises_on_404(tmp_path: Path) -> None:
    """A 404 (Vite is up but root path is misconfigured) is also
    a fail — the operator needs to see the actionable error."""
    with patch("tradefarm.render.headless.httpx.get") as mock_get:
        mock_get.return_value = _FakeResponse(404)
        with pytest.raises(RuntimeError) as exc_info:
            await render_session(
                "s_x",
                sessions_dir=tmp_path,
                stream_base="http://localhost:5180/",
                _probe=True,
            )
    assert "404" in str(exc_info.value)
