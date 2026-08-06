"""In-memory bounded ledger of per-agent decision-lab entries.

0.19.0 — the operator-facing dashboard wanted a *persistent* feed of
LLM decisions (not just the latest per-agent view that the stream's
BrainScene / dashboard's BrainPanel already provide). The WS event
``agent_decisions_batch`` is published per tick (one envelope per 100
agents); the ledger is the rolling server-side store that backs the
new ``GET /decisions/recent`` endpoint so a freshly-reloaded page
sees the recent history before any new tick lands.

Design notes:

- Bounded ``deque`` (max 200 entries) — a 100-agent run at the default
  30s tick interval produces ~1200 entries/hour. 200 covers ~10
  minutes of decision-lab activity, which is what an operator wants
  for "what was the LLM thinking about 5 min ago?" review. Older
  entries are silently dropped (the same pattern as
  ``BroadcastRecapLedger``).
- Per-tick dedup: if a single tick's batch is recorded twice (e.g. a
  WS subscriber that subscribes after the first publish then resends
  the same envelope), the second record is a no-op. ``tick_id`` is
  the dedup key.
- ``record_batch`` is the only mutator; tests use it to seed.
- Query methods return plain dicts (not dataclasses) so the FastAPI
  serializer round-trips them without a custom encoder.

This module is intentionally dependency-free. The event-bus
subscriber that calls ``record_batch`` lives in ``api/main.py``;
the ledger itself is a pure data structure.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecentDecisionsLedger:
    """Bounded in-memory store of the most recent agent decisions.

    A single ``record_batch(batch)`` call appends every decision in
    the batch to the ring. Query methods are read-only and return
    plain dicts matching the on-the-wire ``agent_decisions_batch``
    payload shape (so a FastAPI handler can serialize directly).

    Parameters
    ----------
    max_entries:
        Hard cap on stored entries. Defaults to 200, which covers
        ~10 minutes of 100-agent activity at 30s tick interval.
    """

    max_entries: int = 200
    _entries: deque[dict[str, Any]] = field(init=False, repr=False)
    _seen_tick_ids: deque[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._entries = deque(maxlen=self.max_entries)
        # Track the last ~64 tick_ids we've seen so a replayed batch
        # is dropped without a linear scan. Capped at 2x max_entries
        # so memory stays bounded even under heavy replay load.
        self._seen_tick_ids = deque(maxlen=max(64, self.max_entries // 4))

    def __len__(self) -> int:
        return len(self._entries)

    def record_batch(self, batch: dict[str, Any]) -> int:
        """Append every decision in ``batch`` to the ledger.

        Returns the number of decisions actually appended (0 if the
        batch was empty or its ``tick_id`` was already recorded).

        The dedup contract: a batch is keyed by ``tick_id``. If we
        have already recorded that ``tick_id`` we drop the entire
        batch — partial overlap (some decisions from a tick already
        seen) is not possible because the producer publishes the full
        batch atomically per tick.

        Malformed batches (``decisions`` missing or not a list) are
        silently skipped: the orchestrator's own validation lives in
        ``decision_feed.build_decisions_batch``; this ledger is
        defensive.
        """
        decisions = batch.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            return 0
        tick_id = batch.get("tick_id")
        if isinstance(tick_id, str) and tick_id in self._seen_tick_ids:
            return 0
        appended = 0
        for raw in decisions:
            if not isinstance(raw, dict):
                continue
            entry = dict(raw)
            # Stamp the per-batch ts on every entry so the API can
            # surface a "when did this decision happen" column without
            # the client joining the batch back together.
            if "at" not in entry and "at" in batch:
                entry["at"] = batch["at"]
            if "tick_id" not in entry and isinstance(tick_id, str):
                entry["tick_id"] = tick_id
            self._entries.append(entry)
            appended += 1
        if isinstance(tick_id, str):
            self._seen_tick_ids.append(tick_id)
        return appended

    def recent(
        self,
        limit: int = 50,
        *,
        agent_id: int | None = None,
        only_llm: bool = False,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` recent decisions, newest first.

        ``agent_id`` filters to one agent (None = all). ``only_llm``
        filters to entries where the agent actually had an LLM call
        (i.e. ``llm_bias`` or ``llm_stance`` is set); the default is
        to include the rule-based agents' decisions so the operator
        sees *all* reasoning activity, not just the LLM-overlay
        hybrid's. Lstm-only agents (no LLM) carry no ``llm_*`` key
        so they're naturally excluded by ``only_llm=True``.
        """
        if limit < 0:
            raise ValueError("limit must be non-negative")
        # Newest first: walk the deque backwards.
        out: list[dict[str, Any]] = []
        for entry in reversed(self._entries):
            if agent_id is not None and entry.get("agent_id") != agent_id:
                continue
            if only_llm and not (entry.get("llm_bias") or entry.get("llm_stance")):
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    def clear(self) -> None:
        """Drop every entry. Test helper; not exposed via the API."""
        self._entries.clear()
        self._seen_tick_ids.clear()
