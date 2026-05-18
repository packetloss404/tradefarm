# Session Runner — scoping (Phase 1, step 1 of the VOD pivot)

Status: scoping. No code yet. Companion to `docs/vod-pivot.md`.

## Goal

A headless driver that replays historical market days through the full
100-agent orchestrator and writes every decision, fill, and snapshot to
disk, tagged with a `session_id`. This is the keystone of the VOD
pipeline — every downstream subsystem (beat detector, script writer,
renderer) consumes its output.

Run:
```
uv run python -m tradefarm.session.run --date-range 2026-05-12:2026-05-16 --speed asap
```

Produces:
- DB rows tagged with `session_id` (Trade, PnlSnapshot, AgentNote)
- `out/sessions/<session_id>/manifest.json` — flat event list, ready
  for the beat detector
- Optional: per-tick JSON snapshots for the replay-mode renderer

## What the exploration confirmed (file:line)

- `data/eodhd.py:34-71` — `get_eod()` returns **daily bars only**, no
  intraday endpoint today. Hard constraint for v0.
- `orchestrator/scheduler.py:192` — `_load_bars` calls `date.today()`;
  the orchestrator is tied to wall-clock.
- `orchestrator/scheduler.py:219` — tick timestamp also wall-clock.
- `storage/models.py:47-95` — Trade, PnlSnapshot, AgentNote all use
  implicit "current run" semantics; **no `session_id` field exists**.
- `risk/manager.py:40`, `execution/virtual_book.py:14`,
  `storage/journal.py:139`, `orchestrator/auto_director.py:51`,
  `orchestrator/predictions.py:52`, `market/hours.py:14`,
  `api/market_clock.py:88` — 7+ additional `datetime.now()` call sites
  in the trading path.
- `agents/backtest.py:171-194` — existing CLI style is argparse +
  `asyncio.run(main())`. Match this for consistency.
- `backtest.py` itself is single-agent, single-symbol, in-memory; it is
  **not a useful base class** for the session runner. Build fresh.

## Key design decisions

### 1. Bar source (v0): daily EOD, trimmed to target date

EODHD client only serves daily bars today. **v0 accepts this** and
treats "one tick = one trading day". A "session" defaults to the last
5 trading days (≈100 agents × 5 days = ~500 decisions, ~50-150 fills
depending on entry rate). Intraday bars are a Phase 1.5 add when we
extend `EodhdClient` with the 1-min endpoint.

**Honest caveat:** daily bars give ~one decision per agent per day.
The content per session is the *divergence* across 100 agents on the
same bar (some long, some short, some wait), plus the day-over-day P&L
chase. That's the v0 content shape; if it doesn't feel rich enough in
practice we know intraday is the unlock.

### 2. Time injection: ContextVar + `now_utc()` helper

Replace the ~10 `datetime.now()` / `date.today()` call sites in the
trading path with a single helper:

```python
# src/tradefarm/runtime/clock.py
import contextvars
from datetime import datetime, timezone

_replay_now: contextvars.ContextVar[datetime | None] = contextvars.ContextVar(
    "replay_now", default=None,
)

def now_utc() -> datetime:
    v = _replay_now.get()
    return v if v is not None else datetime.now(timezone.utc)

def set_replay_now(t: datetime) -> contextvars.Token: ...
def reset_replay_now(token: contextvars.Token) -> None: ...
```

Live mode: ContextVar empty → falls through to wall-clock. Session
mode: runner sets the var before each tick, resets after. Zero impact
on live code paths. **Pre-work for the runner itself.**

### 3. DB schema: nullable `session_id` column

Migration adds `session_id: str | None` to `Trade`, `PnlSnapshot`,
`AgentNote`. Nullable, defaults to None. Live runs leave it None; the
session runner sets it. Indexed for query speed (`run_id` is the
join key for the beat detector). No breaking changes — existing
rows survive.

**Alternative considered:** entirely separate scratch DB per session.
Rejected because the dashboard's "show producer console" needs to
query across sessions, and forcing cross-DB joins is ugly. Single DB
+ session_id tag scales fine until tens of thousands of sessions.

### 4. CLI shape

```
uv run python -m tradefarm.session.run \
    --date-range 2026-05-12:2026-05-16 \
    --speed asap \
    --session-id auto \
    --out out/sessions/
```

- `--date-range START:END` (or `--date YYYY-MM-DD` for single day)
- `--speed asap | 10x | realtime` (v0 only implements `asap`; 10x and
  realtime are stubs that error until later)
- `--session-id` defaults to `auto` (UUID); pass a value for re-runs
- `--out` defaults to `out/sessions/`

Matches `agents/backtest.py:171-194` style (argparse +
`asyncio.run(main())`).

### 5. Manifest format

```json
{
  "session_id": "s_2026-05-15_a3f2",
  "date_range": ["2026-05-12", "2026-05-16"],
  "started_at": "2026-05-17T22:00:00Z",
  "ended_at":   "2026-05-17T22:00:42Z",
  "trading_days": ["2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16"],
  "tick_count": 5,
  "fill_count": 84,
  "agents_active": 100,
  "events": [
    {"t": "2026-05-12", "kind": "fill", "agent_id": 17, "agent_name": "andrew_wagner",
     "symbol": "SPY", "side": "buy", "qty": 38, "price": 521.4, "notional": 19813.2,
     "reason": "lstm up p=0.62"},
    {"t": "2026-05-12", "kind": "decision", "agent_id": 4, "agent_name": "james_jones",
     "signal": "wait", "rationale": "lstm flat max_prob=0.31 < 0.40"},
    ...
  ]
}
```

Flat event list, sorted by timestamp. Beat detector reads this; it
doesn't need to know about DB internals.

## Scope cut-list for v0 (do NOT do)

- Intraday bars (Phase 1.5; needs new EODHD endpoint)
- Multiple speeds (`10x`, `realtime` stubs error)
- Resume / partial-day replay
- Live websocket fan-out (sessions are batch jobs; the live WS is for
  the live mode only)
- Multi-day storyline carryover (Phase 3)
- The replay mode in `stream/` (Phase 1, step 3 — separate doc later)

## Decided defaults (locked 2026-05-17)

1. **LLM overlay: default ON, `--no-llm` to opt out.** Real `lstm_llm`
   agents in every session (~$0.25 per 5-day replay at Haiku 4.5
   prices). The 0.40 max_prob cost gate (CLAUDE.md #9) already caps
   spend. `--no-llm` available for fast dev iteration. Honest reason:
   disabling silently changes the strategy mix via the build_default
   fallback path, so default OFF would mean every session runs a
   *different* product than live.
2. **Bar caching: yes, parquet per (symbol, year), no TTL.** ~10MB
   total disk for the full universe × 5 years. Historical bars never
   change so no invalidation needed. One wrapper function over
   `EodhdClient.get_eod`; falls through to the EODHD call on cache miss.
3. **Agent state: fresh start, but write closing snapshot.** Each
   session resets books to $100k; we write a per-session closing
   snapshot of positions/cash/realized_pnl tagged with session_id.
   Phase 2 adds `--continue-from <session_id>` to enable multi-day
   arcs without re-running prior sessions. Cheap optionality.

## Suggested implementation order (when we start)

1. Add `runtime/clock.py` with ContextVar + helper, migrate ~10 call
   sites. Tests assert wall-clock behavior unchanged when var unset.
2. Add `session_id` migration + repo helpers that set the var when
   writing.
3. Add `src/tradefarm/session/__init__.py`, `session/run.py`.
4. Implement a single-day session: load bars trimmed to date,
   inject clock, run `orchestrator.tick_once()` once, persist tagged.
5. Extend to multi-day loop.
6. Write the manifest. Done.

Each of those is a focused commit (and an episode candidate). Total
estimated effort: 1-2 focused days for v0; longer if intraday
becomes a prerequisite.

## Cross-references

- `docs/vod-pivot.md` — parent decision doc; defines the 10-subsystem
  pipeline this is step 1 of
- Memory: `pivot-to-vod-2026-05-17` — the why
