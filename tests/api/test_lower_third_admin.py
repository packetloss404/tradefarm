"""Tests for the 0.17.0 ``POST /admin/lower_third/push`` and
``GET /admin/lower_third/recent`` admin endpoints.

The push endpoint is responsible for two things:
1. Validating the request body (empty title, bad color, out-of-range
   ttl) and 400-ing on the first failure. The body shape is also
   enforced by pydantic — missing required fields yield 422.
2. Publishing a ``lower_third`` event on the WS bus with the canonical
   payload shape, AND recording the entry in the in-memory ring
   buffer so ``GET /admin/lower_third/recent`` can return it.

The recent endpoint is responsible for:
1. Newest-first ordering.
2. ``limit`` clamping (and 400 on negative).
3. Ring-buffer FIFO eviction at the documented cap.

The endpoint tests use the FastAPI TestClient and a fresh
``LowerThirdLog`` instance patched in for isolation — the process-
global singleton in ``lower_third_log.log`` is shared across tests,
and we don't want a test's leftover entries leaking into the next.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradefarm.api import lower_third_log as ltl_mod
from tradefarm.api.events import EVENT_TYPE_LOWER_THIRD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_log(monkeypatch: pytest.MonkeyPatch):
    """Patch the process-global log with a fresh instance per test.

    The endpoint reads ``lower_third_log.log`` at request time, so
    swapping the module attribute is enough to redirect writes.
    """
    fresh = ltl_mod.LowerThirdLog()
    monkeypatch.setattr(ltl_mod, "log", fresh)
    return fresh


@pytest.fixture
def push_client(fresh_log) -> TestClient:
    """A bare FastAPI TestClient.

    No ``with`` context — the lower-third endpoint doesn't touch the
    orchestrator, the DB, or the broadcast arbiter. The lifespan
    would just slow the test down (orchestrator init does a
    ``persist_initial_state`` write).
    """
    from tradefarm.api.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: push
# ---------------------------------------------------------------------------


def test_push_lower_third_publishes_event(
    push_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POST /admin/lower_third/push`` records the entry and publishes
    a ``lower_third`` WS event with the canonical payload shape (id,
    title, subtitle, ttl_sec, color).

    The endpoint imports ``publish_event`` lazily inside the handler
    (so the WS bus isn't required at import time), so we patch the
    module-global reference and capture the call. This avoids
    spinning up a separate subscriber loop in the test client which
    runs synchronously.
    """
    from tradefarm.api import events as _events

    captured: list[tuple[str, dict]] = []

    async def _fake_publish(event_type: str, payload: dict) -> None:
        captured.append((event_type, payload))

    monkeypatch.setattr(_events, "publish_event", _fake_publish)

    r = push_client.post(
        "/admin/lower_third/push",
        json={
            "title": "Back from break",
            "subtitle": "Resuming in 30s",
            "ttl_sec": 12,
            "color": "profit",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Back from break"
    assert body["subtitle"] == "Resuming in 30s"
    assert body["ttl_sec"] == 12
    assert body["color"] == "profit"
    # id is a uuid hex (32 chars) — not empty.
    assert isinstance(body["id"], str)
    assert len(body["id"]) >= 16

    # The publish was called once with the right shape.
    assert len(captured) == 1
    event_type, payload = captured[0]
    assert event_type == EVENT_TYPE_LOWER_THIRD
    assert payload["id"] == body["id"]
    assert payload["title"] == "Back from break"
    assert payload["subtitle"] == "Resuming in 30s"
    assert payload["ttl_sec"] == 12
    assert payload["color"] == "profit"


def test_push_lower_third_rejects_empty_title(push_client: TestClient) -> None:
    """Empty title (or whitespace-only) is a 400, not a 200 with an
    empty string on the bus. The endpoint strips before checking
    so ``"   "`` doesn't squeak through."""
    for empty in ("", "   ", "\t\n"):
        r = push_client.post("/admin/lower_third/push", json={"title": empty})
        assert r.status_code == 400, f"expected 400 for title={empty!r}, got {r.status_code}"
        assert "title" in r.json()["detail"].lower()


def test_push_lower_third_rejects_invalid_color(push_client: TestClient) -> None:
    """An unknown color value is a 400. The stream's color guard
    only handles the three documented values, so silently coercing
    a typo to a default would let a UI bug render forever."""
    r = push_client.post(
        "/admin/lower_third/push",
        json={"title": "hi", "color": "purple"},
    )
    # ``color`` is `Literal[...]` in the pydantic model so pydantic
    # rejects unknown values with 422; the endpoint never sees them.
    # Both 400 and 422 are acceptable rejection codes per the spec;
    # the wire spec document is silent on the specific code.
    assert r.status_code in (400, 422), f"got {r.status_code}"


def test_push_lower_third_rejects_out_of_range_ttl(push_client: TestClient) -> None:
    """ttl_sec outside [1, 120] is rejected. The stream's clamp would
    silently coerce, but the endpoint rejects so the operator
    sees the typo in the response, not in the stream."""
    for bad in (0, 121, 200, -5):
        r = push_client.post(
            "/admin/lower_third/push",
            json={"title": "hi", "ttl_sec": bad},
        )
        assert r.status_code in (400, 422), f"expected rejection for ttl_sec={bad}, got {r.status_code}"


def test_push_lower_third_accepts_boundary_ttl(push_client: TestClient) -> None:
    """1 and 120 are inclusive — the boundaries are valid values."""
    for ttl in (1, 120):
        r = push_client.post(
            "/admin/lower_third/push",
            json={"title": "hi", "ttl_sec": ttl},
        )
        assert r.status_code == 200
        assert r.json()["ttl_sec"] == ttl


def test_push_lower_third_omitted_optional_fields_use_defaults(
    push_client: TestClient,
) -> None:
    """A request with only ``title`` is accepted; the other fields
    default to subtitle="", ttl_sec=8, color=None, and the response
    echoes those defaults so the dashboard's toast can render
    without an undefined check."""
    r = push_client.post("/admin/lower_third/push", json={"title": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["subtitle"] == ""
    assert body["ttl_sec"] == 8
    assert body["color"] is None


def test_push_lower_third_records_in_recent_log(push_client: TestClient) -> None:
    """The endpoint appends to the in-memory ring buffer so a
    follow-up ``GET /admin/lower_third/recent`` returns the entry."""
    r1 = push_client.post(
        "/admin/lower_third/push", json={"title": "first"}
    )
    r2 = push_client.post(
        "/admin/lower_third/push", json={"title": "second"}
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    recent = push_client.get("/admin/lower_third/recent")
    assert recent.status_code == 200
    items = recent.json()["items"]
    titles = [it["title"] for it in items]
    # Newest-first ordering.
    assert titles == ["second", "first"]


# ---------------------------------------------------------------------------
# Tests: recent
# ---------------------------------------------------------------------------


def test_recent_lower_thirds_returns_newest_first(push_client: TestClient) -> None:
    """Three pushes land in newest-first order. The third push's
    title is the first element of the response array."""
    push_client.post("/admin/lower_third/push", json={"title": "t1"})
    push_client.post("/admin/lower_third/push", json={"title": "t2"})
    push_client.post("/admin/lower_third/push", json={"title": "t3"})

    r = push_client.get("/admin/lower_third/recent")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3
    assert [it["title"] for it in items] == ["t3", "t2", "t1"]


def test_recent_lower_thirds_respects_limit(push_client: TestClient) -> None:
    """``?limit=N`` returns at most N items, newest-first."""
    for i in range(5):
        push_client.post("/admin/lower_third/push", json={"title": f"t{i}"})

    r = push_client.get("/admin/lower_third/recent?limit=2")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert [it["title"] for it in items] == ["t4", "t3"]


def test_recent_lower_thirds_rejects_negative_limit(push_client: TestClient) -> None:
    """A negative ``limit`` is a 400, not a silent coercion. The
    endpoint should fail loud so a buggy UI doesn't render a
    confusing 500 from the underlying ``ValueError``."""
    r = push_client.get("/admin/lower_third/recent?limit=-1")
    assert r.status_code == 400
    assert "limit" in r.json()["detail"].lower()


def test_recent_lower_thirds_ring_buffer_caps_at_max(
    fresh_log: "ltl_mod.LowerThirdLog",
    push_client: TestClient,
) -> None:
    """The ring buffer evicts the oldest entries when the cap is
    exceeded. With a 200-row cap and 250 pushes, only the most
    recent 200 are retained; the oldest 50 are dropped.

    We install a smaller cap (200) for test speed, then push 250
    and assert exactly 200 are returned and the first 50 are gone.
    """
    # Re-create with the spec'd cap and re-patch.
    fresh = ltl_mod.LowerThirdLog(max_size=200)
    ltl_mod.log = fresh

    for i in range(250):
        r = push_client.post(
            "/admin/lower_third/push", json={"title": f"t{i:03d}"}
        )
        assert r.status_code == 200

    # Read the log directly to confirm the cap is enforced.
    assert len(fresh) == 200
    items = fresh.recent()
    assert len(items) == 200
    # Newest-first: the last push is first.
    assert items[0]["title"] == "t249"
    # The 200th-from-the-top is t50 — pushes t0..t49 are evicted.
    assert items[-1]["title"] == "t050"
    titles = {it["title"] for it in items}
    assert "t000" not in titles
    assert "t049" not in titles


def test_recent_lower_thirds_clamps_huge_limit(push_client: TestClient) -> None:
    """A limit above MAX_RECENT_LIMIT is silently clamped so a
    runaway dashboard doesn't get a multi-MB response."""
    for i in range(3):
        push_client.post("/admin/lower_third/push", json={"title": f"t{i}"})
    r = push_client.get("/admin/lower_third/recent?limit=10000")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3


def test_recent_default_limit(push_client: TestClient) -> None:
    """``GET /admin/lower_third/recent`` (no ``limit``) returns up
    to the default cap (50). Pushing 60 and querying without a
    limit returns 50, newest-first."""
    for i in range(60):
        push_client.post("/admin/lower_third/push", json={"title": f"t{i:03d}"})
    r = push_client.get("/admin/lower_third/recent")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 50
    # Newest is t059.
    assert items[0]["title"] == "t059"
