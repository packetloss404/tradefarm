"""Hardcoded list of well-known US equity pairs for the pairs_zscore strategy.

Each pair is a 2-tuple of symbols the orchestrator will round-robin into
~14 pairs slots (i % 7 == 6, with agent_count=100). Long-only sandbox —
the strategy is one-sided (long the underperformer).
"""

PAIRS: tuple[tuple[str, str], ...] = (
    ("KO", "PEP"),
    ("XOM", "CVX"),
    ("V", "MA"),
    ("HD", "LOW"),
    ("JPM", "BAC"),
    ("MCD", "SBUX"),
    ("PG", "KMB"),
    ("WMT", "TGT"),
    ("T", "VZ"),
    ("BA", "LMT"),
    ("INTC", "AMD"),
    ("AAPL", "MSFT"),
    ("GS", "MS"),
    ("CVX", "COP"),
)


def pair_for_slot(slot_idx: int) -> tuple[str, str]:
    """Return the pair assigned to the given pairs-slot index.

    The orchestrator calls this with the index of a pairs_zscore agent
    within its cohort (not the global agent_id), so consecutive
    slot_idxs return different pairs via modulo. Modulo by the number
    of pairs — slot_idx past the pair count cycles through the list.
    """
    return PAIRS[slot_idx % len(PAIRS)]
