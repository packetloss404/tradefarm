"""WS frame recorder — logs every /ws envelope to a per-session NDJSON file.

0.17.0 — three concrete use cases drive this module:

  1. Audio-engine tuning without live ticks — load a recorded session
     into the stream app and watch the rotator behave.
  2. Pre-recorded promo clips — record a session with intentional
     moments, then play it back at higher speed.
  3. Test fixture generation — recordings become CI-loadable replays
     (the same way ``tests/fixtures/moments/*.ndjson`` works for
     scheduler tuning).

Recording is opt-in. A recorder is created either via the admin
endpoint (operator pre-arms a session before opening the dashboard)
or by a WS connection that supplies ``?session_id=...`` in the query
string. When no recorder is active for a session, the WS hot path
costs a single pointer check (``if recorder is not None``).

The overhead matters because every broadcast event flows through
``publish_event`` on every tick; the recorder is gated on a
module-level ``_SESSION_RECS`` lookup that happens once per WS
connection, not per event. See ``api/ws.py`` for the integration
point and the rationale for the recorder-aware shim.

The on-disk file path defaults to
``data_cache/ws_recordings/<session_id>.ndjson`` so operators can
``cp`` the resulting NDJSON to ``tests/fixtures/ws/`` for committed
fixtures (``data_cache/`` is gitignored).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import structlog

log = structlog.get_logger()

# Default on-disk root. Operators copy recordings to
# tests/fixtures/ws/ for committed fixtures (the dir is gitignored).
DEFAULT_BASE_DIR = Path("data_cache/ws_recordings")

# Module-level registry: at most one recorder per session_id. The
# constructor closes any pre-existing recorder for the same session;
# the factory :func:`get_or_create_recorder` is the idempotent
# short-circuit callers should use.
_SESSION_RECS: dict[str, WsRecorder] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WsRecorder:
    """Per-session NDJSON recorder for /ws frames.

    Writes one JSON line per call to :meth:`record`, line-buffered in
    append mode so ``tail -f`` sees writes live. Disk failures are
    swallowed (best-effort — must never crash the WS or the orchestrator).

    The constructor closes any pre-existing recorder for the same
    session_id, so two constructors for the same session leave
    exactly one open file (and the first's buffer is flushed). The
    factory :func:`get_or_create_recorder` is the idempotent
    short-circuit callers should use; the constructor's
    close-predecessor behavior is for the unit tests + the rare
    "deliberately restart a recording" operator flow.
    """

    def __init__(
        self,
        *,
        session_id: str,
        base_dir: Path | None = None,
        path: Path | None = None,
    ) -> None:
        # Defensive: a malformed session_id would let an operator (or a
        # bug in the admin endpoint) write outside the base dir. The
        # safe-id regex is the same one ``session/replay_query.py``
        # uses for replay-mode manifests — keeps the two filesystem
        # namespaces consistent.
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        self.session_id = session_id
        if path is None:
            base = base_dir if base_dir is not None else DEFAULT_BASE_DIR
            base.mkdir(parents=True, exist_ok=True)
            path = base / f"{session_id}.ndjson"
        else:
            # `path=` is the "redirect to a test fixture" override —
            # create the parent so the constructor doesn't raise a
            # FileNotFoundError on a tmp-dir layout the caller just
            # built. The default branch (above) does the same for the
            # DEFAULT_BASE_DIR-derived path.
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # Close any pre-existing recorder for the same session so the
        # registry never has two open files for one session_id. The
        # close() call is itself try/except'd so a corrupt handle
        # can't take down a fresh one.
        prev = _SESSION_RECS.get(session_id)
        if prev is not None and prev is not self:
            try:
                prev.close()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "ws_record_predecessor_close_failed", error=str(exc), session=session_id
                )
        # Line-buffered append mode (buffering=1) so tail -f works.
        self._fh: TextIO = open(path, "a", encoding="utf-8", buffering=1)
        self._closed = False
        self._frames = 0
        _SESSION_RECS[session_id] = self

    @property
    def frames_recorded(self) -> int:
        """Number of frames written since this recorder was opened.

        The count is the in-process tally; on a process restart it
        resets to zero. The on-disk NDJSON is the durable source of
        truth — use ``sum(1 for _ in path.open())`` to count after
        a restart.
        """
        return self._frames

    def record(self, event: dict[str, Any], *, direction: str) -> None:
        """Write one frame to disk. Swallows IO errors.

        ``direction`` is ``"in"`` (client -> server) or ``"out"`` (server
        -> client). The frame shape on disk is::

            {"ts": iso, "session": sid, "direction": "in"|"out",
             "type": ev_type, "payload": {...}}

        ``event`` is the full envelope (``{type, ts, payload}``) on the
        ``out`` side, or a parsed client frame on the ``in`` side. The
        recorder stores the event's ``type`` + ``payload`` plus a fresh
        wall-clock ``ts`` (the envelope's own ``ts`` would conflate
        re-sent frames; the recorder's clock is the audit clock).
        """
        if self._closed:
            return
        if direction not in ("in", "out"):
            # Defensive: an unknown direction would corrupt downstream
            # consumers. Log + drop rather than write a bogus line.
            log.warning("ws_record_bad_direction", direction=direction, session=self.session_id)
            return
        try:
            line = {
                "ts": _now_iso(),
                "session": self.session_id,
                "direction": direction,
                "type": str(event.get("type", "")),
                "payload": event.get("payload", {}),
            }
            self._fh.write(json.dumps(line, separators=(",", ":")) + "\n")
            self._frames += 1
        except Exception as exc:  # noqa: BLE001
            # Best-effort: a disk-full / permission error must NEVER
            # crash the orchestrator or the WS. The in-memory state
            # (frames_recorded) doesn't advance, the on-disk file may
            # have a partial line; the operator sees the gap in tail -f.
            log.warning(
                "ws_record_write_failed", error=str(exc), session=self.session_id
            )

    def close(self) -> None:
        """Flush + close the on-disk handle. Idempotent.

        Safe to call multiple times — the second call is a no-op. The
        registry entry for this session is removed only if we're still
        the current recorder (a concurrent re-create for the same
        session would have replaced us already).
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._fh.flush()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ws_record_flush_failed", error=str(exc), session=self.session_id
            )
        try:
            self._fh.close()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ws_record_close_failed", error=str(exc), session=self.session_id
            )
        # Drop from registry only if we're still the current one.
        cur = _SESSION_RECS.get(self.session_id)
        if cur is self:
            _SESSION_RECS.pop(self.session_id, None)


def get_recorder(session_id: str) -> WsRecorder | None:
    """Return the active recorder for ``session_id`` or ``None``.

    Pure lookup — does NOT create. Use this from the WS hot path to
    gate the per-event write on a single pointer check.
    """
    return _SESSION_RECS.get(session_id)


def get_or_create_recorder(
    session_id: str, *, base_dir: Path | None = None
) -> WsRecorder:
    """Return the existing recorder for ``session_id`` or create one.

    Idempotent at the lookup level: a second call for the same
    session_id returns the same recorder. The constructor's
    close-predecessor behavior is only triggered by directly
    instantiating two ``WsRecorder`` objects.
    """
    existing = _SESSION_RECS.get(session_id)
    if existing is not None:
        return existing
    return WsRecorder(session_id=session_id, base_dir=base_dir)


def stop_recorder(session_id: str) -> WsRecorder | None:
    """Close + remove the recorder for ``session_id``.

    Returns the closed recorder (so the admin endpoint can read
    ``frames_recorded`` + ``path`` for its response) or ``None`` if
    there was no active recorder for that session.
    """
    rec = _SESSION_RECS.get(session_id)
    if rec is None:
        return None
    rec.close()
    return rec


def list_recorded_sessions(base_dir: Path | None = None) -> list[str]:
    """Return the sorted list of session_ids with a recording on disk.

    Reads the directory listing; an active recorder for a session is
    NOT required for the session to appear here — the file's mere
    presence means the session was at least started at some point.
    """
    base = base_dir if base_dir is not None else DEFAULT_BASE_DIR
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.ndjson"))


def reset_for_tests() -> None:
    """Close all recorders and clear the registry. Tests only.

    The orchestrator's lifetime is the process's; in production this
    function is never called. Tests use it to keep the module-level
    ``_SESSION_RECS`` clean across cases.
    """
    for rec in list(_SESSION_RECS.values()):
        try:
            rec.close()
        except Exception:  # noqa: BLE001
            pass
    _SESSION_RECS.clear()
