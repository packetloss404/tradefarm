# 4pm ET live recap scene — design

research date: 2026-08-05 (post-0.15.0, pre-0.16.0)
scope: item **4.5** in `dev/feature-backlog.md` — the live, on-stream recap scene that auto-activates after the US equity close. NOT the VOD-only `RecapScene.tsx` already shipping in the stream app, and NOT the post-close 4:05pm VOD render that `run_vod_scheduler` (`src/tradefarm/orchestrator/scheduler.py:752`) already kicks off. This is a third surface, used by the live audience at the moment the market goes "ding".

## tl;dr

- **the existing `RecapScene.tsx` is the wrong surface.** it's a 30-second card rotator that reads `/api/recap/today` (live, today-only) and animates a 8-card sequence. the 4pm scene is *operator-facing* in the dashboard AND a different *audience-facing* moment on the stream — it pulls from `BroadcastRecapLedger` + weekly rollup, not from `/api/recap/today`. they coexist.
- **the trigger is a 4pm-ET cron, not the VOD scheduler.** `run_vod_scheduler` is gated on `is_market_closed_for_n_minutes(settings.vod_market_close_offset_min)` which fires at 4:05 ET, in a worker thread, for the VOD render. the live recap fires *earlier* (16:00 sharp, idempotent on the ET date) and emits a `broadcast_moment` that the stream's `SceneRotator` consumes. two loops; they don't share code.
- **the moment is a new `kind="day_leader"` with `outputs=("recap_log",)` + a force-scene override.** the scene becomes the new "today on tradefarm" splash that auto-activates once per trading day at 4pm. operator can also push it from the dashboard at any time.
- **audio = TTS of the day's headline + the existing commentary loop's bulletin.** no new jingle. piggy-backs on `tts/run.py` with a new prompt template.
- **recommendation: hybrid model** — auto-rotation that forces the recap into the rotator at 4:01pm ET (one cycle), PLUS a dashboard "Push recap now" button. operators want both.

## the surface landscape (what's already there)

| surface | audience | when | source | status |
|---|---|---|---|---|
| `RecapScene.tsx` (`stream/src/scenes/RecapScene.tsx:110`) | stream audience, in `SceneRotator` rotation | any time, mounted as one of 9 scenes; usually last in the cycle | `/api/recap/today` (`src/tradefarm/api/recap.py:419` `build_recap_from_manifest` or `:365` `build_recap`) | shipped 0.9.0 |
| VOD daily reel | YouTube, async | 4:05pm ET, `is_market_closed_for_n_minutes(5)` | `run_vod_scheduler` (`src/tradefarm/orchestrator/scheduler.py:752`) → `render.pipeline.run_pipeline` | shipped 0.9.0 |
| weekly rollup JSON | n/a — read by Studio + detectors | on demand, written when a session closes | `src/tradefarm/session/weekly_rollup.py:245` `write_weekly_rollup` | shipped 0.10.0 |
| `BroadcastRecapLedger` | in-process | continuous, recorded by `publish_broadcast_moment` (`src/tradefarm/orchestrator/broadcast_os.py:231`) | `src/tradefarm/orchestrator/broadcast_recap.py:43` | shipped 0.15.0 |
| **4pm ET live recap (this doc)** | **stream audience + dashboard operator** | **4:00 ET once per trading day + operator push** | **`BroadcastRecapLedger.to_payload()` + `weekly_rollup.read_weekly_rollup(week_id)`** | **0.16.0** |

the four existing surfaces do not solve the operator's 4pm moment. `RecapScene.tsx` exists, but the operator can't *trigger* it — it just rotates in. the VOD reel takes 30+ minutes to render and is post-close. the ledger + weekly rollup exist but are not surfaced in a "closing the day" frame. the 4pm recap fills the gap: an operator-triggered, on-stream, 60-second scene that reads from the recap ledger + weekly rollup.

## the moment itself

new canonical moment, published via `publish_broadcast_moment` (the existing arbiter in `src/tradefarm/orchestrator/broadcast_os.py:212`):

```python
BroadcastMoment(
    id=f"daily-recap-{et_date.isoformat()}-{uuid_hex}",
    kind="day_leader",                       # reuses existing literal
    title="Closing bell — today's recap",
    subtitle=None,                            # filled by the rotator
    priority=88,                               # high but below promotion (90)
    color="neutral",
    agent_id=None,
    trigger="daily_recap",
    outputs=("recap_log",),                    # NO macro_burst, NO lower_third
    ttl_sec=60,                                # long enough for the 30s scene
    created_at=...,
    metadata={
        "date": "2026-08-05",
        "week_id": "2026-W31",
        "ledger_size": 47,
        "top_moment_ids": ["bigwin-42", "market_surge", ...],
        "weekly_pool_pnl_pct": +1.42,
    },
)
```

**`outputs=("recap_log",)` only.** why not also `lower_third`? the recap scene is *the* scene — the rotator pulls the stream into `RecapScene.tsx` for 60 seconds. a lower-third running simultaneously would compete with the scene for the bottom 18% of the viewport. the moment's job is "force the rotator" not "pop a banner". if a future build wants both, the scene template can read the ledger's `top_moments[0]` and render its title as the lower-third text — no second moment needed.

**`priority=88`.** below `promotion=90` (`src/tradefarm/orchestrator/broadcast_os.py:53`) so a late-day promotion still preempts the recap (the rank-up is more dramatic than the summary). above `big_win=78` so the recap lands in the active slot even if the last 10 minutes had a big win.

**`ttl_sec=60`.** the rotator reads it as "hold for 60 seconds, then resume normal rotation." the 8-card sequence in `RecapScene.tsx:31` already totals ~31 seconds; 60 gives the operator a 30-second buffer to push the next forced scene manually.

## trigger — cron + idempotency

new method on `BroadcastSuite` (`src/tradefarm/orchestrator/broadcast_suite.py`), not on the orchestrator. the suite already owns the recap ledger + scheduler; the trigger is a natural fit:

```python
# src/tradefarm/orchestrator/broadcast_suite.py (new method)
async def run_daily_recap_scheduler(self) -> None:
    """Fire the 4pm-ET live recap once per NYSE trading day.

    Poll every 30s. When (ET clock) >= 16:00 AND no row in
    `daily_recap_fired` for today's ET date, publish a `daily_recap`
    moment via the installed arbiter. The per-day row is the idempotency
    key — a restart at 4:02pm does not re-fire. Holidays and weekends
    are handled by `is_market_closed_for_n_minutes(0)` (returns False on
    non-trading days), so the predicate simply doesn't trigger.
    """
    if not settings.daily_recap_enabled:
        await asyncio.Event().wait()
        return
    while True:
        try:
            if self._should_fire_daily_recap():
                await self._fire_daily_recap_moment()
        except Exception as exc:
            log.exception("daily_recap_loop_failed", error=str(exc))
        await asyncio.sleep(30)


def _should_fire_daily_recap(self) -> bool:
    # 16:00 ET trigger, with a 30-min grace window so a slow tick at
    # 16:00:07 doesn't get skipped.
    now_et = _runtime_clock_now_utc().astimezone(ET)
    if not (now_et.hour == 16 and 0 <= now_et.minute < 30):
        return False
    # Don't fire on a closed market — the equity market just closed
    # but holidays/weekends are not real sessions. is_market_closed_for_n_minutes
    # already encodes the holiday calendar.
    if not is_market_closed_for_n_minutes(0):
        return False
    today = now_et.date().isoformat()
    return self._daily_recap_repo.find_by_date(today) is None
```

**idempotency key = a new tiny table** `daily_recap_fired(date TEXT PRIMARY KEY, moment_id TEXT, fired_at TEXT)`. mirrors the `live_today` pattern from the VOD scheduler (`src/tradefarm/orchestrator/scheduler.py:850`) but without the boot-sweep complexity — this is a one-row-per-day table that's write-once, never updated, and never deleted (let it grow; ~250 rows/year is nothing). the row is written *after* `publish_broadcast_moment` returns, with `try/except` that doesn't roll back the publish — a lost row just means a possible re-fire the next restart, which the dashboard's "already pushed" toast surfaces.

**why not a `cron`?**
- the project's `orchestrator` doesn't have a `cron` dep; everything is an `asyncio.Task` started from `BroadcastSuite.start()`.
- the VOD scheduler already uses the same poll loop pattern (`scheduler.py:804` `poll_sec = 60`); this is 30s for tighter operator feedback.
- `is_market_closed_for_n_minutes(0)` already encodes the holiday calendar — no manual holiday list.

**operator push** — separate path. a new endpoint `POST /admin/recap/push` that takes an optional `{date: "YYYY-MM-DD"}` (defaults to today) and publishes the recap moment unconditionally. the dashboard's broadcast panel gets a new "Push 4pm recap" button. the row in `daily_recap_fired` is *not* written on manual push — so the next 4pm still fires (the operator can disable via `daily_recap_enabled=False` if they want to skip today's).

## the on-stream scene — separate component

`stream/src/scenes/RecapScene.tsx` reads from `/api/recap/today` and is fine for the 4pm replay. the 4pm live scene is a *new* component because the data shape is different: the live scene is built from `BroadcastRecapLedger` + weekly rollup, not from `/api/recap/today`. the recap scene's job at 4pm is to show "what just happened on the stream today" not "what the day's PnL was", which is what `/api/recap/today` answers.

**new component** `stream/src/scenes/LiveRecapScene.tsx`. a single React component:

```tsx
// stream/src/scenes/LiveRecapScene.tsx (sketch)
export function LiveRecapScene({ snapshot, weekId }: { snapshot: StreamSnapshot; weekId: string }) {
  const { data: ledger, loading: ledgerLoading } = useRecapLedger();
  const { data: week, loading: weekLoading } = useWeeklyRollup(weekId);

  if (ledgerLoading || weekLoading) return <LiveRecapShell><Loading /></LiveRecapShell>;
  if (!ledger) return <LiveRecapShell><Error message="no recap data" /></LiveRecapShell>;

  return (
    <LiveRecapShell>
      {/* Top-line */}
      <RecapKpiLine ledger={ledger} week={week} />

      {/* Biggest moves — top 3 moments by priority from the ledger */}
      <RecapTopMoves moments={ledger.top.slice(0, 3)} />

      {/* Rivalries — from the weekly rollup, if any */}
      {week && week.rivalries.length > 0 && <RecapRivalries rivalries={week.rivalries.slice(0, 2)} />}

      {/* Lower-third with the operator's pre-event headline */}
      <LowerThird title="Closing bell — today's recap" ttl={30} />
    </LiveRecapShell>
  );
}
```

two new SWR hooks: `useRecapLedger()` reads `GET /api/recap/ledger` (new endpoint, returns `BroadcastRecapLedger.to_payload()`), `useWeeklyRollup(weekId)` reads `GET /api/weekly/<week_id>` (new endpoint, wraps `weekly_rollup.read_weekly_rollup`).

### layout (ASCII mockup)

```
+----------------------------------------------------------------+
|  CLOSING BELL  ·  Tue Aug 5  ·  47 moments today               |
|  ──────────────────────────────────────────────────────────    |
|                                                                |
|   TODAY'S POOL         WEEKLY ROLLUP                           |
|   +1.42%               Strategy momentum    +5.3%             |
|   $100,142             Strategy mean-rev    -1.8%              |
|   47 trades            212 trades · 5 days                     |
|                                                                |
|   ──────────────────────────────────────────────────────────   |
|                                                                |
|   TOP 3 MOVES (from BroadcastRecapLedger)                      |
|     #1  Mei Patel    +12.4%  big win · AAPL · 15:42 ET         |
|     #2  Marcus Smith +9.1%   market surge · SPY · 11:08 ET     |
|     #3  Bob Huang    -7.2%   crash · TSLA · 13:55 ET           |
|                                                                |
|   ──────────────────────────────────────────────────────────   |
|                                                                |
|   RIVALRIES THIS WEEK                                           |
|     Mei Patel vs Bob Huang · NVDA · 4 trades · Mei 3-1         |
|                                                                |
|  ───────────────────────────────────────────────────────────   |
|  [lower third: "Closing bell — today's recap" · 30s TTL]       |
+----------------------------------------------------------------+
```

three rows of content (KPI line / top 3 / rivalries) inside the same `RecapShell` chrome that `RecapScene.tsx:179` already uses. the scene reads from a `useStreamCommands` hook to know when a `day_leader` moment with `trigger="daily_recap"` is active, and forces itself into the rotator's `idx` for the moment's `ttl_sec` (the existing `useStreamCommands` mappers already route `broadcast_moment` into the rotator; we just need a new `mapper.outputs=("recap_log",) -> LiveRecapScene` entry, mirroring how `macro_burst` routes to `MacroBurst`).

## audio — TTS of the headline, no new jingle

reuse `src/tradefarm/tts/run.py:316` `run_tts()`. new prompt template `templates/recap_close.txt` (~80 words, written by the same LLM the `CommentaryLoop` already uses):

```
Closing bell on {date}. {n} agents traded {moves} today.
Top move: {headline_1}. {headline_2_or_3}.
Pool P&L {signed_pnl} ({signed_pct}%) for the week.
That's the day. See you tomorrow at the open.
```

`render.headless` captures the scene (with the `recap_log` output already in `SCENES_WITH_REPLAY_SUPPORT`), `render.tts` synthesizes the wav, `render.mix` ducks the music bed. output: `out/sessions/{sid}/clips/recap_close.mp4` — same shape as the existing beat clips, but tagged `kind="recap_close"` in `beats.json` so the headless renderer picks it up at the end of the session.

the stream side reads a new WS event `audio_cue` and plays the wav via `streamAudio.duck(0.2, durationSec)`. the existing `LowerThird.tsx` already accepts a `ttl_sec` so the on-screen lower-third and the audio clip are aligned.

**why no new jingle?** a 30-second "today's recap" jingle is a creative-asset decision (`feature-backlog.md:5.3` is the existing home for recap MP4 capture, which would own the jingle). the TTS approach is free, voice-consistent with the rest of the stream's commentary, and shipped in the same PR as the scene. the operator can later add a jingle as a `CommentaryLoop` stinger that fires 3 seconds before the TTS.

## interaction with the existing `RecapScene.tsx`

`RecapScene.tsx` stays. it serves the use case "operator is browsing the stream and the rotator lands on recap". the new `LiveRecapScene` is mounted only when a `day_leader` moment with `trigger="daily_recap"` is active. `SceneRotator` (`stream/src/scenes/SceneRotator.tsx:31`) checks for the active moment's `outputs` and overlays the live scene on top of the rotator's current scene for the TTL — same pattern `MacroBurst` and `LowerThird` already use (the comment in `useStreamCommands` calls these "overlay surfaces").

a week with zero `day_leader` moments fired (operator disabled, or stream was down) → `RecapScene.tsx` rotates in as the fallback. zero operator awareness required.

## interaction with `run_vod_scheduler`

the VOD scheduler at `src/tradefarm/orchestrator/scheduler.py:752` fires at 4:05 ET. the live recap fires at 4:00 ET. they don't block each other:

- 4:00:01 ET — `_fire_daily_recap_moment()` runs. `BroadcastMoment` is published; ledger records; stream scene activates.
- 4:00:01-4:00:60 ET — `LiveRecapScene` is on stream; `useRecapLedger()` returns the moment-fresh ledger; `useWeeklyRollup()` returns the rollup that the day's last `write_weekly_rollup()` produced.
- 4:05:00 ET — `is_market_closed_for_n_minutes(5)` becomes true; VOD scheduler starts the daily VOD render. independent of the live scene (different process thread, different event consumer).
- 4:30:00 ET — live scene TTL expires; rotator returns to normal rotation.

the only coupling is the *row write* — the live recap writes to `daily_recap_fired`; the VOD scheduler writes to `pipeline_runs` (`src/tradefarm/orchestrator/scheduler.py:850`). separate tables, separate idempotency.

## files to touch (impl checklist for the dev subagent)

| file | change | lines (est.) |
|---|---|---|
| `src/tradefarm/orchestrator/broadcast_suite.py` | add `run_daily_recap_scheduler` + `_fire_daily_recap_moment` | 80 |
| `src/tradefarm/api/admin.py` (or new `recap_admin.py`) | add `POST /admin/recap/push` (operator manual trigger) | 40 |
| `src/tradefarm/api/recap.py` | add `GET /api/recap/ledger` (returns `BroadcastRecapLedger.to_payload()`) + `GET /api/weekly/{week_id}` (wraps `read_weekly_rollup`) | 50 |
| `src/tradefarm/storage/models.py` + new migration | add `daily_recap_fired` table | 25 + migration |
| `src/tradefarm/config.py` | add `daily_recap_enabled: bool = True` | 1 |
| `stream/src/scenes/LiveRecapScene.tsx` | new scene component (the ASCII mockup above) | 200 |
| `stream/src/hooks/useRecapLedger.ts` | new SWR hook | 25 |
| `stream/src/hooks/useWeeklyRollup.ts` | new SWR hook | 25 |
| `stream/src/shared/broadcastMomentMappers.ts` | add mapper for `kind="day_leader"` + `outputs=("recap_log",)` → `LiveRecapScene` | 30 |
| `web/src/broadcast/BroadcastPanel.tsx` | add "Push 4pm recap" button | 40 |
| `tests/orchestrator/test_daily_recap_scheduler.py` | new test using a 2-moment fixture to verify `_should_fire_daily_recap` + idempotency | 100 |
| `tests/api/test_recap_ledger_endpoint.py` | new test for the `GET /api/recap/ledger` endpoint | 60 |

**total: ~675 lines.** fits the `L` estimate from the backlog (item 4.5).

## Recommendation

**auto-rotation with operator override.** the recap scene auto-activates at 4:00 ET (one full 60-second cycle), but the dashboard gets a "Push recap now" button that publishes the same moment manually — bypassing the per-day idempotency row. operators want both because the auto-trigger assumes the live stream is on-air (it might be on a 5-minute mid-show break) and operators want a way to re-show the recap during the last 5 minutes of a stream (after the day's last big fill, when the audience is highest).

the alternative — pure force-scene override (operator must push it manually every day) — is simpler (~300 lines vs 675) but operators forget. item 4.5 in the backlog reads "force `idx = recap` once per cycle" and the language implies auto. pure auto-rotation (no operator button) is the lowest-friction path but the operator loses control during a stream restart at 4:03pm. the hybrid is the right call; the 4pm cron is the default, the button is the safety net.

the data source is `BroadcastRecapLedger.to_payload()` (in-memory, fresh) + `read_weekly_rollup(week_id)` (on disk, stale by ≤ 1 day). the scene renders inside the existing `RecapShell` chrome, on top of whatever the rotator's current scene is, for the moment's `ttl_sec=60`. the TTS uses the existing `run_tts()` with a new `templates/recap_close.txt`. audio reuses the existing `audio_cue` event path. no new musical asset, no new jingle — keep the v0 small and ship the jingle as a follow-up.
