# Moment timeline replay fixtures

NDJSON replay inputs for `BroadcastScheduler` tests. One
`BroadcastMoment.to_payload()` per line; each file is a hand-crafted
scenario that exercises a specific scheduler branch.

See `docs/research/replay-fixtures.md` for the design rationale.

## Files

| fixture | lines | what it exercises | assertion shape |
|---|---|---|---|
| `priority_preempt.ndjson` | 6 | `_preempt_lower_priority` (`scheduler.py:278`): a high-priority moment bumps a lower-priority one off `macro_burst`, then a triple-output moment bumps the mid-priority one off both `macro_burst` and `ticker` while leaving the unrelated `lower_third` occupant alone | `low-1` / `mid-1` end preempted, `high-1` active on all 3 outputs, `mid-1-followup` + `low-3` queued |
| `cooldown_collision.ndjson` | 5 | `BroadcastRecapLedger` dedup: five near-identical `bigwin` moments for the same agent 90s apart; the ledger keeps all 5 (no dedup at the ledger level), and `top_moments(limit=3)` returns 3 of them | `len(ledger) == 5`, `top_moments(limit=3)` returns 3 same-priority moments, scheduler view with `tick_sec=0.1` shows moment-1 active + moments 2-5 queued |
| `queue_overflow_8.ndjson` | 35 | `_trim_queue` (`scheduler.py:233`): 35 mixed-priority moments against `max_queue_size=8`; 27 are dropped, the 8 highest-priority survive (2 at prio 80, 5 at prio 60-70, 1 at prio 50 — the most-recent one) | the 8 kept IDs are exactly `q-03, q-04, q-05, q-15, q-20, q-21, q-28, q-35`; no dropped moment appears in any slot transition |

## What this unblocks

Without fixtures, every `BroadcastScheduler` change required a 5-10 minute
live orchestrator loop (start, wait for a market-open window, watch the
WS stream, tweak, restart). With fixtures, every change is:

```bash
pytest tests/orchestrator/test_broadcast_fixtures.py -v
```

`< 5` seconds per change. The 60-120x speedup is the milestone-3 win from
`docs/broadcast_os.md:84-85`.

Specific tunings this enables:

- `max_queue_size`: test at 4, 8, 16, 32, 64 against
  `queue_overflow_8.ndjson`; pick the smallest that doesn't drop a
  priority-80 moment in a 35-moment input.
- `_preempt_lower_priority` comparison (`<` vs `<=`): fixture an
  equal-priority scenario (two priority-70 moments on the same output)
  and assert whether the second preempts the first or queues behind it.
- `_trim_queue` sort key `(priority, -enqueued_at, -sequence)`: does
  `-enqueued_at` give the right tiebreaker? Fixture two priority-40
  moments submitted 5 seconds apart and assert the older one drops.

## How to add a new fixture

1. Create `tests/fixtures/moments/<scenario>.ndjson`.
2. One `BroadcastMoment.to_payload()` per line. Use `json.dumps(...)` with
   `separators=(",", ":")` to match the recorder's output format.
3. Add a test in `tests/orchestrator/test_broadcast_fixtures.py` that
   loads the fixture, replays it, and asserts on the slot transitions.
4. Update this README's table with the new row.

The loader (`broadcast_fixtures.load_fixture`) skips blank lines and
lines starting with `#`, so you can annotate tricky moments inline. A
malformed line is logged and skipped — the rest of the file still
loads. A missing file returns an empty moment list (no raise) so tests
can opt into "fixture optional" patterns.

## Recording a new fixture from a live session

```bash
broadcast_record_moments=out/debug/2026-08-05-session.ndjson \
  python -m tradefarm.orchestrator.main
```

The orchestrator appends one NDJSON line per `BroadcastMoment` it
emits. The file lives in `out/debug/` (gitignored). When you see a
collision or preemption you want to lock in as a regression test:

1. `cp out/debug/2026-08-05-session.ndjson tests/fixtures/moments/<scenario>.ndjson`
2. Hand-prune the lines you don't want (keep the minimal sequence that
   triggers the behavior you care about).
3. Write the assertion in `test_broadcast_fixtures.py`.
4. Commit the fixture + test together.

## Why NDJSON, not SQLite or single-JSON-array

- Append-only writes: O(1), safe to do while a reader is `tail -f`-ing.
- Partial-load: a corrupted line skips with a warning; the rest of the
  file still loads.
- Human-editable: any text editor works, no CLI needed.
- Convention: `tests/data/` already has `.ndjson` files for other
  test inputs; the pattern is already in the repo.
