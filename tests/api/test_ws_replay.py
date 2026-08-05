"""End-to-end test of the replay chain the headless renderer depends on.

The full chain runs through four layers:

  1. tradefarm.render.headless.build_url()       — produces a URL the
     stream/ app will navigate to
  2. stream/src/shared/replayMode.ts (URLSearchParams parsing) — the
     stream reads the same URL into a {sessionId, at, until, speed, scene}
     dict and opens a WS with a replay frame
  3. tradefarm.api.ws._stream_replay()           — receives the frame,
     loads the manifest, calls events_in_window(), and pumps the
     matched events back as WS envelopes
  4. stream/src/shared/useLiveEvents.ts          — validates the
     envelope shape `{type, ts, payload}` before handing it to the
     scene

The unit tests for (1) live in tests/render/test_headless.py, the unit
tests for (3)'s pieces live in tests/session/test_replay_query.py, but
nothing ties the chain together — until now a regression in URL→parsed
query handling, or in events_in_window→envelope conversion at the WS
boundary, would slip through.

This module fixes that with one shape contract per layer and one
end-to-end test that drives all four.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from tradefarm.api.main import app
from tradefarm.render.headless import build_url
from tradefarm.session import replay_query


OPEN = datetime(2026, 5, 19, 13, 30, tzinfo=timezone.utc)
CLOSE = datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc)


# ----- layer 1 fixtures ---------------------------------------------------


def _fill_event(
    *,
    agent_id: int,
    t: datetime,
    symbol: str = "AAPL",
    side: str = "buy",
    qty: float = 10.0,
    price: float = 100.0,
) -> dict[str, Any]:
    return {
        "t": t.isoformat(),
        "kind": "fill",
        "agent_id": agent_id,
        "agent_name": f"agent_{agent_id}",
        "payload": {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "notional": abs(qty * price),
            "reason": "test",
        },
    }


def _decision_event(
    *,
    agent_id: int,
    t: datetime,
    kind: str = "entry",
    symbol: str = "AAPL",
    content: str = "buy reason",
) -> dict[str, Any]:
    return {
        "t": t.isoformat(),
        "kind": "decision",
        "agent_id": agent_id,
        "agent_name": f"agent_{agent_id}",
        "payload": {"kind": kind, "symbol": symbol, "content": content, "metadata": "{}"},
    }


def _write_manifest(tmp_path: Path, session_id: str, events: list[dict[str, Any]]) -> Path:
    """Materialise a manifest.json under ``<sessions_dir>/<session_id>/``
    the way session/run.py does, so the WS layer can find it via the
    default loader (which uses out/sessions/ as its root)."""
    base = tmp_path
    d = base / session_id
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "session_id": session_id,
        "date_range": ["2026-05-19", "2026-05-19"],
        "started_at": OPEN.isoformat(),
        "ended_at": CLOSE.isoformat(),
        "trading_days": ["2026-05-19"],
        "tick_count": 1,
        "fill_count": sum(1 for e in events if e["kind"] == "fill"),
        "agents_active": len({e["agent_id"] for e in events}),
        "events": events,
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d / "manifest.json"


# ---------------------------------------------------------------------------
# Layer 1: headless URL -> stream URLSearchParams contract
# ---------------------------------------------------------------------------
#
# The headless emits a URL like
#   http://localhost:5180/?replay=s_abc&at=...&until=...&scene=hero&speed=60.0
# and the stream app reads the same URL via URLSearchParams. The key
# contract: every param the headless sets must be readable back under
# the same name, and the values must round-trip without surprise.
# Regressing this would silently break every capture.


@pytest.mark.parametrize(
    "stream_base",
    [
        "http://localhost:5180/",   # default — trailing slash
        "http://localhost:5180",    # no trailing slash
    ],
)
def test_headless_url_round_trips_into_stream_querystring(stream_base: str):
    at = "2026-05-19T14:00:00+00:00"
    until = "2026-05-19T14:00:30+00:00"
    url = build_url(
        stream_base=stream_base,
        session_id="s_abc",
        at=at,
        until=until,
        scene="hero",
        speed=60.0,
    )
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    # Stream URLSearchParams -> replayMode.ts reads exactly these keys.
    assert qs["replay"] == ["s_abc"]
    assert qs["at"] == [at]
    assert qs["until"] == [until]
    assert qs["scene"] == ["hero"]
    assert qs["speed"] == ["60.0"]


def test_headless_url_speed_default_is_what_stream_expects():
    """The stream's replayMode.ts defaults speed to 60 when the param
    is missing; the headless writes ``speed=60.0`` explicitly. Belt
    and braces: confirm the headless side stays on its declared
    default of 60.0 so a drift gets caught here instead of at the
    renderer's side."""
    url = build_url(
        stream_base="http://localhost:5180/",
        session_id="s_x",
        at="2026-05-19T14:00:00+00:00",
        until="2026-05-19T14:00:30+00:00",
        scene="hero",
        speed=60.0,
    )
    qs = parse_qs(urlparse(url).query)
    assert float(qs["speed"][0]) == 60.0


# ---------------------------------------------------------------------------
# Layer 2: events_in_window -> manifest_event_to_ws_envelope contract
# ---------------------------------------------------------------------------
#
# The WS pump calls events_in_window(manifest, at=at, until=until) and
# then converts each event via manifest_event_to_ws_envelope. The
# frontend's useLiveEvents validator expects envelopes of shape
# {type, ts, payload}. This is tested indirectly across two modules
# today; the parametrised matrix below pins the shape so a rename or
# a type-tag drift can't slip through.


def test_manifest_event_to_ws_envelope_keeps_canonical_types():
    """Every shape manifest_event_to_ws_envelope can emit must use the
    canonical `{type, ts, payload}` envelope the frontend validates.
    Pinned here so a future addition has to update the test rather
    than silently diverging."""
    fill = _fill_event(agent_id=1, t=OPEN, symbol="AAPL", side="buy", qty=5, price=100)
    decision = _decision_event(agent_id=2, t=OPEN, kind="entry", symbol="MSFT", content="ok")

    for ev in (fill, decision):
        env = replay_query.manifest_event_to_ws_envelope(ev)
        assert env is not None
        assert set(env.keys()) == {"type", "ts", "payload"}
        assert env["ts"] == ev["t"]


def test_events_in_window_preserves_manifest_order():
    """The WS pump relies on events arriving in manifest order so
    the per-event wall sleep (`(t_next - t_prev) / speed`) makes
    sense. The function does NOT sort — it returns whatever the
    manifest stored. A future change that adds ``sorted(..., key=...)``
    would break the pacing for non-monotonic inputs."""
    events = [
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=5), symbol="AAPL", price=101),
        _fill_event(agent_id=2, t=OPEN + timedelta(minutes=1), symbol="AAPL", price=100),
        _fill_event(agent_id=3, t=OPEN + timedelta(minutes=10), symbol="AAPL", price=102),
    ]
    manifest = {
        "session_id": "s_ord",
        "started_at": OPEN.isoformat(),
        "ended_at": CLOSE.isoformat(),
        "events": events,
    }
    window = replay_query.events_in_window(manifest, at=OPEN, until=CLOSE)
    # Same order as the manifest — NOT sorted by `t`.
    assert [e["payload"]["price"] for e in window] == [101, 100, 102]


def test_events_in_window_is_inclusive_on_both_ends():
    """Boundary semantics. The contract is inclusive on both ends
    (matches the existing ``test_events_in_window_slices_inclusive``
    in tests/session/test_replay_query.py). The headless builder
    computes ``until = at + duration`` so in practice adjacent beat
    windows can share a boundary event — accepted behaviour for
    this round; the manifest pump emits each in real time and the
    renderer stitches the clips, so the visible duplicate is
    cosmetic. A flip in either direction would change the captured
    clip content; this test pins the current contract."""
    at = OPEN + timedelta(minutes=5)
    until = OPEN + timedelta(minutes=15)
    events = [
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=4), price=99),    # before
        _fill_event(agent_id=1, t=at, price=100),                            # at
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=10), price=101),  # middle
        _fill_event(agent_id=1, t=until, price=102),                          # at_until
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=20), price=103),  # after
    ]
    manifest = {"events": events}
    window = replay_query.events_in_window(manifest, at=at, until=until)
    assert [e["payload"]["price"] for e in window] == [100, 101, 102]


# ---------------------------------------------------------------------------
# Layer 3: full WS round-trip via the real /ws endpoint
# ---------------------------------------------------------------------------
#
# We use Starlette's TestClient (which FastAPI's TestClient wraps)
# with `client.websocket_connect("/ws")` to drive the real handler.
# No Playwright, no actual stream/ Vite — just the WS contract that
# the headless + stream both speak.


def _consume_replay(
    client: TestClient, session_id: str, at: str, until: str, *, speed: float = 60.0
) -> list[dict[str, Any]]:
    """Open a WS, send the replay frame the stream's LiveContext sends,
    and read envelopes until the server signals done or closes."""
    sent: list[dict[str, Any]] = []
    with client.websocket_connect("/ws") as ws:
        # First frame: server sends a hello with `subscribed: true`.
        hello_live = ws.receive_json()
        assert hello_live["type"] == "hello"
        assert hello_live["payload"].get("subscribed") is True

        # The stream's LiveContext sends the replay frame on open.
        ws.send_text(
            json.dumps(
                {
                    "type": "replay",
                    "session_id": session_id,
                    "at": at,
                    "until": until,
                    "speed": speed,
                }
            )
        )

        # Drain frames. The pump closes the WS after the done envelope,
        # so a receive_json raising WebSocketDisconnect is the exit
        # signal. We collect until then.
        while True:
            try:
                frame = ws.receive_json()
            except Exception:  # noqa: BLE001 — WebSocketDisconnect on close
                break
            sent.append(frame)
            if frame.get("type") == "hello" and frame.get("payload", {}).get("done") is True:
                # Server sends a final "hello" with `done: true`; one
                # more receive will close.
                continue
    return sent


def test_ws_replay_full_chain_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The big one: write a real manifest under out/sessions/, point
    the headless URL builder at it, build the same URL the stream app
    would see, and run a real WS handshake end-to-end. The envelopes
    we collect should match the manifest's windowed events in order,
    translated via the canonical manifest_event_to_ws_envelope path."""
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)

    session_id = "s_chain"
    at = OPEN + timedelta(minutes=5)
    until = OPEN + timedelta(minutes=20)
    events = [
        _decision_event(agent_id=1, t=OPEN + timedelta(minutes=2)),    # before window
        _fill_event(agent_id=1, t=at, symbol="AAPL", side="buy", qty=5, price=100),  # at
        _decision_event(agent_id=2, t=OPEN + timedelta(minutes=8), kind="entry",
                        symbol="MSFT", content="read"),                            # middle
        _fill_event(agent_id=2, t=OPEN + timedelta(minutes=12), symbol="MSFT", side="buy",
                    qty=2, price=200),                                              # middle
        _decision_event(agent_id=3, t=OPEN + timedelta(minutes=30)),   # after window
    ]
    _write_manifest(tmp_path, session_id, events)

    # Layer 1: build the URL the headless would navigate to.
    url = build_url(
        stream_base="http://localhost:5180/",
        session_id=session_id,
        at=at.isoformat(),
        until=until.isoformat(),
        scene="hero",
        speed=60.0,
    )
    # Layer 2 (pre-flight): the stream app would parse this same URL.
    qs = parse_qs(urlparse(url).query)
    assert qs["replay"] == [session_id]

    # Layer 3: real WS handshake.
    client = TestClient(app)
    frames = _consume_replay(
        client,
        session_id=qs["replay"][0],
        at=qs["at"][0],
        until=qs["until"][0],
        speed=float(qs["speed"][0]),
    )

    # First frame is the replay hello with the event count.
    hello = frames[0]
    assert hello["type"] == "hello"
    assert hello["payload"]["replay"] is True
    assert hello["payload"]["session_id"] == session_id
    # events_in_window is inclusive on both ends: the event at `at`
    # and the two middle events all fall in the window. The
    # decision at OPEN+30min is excluded (after `until`).
    assert hello["payload"]["event_count"] == 3

    # The envelopes after the hello should be the windowed events in
    # manifest order, translated to the canonical shape.
    envelopes = [f for f in frames[1:] if f.get("type") in ("fill", "agent_decisions_batch")]
    assert len(envelopes) == 3

    # First: a fill at `at` (the boundary event).
    assert envelopes[0]["type"] == "fill"
    assert envelopes[0]["payload"]["symbol"] == "AAPL"
    assert envelopes[0]["payload"]["side"] == "buy"
    assert envelopes[0]["ts"] == at.isoformat()

    # Second: a decision at OPEN+8m.
    assert envelopes[1]["type"] == "agent_decisions_batch"
    assert envelopes[1]["payload"]["decisions"][0]["symbol"] == "MSFT"
    assert envelopes[1]["ts"] == (OPEN + timedelta(minutes=8)).isoformat()

    # Third: a fill at OPEN+12m.
    assert envelopes[2]["type"] == "fill"
    assert envelopes[2]["payload"]["symbol"] == "MSFT"
    assert envelopes[2]["ts"] == (OPEN + timedelta(minutes=12)).isoformat()

    # Last frame is the done sentinel.
    done = [f for f in frames if f.get("type") == "hello" and f.get("payload", {}).get("done") is True]
    assert len(done) == 1


def test_ws_replay_rejects_path_traversal_in_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The WS endpoint must validate session_id before touching disk —
    a malicious client could otherwise read arbitrary manifest.json
    files anywhere reachable from cwd."""
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # subscribed hello
        ws.send_text(
            json.dumps(
                {
                    "type": "replay",
                    "session_id": "../etc/passwd",
                    "at": OPEN.isoformat(),
                    "until": until_iso(OPEN),
                    "speed": 60.0,
                }
            )
        )
        err = ws.receive_json()
        assert err["type"] == "hello"
        assert err["payload"]["replay"] is True
        assert "invalid session_id" in err["payload"]["error"]


def test_ws_replay_missing_manifest_returns_error_hello(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A non-existent session_id must produce a clear error frame,
    not a 500 / stack trace. The stream app's LiveContext would log
    this and bail; the test asserts the contract is clean."""
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text(
            json.dumps(
                {
                    "type": "replay",
                    "session_id": "s_does_not_exist",
                    "at": OPEN.isoformat(),
                    "until": until_iso(OPEN),
                    "speed": 60.0,
                }
            )
        )
        err = ws.receive_json()
        assert err["type"] == "hello"
        assert err["payload"]["replay"] is True
        assert "no manifest" in err["payload"]["error"]


def test_ws_replay_invalid_timestamps_return_error_hello(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A bad ISO timestamp must not crash the pump — the contract is
    a structured error envelope the LiveContext can render."""
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)
    _write_manifest(tmp_path, "s_garbage", [_fill_event(agent_id=1, t=OPEN)])

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text(
            json.dumps(
                {
                    "type": "replay",
                    "session_id": "s_garbage",
                    "at": "not-an-iso-timestamp",
                    "until": until_iso(OPEN),
                    "speed": 60.0,
                }
            )
        )
        err = ws.receive_json()
        assert err["type"] == "hello"
        assert err["payload"]["replay"] is True
        assert "invalid" in err["payload"]["error"]


def test_ws_replay_speed_zero_means_no_wall_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``speed <= 0`` collapses the wall-sleep entirely; the pump
    should still emit all the window's envelopes in chronological
    order. The contract is what `_stream_replay`'s docstring promises;
    a regression here would make 'as-fast-as-possible' mode silently
    lose events."""
    monkeypatch.setattr(replay_query, "DEFAULT_SESSIONS_DIR", tmp_path)
    session_id = "s_fast"
    at = OPEN
    until = OPEN + timedelta(minutes=10)
    events = [
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=1)),
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=2)),
        _fill_event(agent_id=1, t=OPEN + timedelta(minutes=3)),
    ]
    _write_manifest(tmp_path, session_id, events)

    client = TestClient(app)
    frames = _consume_replay(client, session_id, at.isoformat(), until.isoformat(), speed=0)
    envelopes = [f for f in frames if f.get("type") == "fill"]
    assert len(envelopes) == 3
    # Chronological order preserved even with no sleep.
    assert [e["ts"] for e in envelopes] == sorted(e["ts"] for e in envelopes)


# ----- helpers ------------------------------------------------------------


def until_iso(at: datetime) -> str:
    return (at + timedelta(minutes=10)).isoformat()
