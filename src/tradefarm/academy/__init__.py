"""Agent Academy (Phase 2): rank system + rank-gated capital.

Public surface:

- :mod:`tradefarm.academy.ranks` — `Rank`, `RankStats`, `compute_stats`,
  `eligible_rank`.
- :mod:`tradefarm.academy.repo` — `set_rank`, `get_rank`, `rank_distribution`.

Phase 4's curriculum will call ``compute_stats`` → ``eligible_rank`` → ``set_rank``.
"""
from tradefarm.academy.ranks import (
    RANK_ORDER,
    Rank,
    RankStats,
    compute_stats,
    eligible_rank,
    rank_tone,
)

__all__ = [
    "RANK_ORDER",
    "Rank",
    "RankStats",
    "compute_stats",
    "eligible_rank",
    "rank_tone",
]
