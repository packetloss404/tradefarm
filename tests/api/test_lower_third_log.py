"""Pure unit tests for the 0.17.0 lower-third ring buffer.

No FastAPI / WS machinery — these tests exercise
``LowerThirdLog`` directly so the admin endpoint's read path is
covered even when the rest of the bus is mocked. FIFO eviction and
``recent`` ordering are the two contracts that matter; the rest of
the log is exercised by the admin-endpoint integration tests in
``test_lower_third_admin.py``.
"""

from __future__ import annotations

import pytest

from tradefarm.api.lower_third_log import (
    DEFAULT_RING_SIZE,
    MAX_RECENT_LIMIT,
    MAX_TTL_SEC,
    MIN_TTL_SEC,
    LowerThirdLog,
    VALID_LOWER_THIRD_COLORS,
)


def test_log_rejects_invalid_max_size() -> None:
    """``max_size < 1`` is a programmer error, not a runtime condition."""
    with pytest.raises(ValueError):
        LowerThirdLog(max_size=0)


def test_record_assigns_uuid_when_id_omitted() -> None:
    """Each recorded entry has a server-assigned uuid hex id when the
    caller doesn't pass one. Two calls produce two distinct ids.
    """
    log = LowerThirdLog()
    e1 = log.record(title="hi")
    e2 = log.record(title="hi")
    assert e1.id != e2.id
    assert len(e1.id) > 0


def test_record_uses_caller_supplied_id() -> None:
    """An explicit id is preserved verbatim (used by replay so the
    caller's audit trail stays intact)."""
    log = LowerThirdLog()
    e = log.record(title="hi", id="caller-supplied-1")
    assert e.id == "caller-supplied-1"


def test_record_clamps_ttl_into_allowed_range() -> None:
    """TTL outside [MIN_TTL_SEC, MAX_TTL_SEC] is clamped on the way
    in so the ring never holds an unusable value. The clamp matches
    the stream-side clamp in ``useStreamCommands.setBannerSafe``.
    """
    log = LowerThirdLog()
    too_low = log.record(title="t", ttl_sec=0)
    too_high = log.record(title="t", ttl_sec=999)
    in_range = log.record(title="t", ttl_sec=8)
    assert too_low.ttl_sec == MIN_TTL_SEC
    assert too_high.ttl_sec == MAX_TTL_SEC
    assert in_range.ttl_sec == 8


def test_record_drops_unknown_color() -> None:
    """A color not in the allowlist is recorded as ``None`` so the
    stream's color guard doesn't fail at render time. The endpoint
    also 400s on this case — the log is the backstop."""
    log = LowerThirdLog()
    e = log.record(title="t", color="purple")  # type: ignore[arg-type]
    assert e.color is None
    # Sanity: a valid color sticks.
    e2 = log.record(title="t", color="profit")
    assert e2.color == "profit"


def test_recent_returns_newest_first() -> None:
    """``recent()`` is reverse-chronological so the dashboard's list
    shows the freshest push at the top without extra sorting."""
    log = LowerThirdLog()
    log.record(title="first")
    log.record(title="second")
    log.record(title="third")
    items = log.recent()
    titles = [it["title"] for it in items]
    assert titles == ["third", "second", "first"]


def test_recent_respects_limit() -> None:
    """``recent(limit=N)`` returns at most N items, newest-first."""
    log = LowerThirdLog()
    for i in range(5):
        log.record(title=f"t{i}")
    assert [it["title"] for it in log.recent(limit=2)] == ["t4", "t3"]


def test_recent_clamps_limit_to_max_recent_limit() -> None:
    """Limit above the per-call cap is silently clamped so a
    runaway dashboard (limit=10000) can't trigger a multi-MB
    response. The cap is larger than the default ring so this only
    matters for malformed callers."""
    log = LowerThirdLog(max_size=MAX_RECENT_LIMIT * 2)
    for i in range(MAX_RECENT_LIMIT + 5):
        log.record(title=f"t{i}")
    items = log.recent(limit=MAX_RECENT_LIMIT * 10)
    assert len(items) == MAX_RECENT_LIMIT


def test_recent_rejects_negative_limit() -> None:
    """A negative limit is a programmer error; raise so the
    endpoint can translate to a 400 instead of silently returning
    everything."""
    log = LowerThirdLog()
    with pytest.raises(ValueError):
        log.recent(limit=-1)


def test_ring_buffer_evicts_oldest_when_full() -> None:
    """FIFO eviction. After exceeding ``max_size`` the oldest entries
    are silently dropped — the log is a fixed-size window."""
    log = LowerThirdLog(max_size=3)
    for i in range(5):
        log.record(title=f"t{i}")
    titles = [it["title"] for it in log.recent()]
    assert titles == ["t4", "t3", "t2"]
    assert len(log) == 3


def test_recent_omits_evicted_entries() -> None:
    """Sanity: a fresh log with a small cap evicts as expected, and
    a ``recent()`` query after eviction doesn't surface the dropped
    items."""
    log = LowerThirdLog(max_size=2)
    log.record(title="drop-me-1")
    log.record(title="drop-me-2")
    log.record(title="keep-1")
    log.record(title="keep-2")
    titles = [it["title"] for it in log.recent()]
    assert titles == ["keep-2", "keep-1"]


def test_default_ring_size_matches_spec() -> None:
    """Guard against a future bump to DEFAULT_RING_SIZE that breaks
    the documented contract (the recent endpoint's max clamp assumes
    the default 200)."""
    assert DEFAULT_RING_SIZE == 200


def test_valid_colors_set_is_exactly_three() -> None:
    """The wire spec says three colors; if someone adds a fourth
    the stream's exhaustive check needs an update too, and this
    test forces them to revisit the contract together."""
    assert VALID_LOWER_THIRD_COLORS == frozenset({"profit", "loss", "neutral"})
