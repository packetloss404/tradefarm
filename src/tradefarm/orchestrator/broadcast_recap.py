"""In-memory recap ledger for Broadcast OS moments."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from tradefarm.orchestrator.broadcast_os import BroadcastKind, BroadcastMoment, BroadcastOutput

KindFilter = BroadcastKind | Iterable[BroadcastKind] | None
OutputFilter = BroadcastOutput | Iterable[BroadcastOutput] | None


def _normalize_filter(value: str | Iterable[str] | None) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    normalized = int(limit)
    if normalized < 0:
        raise ValueError("limit must be non-negative")
    return normalized


@dataclass
class BroadcastRecapLedger:
    """Bounded in-memory store for stream-worthy Broadcast OS moments.

    The ledger keeps only the newest ``max_moments`` entries. Query methods
    return ``BroadcastMoment`` objects for in-process consumers, while payload
    helpers serialize through ``BroadcastMoment.to_payload()`` for API/poster
    work later.
    """

    max_moments: int = 100
    _moments: deque[BroadcastMoment] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_moments < 1:
            raise ValueError("max_moments must be at least 1")
        self._moments = deque(maxlen=self.max_moments)

    def __len__(self) -> int:
        return len(self._moments)

    def record(self, moment: BroadcastMoment) -> BroadcastMoment:
        """Append ``moment`` and evict the oldest entry if the ledger is full."""

        self._moments.append(moment)
        return moment

    def extend(self, moments: Iterable[BroadcastMoment]) -> None:
        """Record several moments in order."""

        for moment in moments:
            self.record(moment)

    def clear(self) -> None:
        """Drop all recorded moments."""

        self._moments.clear()

    def recent_moments(
        self,
        *,
        limit: int | None = None,
        kind: KindFilter = None,
        output: OutputFilter = None,
    ) -> list[BroadcastMoment]:
        """Return newest-first moments, optionally filtered by kind/output."""

        matches = self._filtered(kind=kind, output=output)
        matches.reverse()
        normalized_limit = _normalize_limit(limit)
        if normalized_limit is None:
            return matches
        return matches[:normalized_limit]

    def top_moments(
        self,
        *,
        limit: int | None = None,
        kind: KindFilter = None,
        output: OutputFilter = None,
    ) -> list[BroadcastMoment]:
        """Return highest-priority moments, with newer moments winning ties."""

        indexed = list(enumerate(self._filtered(kind=kind, output=output)))
        ranked = sorted(
            indexed,
            key=lambda item: (int(item[1].to_payload()["priority"]), item[0]),
            reverse=True,
        )
        normalized_limit = _normalize_limit(limit)
        moments = [moment for _, moment in ranked]
        if normalized_limit is None:
            return moments
        return moments[:normalized_limit]

    def recent_payloads(
        self,
        *,
        limit: int | None = None,
        kind: KindFilter = None,
        output: OutputFilter = None,
    ) -> list[dict[str, Any]]:
        """Serialize recent moments to plain dictionaries."""

        return [
            moment.to_payload()
            for moment in self.recent_moments(limit=limit, kind=kind, output=output)
        ]

    def top_payloads(
        self,
        *,
        limit: int | None = None,
        kind: KindFilter = None,
        output: OutputFilter = None,
    ) -> list[dict[str, Any]]:
        """Serialize top moments to plain dictionaries."""

        return [moment.to_payload() for moment in self.top_moments(limit=limit, kind=kind, output=output)]

    def to_payload(
        self,
        *,
        recent_limit: int = 10,
        top_limit: int = 5,
        kind: KindFilter = None,
        output: OutputFilter = None,
    ) -> dict[str, Any]:
        """Return a recap-ready snapshot of the current ledger."""

        filtered_count = len(self._filtered(kind=kind, output=output))
        return {
            "max_moments": self.max_moments,
            "count": filtered_count,
            "recent": self.recent_payloads(limit=recent_limit, kind=kind, output=output),
            "top": self.top_payloads(limit=top_limit, kind=kind, output=output),
        }

    def _filtered(self, *, kind: KindFilter, output: OutputFilter) -> list[BroadcastMoment]:
        kind_set = _normalize_filter(kind)
        output_set = _normalize_filter(output)
        out: list[BroadcastMoment] = []
        for moment in self._moments:
            if kind_set is not None and moment.kind not in kind_set:
                continue
            if output_set is not None and not output_set.intersection(moment.outputs):
                continue
            out.append(moment)
        return out
