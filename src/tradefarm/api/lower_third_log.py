"""In-memory ring buffer for operator-pushed lower-thirds.

0.17.0 — `POST /admin/lower_third/push` records into this log so the
dashboard can show a "recent" list and offer a "replay" button for
each row. The buffer is intentionally in-memory only: a process restart
evicts the audit trail, and the operator is expected to re-push if they
want continuity across restarts. There is no DB persistence because the
content of a lower-third is transient (operator typed it a few minutes
ago) and the dashboard doesn't need a long history — last ~200 is plenty
to cover the "I want to show that again" case.

The buffer is FIFO with a hard cap. Older entries are evicted silently
when a new push overflows the cap; the dashboard only ever queries
`recent(limit)` so eviction is invisible to clients.
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# Allowed accent colors. The set is small and intentionally distinct from
# the broader broadcast `color` enum on `BroadcastMoment` so the lower-third
# payload can be a strict literal in pydantic. Reject anything else at the
# endpoint boundary instead of letting an unknown color fall through to a
# default visual.
VALID_LOWER_THIRD_COLORS: frozenset[str] = frozenset({"profit", "loss", "neutral"})

# Lower / upper bounds for `ttl_sec`. Mirrors the stream-side clamp in
# `useStreamCommands.setBannerSafe` (1..120); keeping the bounds symmetric
# on both sides means a request the backend accepts can never be rejected
# by the stream's clamp.
MIN_TTL_SEC = 1
MAX_TTL_SEC = 120

# Default + max ring size. `recent(limit)` accepts up to MAX_RECENT_LIMIT
# items in one call; the ring itself can hold up to `max_size` events
# (default 200 — the test suite exercises a 250-push overflow).
MAX_RECENT_LIMIT = 200
DEFAULT_RING_SIZE = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LowerThirdEntry:
    """One recorded lower-third push.

    The `id` is generated server-side (uuid hex) when the operator omits
    one in the request body. `pushed_at` is wall-clock ISO-8601 so the
    dashboard can show a relative age without server help.
    """

    id: str
    title: str
    subtitle: str
    ttl_sec: int
    color: str | None
    pushed_at: str

    def to_payload(self) -> dict[str, Any]:
        """Shape returned by `GET /admin/lower_third/recent`.

        Kept as a hand-rolled dict (not `asdict`) so the wire format is
        stable even if we add helper fields to the dataclass later.
        """
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "ttl_sec": self.ttl_sec,
            "color": self.color,
            "pushed_at": self.pushed_at,
        }


@dataclass
class LowerThirdLog:
    """Bounded FIFO ring of recent lower-thirds.

    `max_size` is enforced by `collections.deque(maxlen=...)`, so an
    append that overflows the cap silently evicts the oldest entry.
    Single-threaded use only — the admin endpoint is called from the
    FastAPI request handler; we don't need a lock because asyncio
    serializes that handler against itself.
    """

    max_size: int = DEFAULT_RING_SIZE
    _entries: deque[LowerThirdEntry] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._entries = deque(maxlen=self.max_size)

    def __len__(self) -> int:
        return len(self._entries)

    def record(
        self,
        *,
        title: str,
        subtitle: str = "",
        ttl_sec: int = 8,
        color: str | None = None,
        id: str | None = None,
    ) -> LowerThirdEntry:
        """Append a new entry, return the recorded row (with its server-assigned id).

        The caller is expected to have validated the fields already
        (empty-title / out-of-range ttl / unknown color). We re-clamp
        `ttl_sec` here defensively so a direct call from a future caller
        (e.g. a debug tool) can't poison the log with an unusable value.
        """
        clamped_ttl = max(MIN_TTL_SEC, min(MAX_TTL_SEC, int(ttl_sec)))
        entry = LowerThirdEntry(
            id=id or uuid.uuid4().hex,
            title=str(title),
            subtitle=str(subtitle) if subtitle else "",
            ttl_sec=clamped_ttl,
            color=color if color in VALID_LOWER_THIRD_COLORS else None,
            pushed_at=_now_iso(),
        )
        self._entries.append(entry)
        return entry

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return the most-recent entries, newest-first.

        `limit=None` returns the full buffer. Values larger than
        `MAX_RECENT_LIMIT` are clamped to the cap; negatives raise
        ValueError (the endpoint translates that to a 400).
        """
        if limit is None:
            take = len(self._entries)
        else:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            take = min(int(limit), MAX_RECENT_LIMIT)
        # deque is oldest-first; we want newest-first for the dashboard list.
        # Slicing the rightmost N is O(N) (deque doesn't support negative
        # slicing) but N is bounded at 200 so it's fine.
        window: Iterable[LowerThirdEntry] = list(self._entries)[-take:] if take else []
        return [e.to_payload() for e in reversed(list(window))]


# Process-global log. The admin endpoint reads / writes this singleton;
# tests that want isolation should construct their own `LowerThirdLog()`
# rather than patching this.
log = LowerThirdLog()


def build_log_payload(entry: LowerThirdEntry) -> dict[str, Any]:
    """Return the response body for a fresh push (camel / snake parity)."""
    body = asdict(entry)
    return body
