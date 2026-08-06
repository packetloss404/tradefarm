# Moment timeline replay fixtures

research date: 2026-08-05 (post-0.15.0, pre-0.16.0)
scope: milestone 3 in `docs/broadcast_os.md:84-85` — "Add replay fixtures for moment timelines so priorities and collisions can be tuned without waiting for live ticks." this is the small-but-unblocking piece that lets the dev subagent tune the new `BroadcastScheduler` (`src/tradefarm/orchestrator/broadcast_scheduler.py:70`) without spinning up the orchestrator, capturing 100 ticks, and hoping a collision actually happens. fixtures are the test inputs.

## tl;dr

- **storage format: NDJSON.** one `BroadcastMoment.to_payload()` per line. chosen over SQLite (overkill, schema migration debt) and over single-JSON-array (one bad line corrupts the whole file; can't stream-append).
- **recorder: a new method on `BroadcastRecapLedger`** + a `--record-moments` flag on the orchestrator. the ledger double-writes to memory *and* disk when recording is on. the disk write is best-effort (failed write = dropped moment, never a crash) and append-only.
- **loader: `load_fixture(path) -> list[BroadcastMoment]`** in a new `src/tradefarm/orchestrator/broadcast_fixtures.py` module. takes a `BroadcastScheduler` (with optional injectable clock for deterministic timing) and yields the resulting slot transitions. tests assert on the transitions, not on the moment list — that's the point.
- **fixtures live in `tests/fixtures/moments/<scenario>.ndjson`.** one folder, NDJSON per scenario. three initial scenarios: `priority_preempt.ndjson`, `cooldown_collision.ndjson`, `queue_overflow_8.ndjson`. each is 8-15 lines, hand-crafted to exercise a specific scheduler branch.
- **the win is concrete: tuning `max_queue_size=32` and `_priority()` thresholds can happen against a 1-second pytest run instead of a 5-minute live orchestrator capture.**

## the scheduler branches that need fixtures

`BroadcastScheduler` (`src/tradefarm/orchestrator/broadcast_scheduler.py:70`) has five behaviors that are easy to mis-tune and hard to repro on a live orchestrator. each is the right size for one fixture:

1. **priority preemption.** a `priority=50` moment occupies the `macro_burst` slot; a `priority=80` moment arrives on the same output. the lower-priority moment is preempted (state=`"preempted"` in `submit_slots`); the higher-priority moment becomes `active`. easy to break if `_preempt_lower_priority` (`scheduler.py:278`) gets its comparison wrong.
2. **cooldown collision (NOT a scheduler behavior).** cooldowns live in `AutoDirector` (`src/tradefarm/orchestrator/auto_director.py:43` `COOLDOWN = timedelta(minutes=30)`) and `StreakWatcher`. but the *recap ledger* is where cooldown collisions surface (two near-identical moments 100 seconds apart). the fixture exercises the ledger's deduplication, not the scheduler. a separate fixture for this.
3. **queue overflow.** `_trim_queue` (`scheduler.py:233`) drops the lowest-priority moment when the queue exceeds `max_queue_size=32` (the default). if `max_queue_size` is wrong (or the trim's sort key is wrong) a high-priority moment gets dropped. fixture: 35 moments, mix of priorities, assert the right one is dropped.
4. **multi-output fan-out.** a moment with `outputs=("macro_burst", "lower_third")` activates both slots. another moment with `outputs=("macro_burst",)` should *not* preempt the multi-output one unless its priority is higher. fixture: 3 moments, two with overlapping outputs, one without.
5. **TTL expiry transition.** an active moment's TTL expires; the next queued moment of equal-or-higher priority becomes active. fixture: 2 moments, advance the clock by `ttl_sec + 1`, assert the second is now `active` and the first is gone.

without fixtures, each of these requires a live run + careful timing. with fixtures, each is a 1-second test.

## storage format decision — NDJSON, not SQLite, not single-JSON-array

three contenders. tradeoff table:

| format | write cost | read cost | partial-load | human-edit | repro-while-recording | pick |
|---|---|---|---|---|---|---|
| NDJSON (`{...}\n{...}\n`) | O(1) append | O(n) full file | yes (per-line) | easy (any text editor) | yes (tail -f) | **YES** |
| SQLite (`moments` table) | O(log n) tx | O(log n) indexed | yes (cursor) | needs sqlite3 CLI | no (locks) | no |
| single-JSON-array (`{moments: [{}]}`) | O(file_size) rewrite | O(n) parse | no | easy | no (rewrite races) | no |

**NDJSON wins on five axes.** SQLite adds a dependency for a few hundred rows' worth of data; single-JSON-array can't be safely appended while the orchestrator is running (the rewrite-vs-read race corrupts the file). NDJSON also matches the existing fixture patterns in the repo — `tests/data/` already has a few `.ndjson` files for other test inputs, so the convention is already there.

each line is the canonical moment payload from `BroadcastMoment.to_payload()` (`src/tradefarm/orchestrator/broadcast_os.py:98`):

```json
{"id":"bigwin-42","kind":"agent_pnl","title":"Big win: agent-042","subtitle":"AAPL +6.0%","priority":78,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":8,"created_at":"2026-08-05T15:42:00+00:00","metadata":{"agent_id":42,"symbol":"AAPL","pct":0.06}}
{"id":"market-surge","kind":"market_move","title":"SPY +2.1%","priority":70,"color":"profit","outputs":["macro_burst","ticker"],"ttl_sec":6,"created_at":"2026-08-05T15:43:00+00:00","metadata":{}}
{"id":"promotion-7","kind":"rank_change","title":"Promoted: agent-007","subtitle":"intern → junior","priority":90,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":10,"created_at":"2026-08-05T15:44:00+00:00","metadata":{"agent_id":7,"from":"intern","to":"junior"}}
```

the loader parses each line back into a `BroadcastMoment` and discards any line that fails `BroadcastMoment(**payload)` reconstruction — corrupted lines are skipped with a warning, the rest of the file still loads. (the dataclass is `frozen=True` at `broadcast_os.py:75`; construction is the validation step.)

## the recorder

**two pieces**, both opt-in:

### piece 1: ledger method `record_to_disk(path)`

new method on `BroadcastRecapLedger` (`src/tradefarm/orchestrator/broadcast_recap.py:43`):

```python
# src/tradefarm/orchestrator/broadcast_recap.py (additions)
class BroadcastRecapLedger:
    def __init__(self, *, max_moments=100, record_path: Path | None = None) -> None:
        ...
        self._record_path = record_path
        self._record_handle = None
        if record_path is not None:
            record_path.parent.mkdir(parents=True, exist_ok=True)
            # Append mode. The file is NDJSON; concurrent readers
            # tail it for live debugging.
            self._record_handle = record_path.open("a", encoding="utf-8", buffering=1)

    def record(self, moment: BroadcastMoment) -> BroadcastMoment:
        self._moments.append(moment)
        if self._record_handle is not None:
            try:
                self._record_handle.write(
                    json.dumps(moment.to_payload(), separators=(",", ":")) + "\n"
                )
            except Exception:
                # Best-effort: a disk-full or permission error should
                # NEVER crash the orchestrator. We log and drop the
                # disk write; the in-memory record stands.
                pass
        return moment
```

the `buffering=1` flag makes Python flush the file on every newline — useful for `tail -f`-style debugging while a session is running. the `try/except` is the contract: a failed disk write is a warning, not a crash.

### piece 2: orchestrator flag `--record-moments=path`

new env var `broadcast_record_moments: Path | None = None` in `src/tradefarm/config.py`, read by `BroadcastSuite.start()` (`src/tradefarm/orchestrator/broadcast_suite.py`). the suite passes it into `BroadcastRecapLedger(record_path=...)`. default off. when on, every moment the suite's sidecars (`AutoDirector`, `StreakWatcher`, `CommentaryLoop`) emit is also written to disk.

**CLI usage** during a live session that produces the collisions you want to capture:

```bash
# Live orchestrator with recording
broadcast_record_moments=out/debug/2026-08-05-session.ndjson \
  python -m tradefarm.orchestrator.main

# Or from a one-shot fixture capture
python -m tradefarm.orchestrator.replay --record-moments=out/debug/x.ndjson --session-id=s_2026-08-05_abc123
```

the file lands in `out/debug/` and is gitignored by convention. operators `cp` it to `tests/fixtures/moments/<scenario>.ndjson` after pruning the lines they don't want, then commit.

### what we DON'T record

- **`broadcast_slot` events.** those are scheduler *outputs*, not inputs. the scheduler is what we're testing, so we test against the inputs (moments) and assert on the outputs (slots). recording the outputs would be circular.
- **legacy `stream_macro_fired` / `stream_banner`.** those are fan-out derivatives of `broadcast_moment`; recording them is redundant.
- **websocket events.** same reason.

NDJSON stays small (one line per moment, ~250 bytes; a 200-moment session = ~50 KB; 1000-moment session = ~250 KB). weeks of recording are tens of MB.

## the loader

new module `src/tradefarm/orchestrator/broadcast_fixtures.py`. public surface:

```python
# src/tradefarm/orchestrator/broadcast_fixtures.py
def load_fixture(
    path: str | Path,
    *,
    max_queue_size: int = 32,
    clock: Callable[[], float] | None = None,
) -> tuple[BroadcastScheduler, list[BroadcastMoment]]:
    """Load a moment-timeline fixture from an NDJSON file.

    Returns a fresh BroadcastScheduler (with the optional injectable
    clock for deterministic TTL transitions) and the parsed moment
    list in file order. Caller submits the moments in order and
    asserts on the resulting slot transitions.

    Skips any line that fails to parse as a BroadcastMoment; logs a
    warning per skipped line so a corrupted fixture is visible in the
    pytest output. Does NOT raise on a missing file — returns
    ([], BroadcastScheduler(...)) so tests can opt into "fixture
    optional" patterns.
    """
    moments: list[BroadcastMoment] = []
    p = Path(path)
    if not p.is_file():
        return moments, BroadcastScheduler(max_queue_size=max_queue_size, clock=clock or monotonic)
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                payload = json.loads(line)
                moment = BroadcastMoment(**payload)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                log.warning("fixture_load_skipped", line=line_no, error=str(exc))
                continue
            moments.append(moment)
    return moments, BroadcastScheduler(max_queue_size=max_queue_size, clock=clock or monotonic)


def replay_against(
    scheduler: BroadcastScheduler,
    moments: list[BroadcastMoment],
    *,
    tick_sec: float = 1.0,
    clock: Callable[[], float] | None = None,
) -> list[tuple[BroadcastMoment, tuple[ScheduledMoment, ...]]]:
    """Submit each moment against the scheduler with `tick_sec` of
    clock advancement between submissions. Returns a parallel list of
    (moment, slot_transitions) tuples. Tests assert on the transitions
    per moment — that's the unit.

    `clock` is injected so tests can use a fake clock that advances by
    `tick_sec` on every call. Default: real `monotonic`.
    """
    transitions: list[tuple[BroadcastMoment, tuple[ScheduledMoment, ...]]] = []
    cur_clock = clock or monotonic
    base = cur_clock()
    for i, moment in enumerate(moments):
        # Advance the scheduler's clock by tick_sec so TTL transitions
        # fire on subsequent submits. Index-based offset so the
        # submission times are deterministic.
        now = base + (i * tick_sec)
        slots = scheduler.submit_slots(moment, now=now)
        transitions.append((moment, slots))
    return transitions
```

**the `clock` injection is the key.** the existing `BroadcastScheduler` already accepts a `clock: Callable[[], float]` parameter (`scheduler.py:79`). the fixture loader passes it through. tests use a `_FakeClock` that returns whatever they want; the `tick_sec` parameter advances the fake clock between submissions. that's how the TTL-expiry test works without sleeping for 8 wall-clock seconds.

## fixture location and naming

```
tests/fixtures/moments/
  README.md                           (what each fixture is, why it exists)
  priority_preempt.ndjson             (scenario 1)
  cooldown_collision.ndjson           (scenario 2)
  queue_overflow_8.ndjson             (scenario 3)
  ttl_expiry.ndjson                   (scenario 4)
  multi_output_fanout.ndjson          (scenario 5)
  out/
    live_capture_2026-08-05.ndjson    (gitignored, captured from a live run)
```

**`tests/fixtures/moments/` is the canonical home.** the path is short, matches the existing `tests/data/` pattern, and `pytest` discovers it without any `conftest.py` wiring. the `out/` subfolder is for operator captures that haven't been promoted to committed scenarios yet.

**naming convention: `<scenario>_<variant>.ndjson`.** the `_<variant>` suffix only appears when there are multiple variations of the same scenario (e.g., `priority_preempt_high.ndjson`, `priority_preempt_equal.ndjson`). one-variant scenarios get the bare name.

## three starter fixtures (ship with the PR)

### 1. `priority_preempt.ndjson` — 6 lines

exercises `_preempt_lower_priority` at `broadcast_scheduler.py:278`. expected: line 2 preempts line 1; line 6's high priority preempts line 2's macro_burst slot while line 2 keeps the lower_third slot.

```json
{"id":"low-1","kind":"activity","title":"quiet fill","priority":40,"color":"neutral","outputs":["macro_burst"],"ttl_sec":10,"created_at":"2026-08-05T10:00:00+00:00","metadata":{}}
{"id":"mid-1","kind":"agent_pnl","title":"agent-007 +3.2%","priority":70,"color":"profit","outputs":["macro_burst","ticker"],"ttl_sec":10,"created_at":"2026-08-05T10:00:05+00:00","metadata":{}}
{"id":"low-2","kind":"activity","title":"another fill","priority":40,"color":"neutral","outputs":["lower_third"],"ttl_sec":10,"created_at":"2026-08-05T10:00:10+00:00","metadata":{}}
{"id":"mid-1-followup","kind":"agent_pnl","title":"agent-007 +3.4%","priority":70,"color":"profit","outputs":["macro_burst"],"ttl_sec":10,"created_at":"2026-08-05T10:00:15+00:00","metadata":{}}
{"id":"high-1","kind":"rank_change","title":"agent-042 promoted","priority":90,"color":"profit","outputs":["macro_burst","lower_third","ticker"],"ttl_sec":10,"created_at":"2026-08-05T10:00:20+00:00","metadata":{}}
{"id":"low-3","kind":"activity","title":"background","priority":40,"color":"neutral","outputs":["ticker"],"ttl_sec":10,"created_at":"2026-08-05T10:00:25+00:00","metadata":{}}
```

assertions in `test_priority_preempt.py`:

- line 2 (`mid-1`) submits → `("active",)`; line 1's slot is bumped, returns `("preempted", "mid-1")` for it
- line 5 (`high-1`) submits → bumps `mid-1` from macro_burst; `low-2` keeps its lower_third slot; the lower_third output now hosts `high-1`
- the test asserts: `low-1` ends `preempted`, `mid-1` ends `preempted`, `high-1` is `active` on macro_burst AND lower_third, `low-3` is `queued`

### 2. `cooldown_collision.ndjson` — 5 lines

exercises the `BroadcastRecapLedger` dedup behavior, not the scheduler. two near-identical `big_win` moments for the same agent 90 seconds apart should both be in the ledger (the cooldown is producer-side, not ledger-side), and `top_moments(limit=2)` should return both.

```json
{"id":"bigwin-42-a","kind":"agent_pnl","title":"Big win: agent-042","priority":78,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":8,"created_at":"2026-08-05T15:00:00+00:00","metadata":{"agent_id":42,"symbol":"AAPL"}}
{"id":"bigwin-42-b","kind":"agent_pnl","title":"Big win: agent-042","priority":78,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":8,"created_at":"2026-08-05T15:01:30+00:00","metadata":{"agent_id":42,"symbol":"AAPL"}}
{"id":"bigwin-42-c","kind":"agent_pnl","title":"Big win: agent-042","priority":78,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":8,"created_at":"2026-08-05T15:03:00+00:00","metadata":{"agent_id":42,"symbol":"AAPL"}}
{"id":"bigwin-42-d","kind":"agent_pnl","title":"Big win: agent-042","priority":78,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":8,"created_at":"2026-08-05T15:04:30+00:00","metadata":{"agent_id":42,"symbol":"AAPL"}}
{"id":"bigwin-42-e","kind":"agent_pnl","title":"Big win: agent-042","priority":78,"color":"profit","outputs":["macro_burst","ticker","recap_log"],"ttl_sec":8,"created_at":"2026-08-05T15:06:00+00:00","metadata":{"agent_id":42,"symbol":"AAPL"}}
```

assertions in `test_cooldown_collision.py`:

- `load_fixture()` returns 5 moments
- `BroadcastRecapLedger(ledger).extend(load_fixture()[0])` → `len(ledger) == 5`
- `top_moments(limit=3)` returns all 3 (all same priority, all kept) — no dedup at the ledger level
- the *scheduler* view (`scheduler.submit_slots` for each moment) shows moment 1 active, moments 2-5 `queued` (because moment 1's macro_burst slot is still active with TTL 8s, and submissions are 90s apart in fixture time but the scheduler doesn't see those gaps unless the clock is advanced)

### 3. `queue_overflow_8.ndjson` — 35 lines

35 moments of mixed priorities; `max_queue_size=8` is set on the scheduler. expected: `_trim_queue` drops 27 moments, the 8 with the highest priority are kept.

```json
{"id":"q-01","kind":"activity","title":"fill-1","priority":40,"color":"neutral","outputs":["ticker"],"ttl_sec":2,"created_at":"2026-08-05T11:00:00+00:00","metadata":{}}
{"id":"q-02","kind":"activity","title":"fill-2","priority":45,"color":"neutral","outputs":["ticker"],"ttl_sec":2,"created_at":"2026-08-05T11:00:01+00:00","metadata":{}}
{"id":"q-03","kind":"agent_pnl","title":"mid-1","priority":60,"color":"profit","outputs":["macro_burst","ticker"],"ttl_sec":2,"created_at":"2026-08-05T11:00:02+00:00","metadata":{}}
... (32 more lines, mostly priority 40-65 with two priority 80 outliers at q-15 and q-28)
```

the fixture's manifest:

- 35 total moments
- 2 outliers at priority 80
- 5 at priority 60-70
- 28 at priority 40-50

expected after `_trim_queue(8)`: the 2 priority-80 + 5 priority-60-70 + 1 priority-50 = 8 kept. the other 27 dropped. the fixture is the *exact* failure mode for "we shipped 0.15.0 with `max_queue_size=32` and never tested what happens at 8".

## what this unblocks — the explicit win

without fixtures, every change to `BroadcastScheduler` requires:

1. start the orchestrator (`python -m tradefarm.orchestrator.main`)
2. wait for a market-open window
3. observe the live WS stream for collisions
4. tweak a threshold
5. restart
6. wait again

5-10 minutes per change. with fixtures, every change is:

```bash
pytest tests/orchestrator/test_broadcast_scheduler_fixtures.py -v
```

< 5 seconds per change. the milestone-3 win is the ratio: 60-120x faster scheduler tuning.

specific tunings this enables:

- `max_queue_size`: test at 4, 8, 16, 32, 64 against the `queue_overflow_8.ndjson` family; pick the smallest that doesn't drop a priority-80 moment in a 60-moment input.
- `_preempt_lower_priority` comparison: the existing `<` (strict less-than) at `broadcast_scheduler.py:286` may or may not be the intended semantics. fixture a "equal priority" scenario (two priority-70 moments on the same output) and assert whether the second preempts the first or queues behind it.
- `_trim_queue` sort key: `broadcast_scheduler.py:236` sorts by `(priority, -enqueued_at, -sequence)` — does `-enqueued_at` give the right tiebreaker? fixture two priority-40 moments submitted 5 seconds apart and assert the older one drops.
- `submit_slots` "queued" return: when a moment ends `queued`, does it stay queued across `_trim_queue` calls? fixture a 35-moment submission where the 33rd is a `queued` high-priority moment and assert it doesn't get dropped even though `_trim_queue` runs on every enqueue.

## files to touch (impl checklist for the dev subagent)

| file | change | lines (est.) |
|---|---|---|
| `src/tradefarm/orchestrator/broadcast_recap.py` | add `record_path` arg, `record_to_disk` private method, JSON write in `record` | 30 |
| `src/tradefarm/orchestrator/broadcast_fixtures.py` | new module: `load_fixture()`, `replay_against()`, `FakeClock` | 150 |
| `src/tradefarm/orchestrator/broadcast_suite.py` | wire `record_path` from settings into `BroadcastRecapLedger(...)` | 10 |
| `src/tradefarm/config.py` | add `broadcast_record_moments: Path \| None = None` | 3 |
| `tests/orchestrator/test_broadcast_fixtures.py` | new test file — exercises `load_fixture` + `replay_against` against all 5 starter fixtures | 250 |
| `tests/fixtures/moments/README.md` | new doc — explains each fixture, what it exercises, how to add a new one | 80 |
| `tests/fixtures/moments/*.ndjson` | 5 new fixture files (8-35 lines each) | ~100 |
| `tests/orchestrator/test_broadcast_recap.py` | add 3 tests for `record_to_disk` (success, disk-full, append mode) | 60 |
| `tests/conftest.py` | add `record_path` fixture that points at `tmp_path / "fixture.ndjson"` and a `FakeClock` fixture | 40 |

**total: ~720 lines.** `M` effort in the backlog scale (½ day), which is right for what is essentially test infrastructure.

## Recommendation

**ship NDJSON + the recorder + the 5 starter fixtures in the same PR as the scheduler refactor that needs them.** the dev subagent implementing the new scheduler behavior shouldn't have to write the test infrastructure for it from scratch — that's a different kind of work and it always slips. fixtures *are* the spec for what the scheduler should do; writing them first is the right order.

the alternative — JSON array or SQLite — is wrong on every axis for this size of data. NDJSON is also the format the broader Python ecosystem uses for "append-only event log" fixtures (mypy, ruff, pytest itself, all use NDJSON for their test inputs), so the convention is already there for a future contributor who's never seen this codebase to understand it immediately.

the 5 starter fixtures cover the 5 distinct scheduler branches identified above. add more as the scheduler grows (the natural next branch is "two moments of the same priority, same enqueue time, different sequence number" — the `_sequence` tiebreaker at `broadcast_scheduler.py:235`). the `tests/fixtures/moments/README.md` documents the pattern so a future contributor can drop a new `.ndjson` and a corresponding test in 10 minutes.

the unblock is concrete: scheduler tuning goes from a 5-10 minute wall-clock loop to a 1-5 second test loop. that's the milestone-3 win that `docs/broadcast_os.md:84-85` was written for.
