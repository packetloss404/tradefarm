# Broadcast OS

> **Status: shipped 2026-06-18** (round 6, audit C6; `BroadcastSuite` is
> the production shape).

The Broadcast OS is TradeFarm's presentation layer between raw trading events
and the stream UI. Raw events say what happened; broadcast moments say what is
worth producing for an audience.

## Architecture

Broadcast OS stays backend-owned and UI-agnostic.

- Detectors observe trading and journal state, then create `BroadcastMoment`s.
- `broadcast_moment` is the canonical bus event; adapters derive legacy stream
  events while the frontend migrates.
- Moment fields such as `priority`, `ttl_sec`, `outputs`, and `metadata`
  describe production intent without naming a specific component.
- The next scheduler layer owns timing, cooldowns, and collisions between
  moments so detectors can stay simple.

## Event Flow

```text
orchestrator detectors
  -> BroadcastMoment
  -> broadcast_moment
  -> legacy stream adapters
       -> stream_macro_fired
       -> stream_banner
```

`broadcast_moment` is the canonical event. Legacy events stay in place so the
current stream app can keep rendering macro bursts and lower-thirds while the
frontend migrates toward the richer contract.

## Moment Payload

```json
{
  "id": "auto-big-win-42",
  "kind": "agent_pnl",
  "title": "Big win: agent-042",
  "subtitle": "AAPL +6.0%",
  "priority": 78,
  "color": "profit",
  "agent_id": 42,
  "trigger": "big_win",
  "outputs": ["macro_burst", "ticker", "recap_log"],
  "ttl_sec": 8,
  "created_at": "2026-05-16T00:00:00+00:00",
  "metadata": {}
}
```

## V1 Rules

- `AutoDirector` converts threshold crossings into broadcast moments.
- `StreakWatcher` converts journal patterns into broadcast moments.
- The tick loop emits `fill_of_tick` for the largest fill above the minimum
  notional threshold.
- Every moment emits `broadcast_moment`.
- Moments with `macro_burst` also emit `stream_macro_fired`.
- Moments with `lower_third` also emit `stream_banner`.

## Next Layer

The missing piece is a presentation scheduler. It should arbitrate collisions
between moments, commentary, lower-thirds, OBS scene changes, and future TTS.
For now, the stream keeps its existing single-slot macro/banner behavior.

## Next Milestones

1. Add scheduler v1: consume `broadcast_moment`, apply priority/TTL/cooldowns,
   and emit one active slot per output type. **Shipped 2026-07 (round 8,
   `broadcast_scheduler.py` + `broadcast_os.py` arbiter).**
2. Move the stream UI to the canonical moment contract, keeping legacy macro and
   banner events as compatibility shims. **Shipped 2026-08-05 in 0.15.0** —
   `useStreamCommands` now reads `broadcast_moment` first and routes
   `macro_burst` / `lower_third` outputs to the existing macro/banner slots via
   pure mappers in `broadcastMomentMappers.ts`. The legacy branches stay live as
   a backstop; a 1.5s id-keyed dedup ring prevents the canonical-then-legacy
   fan-out from re-firing the same slot.
3. Add replay fixtures for moment timelines so priorities and collisions can be
   tuned without waiting for live ticks.
