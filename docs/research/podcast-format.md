# Rivalry Week podcast — 30-min weekly format

research date: 2026-08-05 (post-0.15.0, pre-0.16.0)
scope: a new long-form format — five daily 6-minute sessions stitched into one 30-minute weekly podcast episode. pivots the "Rivalry Week" idea from `docs/research/youtube-interesting.md:103` (one of three top-3 picks) from a video show into an audio-first podcast, with a static visual on the YouTube upload. the audio is the product; the video is the surface for algorithm-surfacing on YT/Shorts.

## tl;dr

- **the format is "Bloomberg daily + weekly stitching"**, not a new kind of beat. the daily pipeline already produces the building blocks; the podcast is a new composer that stitches them.
- **reuse `tts/run.py:316`** with a new `podcast_voice` provider option and a new prompt template `templates/podcast_weekly.txt`. NO ElevenLabs-cloned agent voices for v0 — the cost (~$1.50/week at current script lengths) and the QA surface (voice consistency across weeks) aren't worth the ceiling lift.
- **reuse `render/shorts.py` for the intro/outro cards**, not for the body. the body is a static "weekly rollup" card with a voiceover track; the intro/outro are 9:16 vertical teaser cards that link to the full episode.
- **new composer module: `src/tradefarm/render/podcast.py`**. mirrors `render/stitch.py`'s ffmpeg pattern. one ffmpeg invocation, three input streams (intro.mp4 + voice.wav + outro.mp4), output is `weekly_<week_id>.mp4` at 1920x1080.
- **a single host wraps the week**, not one per session. the script reads "Day 1: Marcus and Mei take opposite sides of NVDA… Day 5: Mei gets the last laugh." the host's "voice" is one TTS voice, picked from `settings.podcast_voice` (default `alloy` — already supported by `tts/run.py`).
- **lands in the VOD studio as a new `WeeklyPodcast` tab** (alongside `BeatPicker`, `EpisodePage`, `RivalryWeek`) and as a new entry in the weekly rollup JSON (a `podcast_path` field).

## why a podcast, not a video

the round-8 research (`docs/research/youtube-interesting.md:46-50`) names three top-3 episode formats. all three assume a video editor and a 5-10 minute runtime. a *30-minute weekly podcast* is a different format with a different ceiling:

- **audio is the hook.** YT music + YT podcast surfaces both surface long-form audio. the show becomes listenable in a car / on a treadmill / while coding, not just on the couch. that's a 10x surface area increase for the same content.
- **the weekly cadence compounds.** the daily show is forgettable; the weekly show is "did you listen this week?" — a habit. one short, one weekly podcast, one daily recap is the same upload cadence as a real podcast network.
- **the production cost is ~5x lower than the video version.** the v0.7.0 chain's biggest runtime cost is `render.headless` at ~30s per beat × 8-15 beats = 4-8 minutes per daily session. the podcast is *zero* headless capture — it reads the manifest, the rollup, and the journal notes; synthesizes voice; stiches ffmpeg. total runtime: ~30 seconds per day, ~2.5 minutes per weekly episode.
- **the video version of Rivalry Week is still the right video.** the podcast is the *audio* counterpart. the same `rivalry` data drives both surfaces.

## format breakdown

| segment | length | source | visual |
|---|---|---|---|
| intro jingle | 8s | `out/assets/intro_podcast.{mp4,mp3}` (new asset, optional) | vertical card "Rivalry Week · {week_id}" |
| week topline | 30s | weekly rollup (`session/weekly_rollup.py:241` `pool_pnl_pct`) + headline | static "Week of {date_range}" card |
| day 1 segment | 5min | daily manifest's day-1 + `rivalries` from that day | per-day montage of still frames + ticker |
| day 2 segment | 5min | same | same |
| day 3 segment | 5min | same | same |
| day 4 segment | 5min | same | same |
| day 5 segment | 5min | same | same |
| week wrap + outro | 2min | weekly rollup + next-week teaser | "See you next week" card |

total: ~30 minutes. day segments are length-capped at 5 minutes each, but the script generator is a per-day budget — if day 1 was a 12-fill day, day 1 gets the full 5 minutes; if day 5 was a 2-fill slow day, day 5 might be 1.5 minutes and the leftover rolls into the wrap.

**all five daily segments share one host voice and one visual chassis.** the audience doesn't need to know "day 1 had host A, day 2 had host B" — the unifying voice IS the format.

## render pipeline spec

new module: `src/tradefarm/render/podcast.py`. mirrors `render/stitch.py`'s shape (one ffmpeg invocation, audio + video inputs muxed). stages:

```
session/manifest_<dow>.json  (5x)
session/beats_<dow>.json     (5x, optional — used for per-day "top beat" callouts)
session/weekly_rollup_<week_id>.json  (1x, written by weekly_rollup.write_weekly_rollup)
        |
        |  render.podcast.compose_weekly_episode(week_id, ...)
        v
   podcast/
     script_<week_id>.txt       (generated LLM script, ~3500 words)
     voice_<week_id>.wav       (TTS, ~30 minutes)
     week_card_<week_id>.mp4   (static visual, 1920x1080, 30 minutes)
     intro_<week_id>.mp4       (vertical teaser, 9:16, 8 seconds)
     outro_<week_id>.mp4       (vertical teaser, 9:16, 8 seconds)
     weekly_<week_id>.mp4      (final mux, 1920x1080, ~30 minutes)
```

each stage is a pure function so the dev subagent can wire them into `render/pipeline.py:393` `run_pipeline()` as a new "extended" pipeline (e.g. `python -m tradefarm.render.pipeline --weekly <week_id>`), or as a standalone CLI: `python -m tradefarm.render.podcast compose <week_id>`.

### stage 1: script generation

LLM call (reuses the existing `CommentaryLoop`'s Claude integration at `src/tradefarm/orchestrator/commentary_loop.py`):

```python
# src/tradefarm/render/podcast.py (sketch)
SCRIPT_PROMPT = """\
You are the host of "Rivalry Week", a weekly podcast about a simulated
stock market run by 100 AI agents. Today is {date}. The week is
{week_id}, covering {date_range}. Here's the data:

{payload}

Write a 3500-word podcast script in 6 segments:
  1. intro (~80 words, 30s spoken)
  2. week topline (~100 words, 45s spoken)
  3-7. day 1 through day 5 (~500 words each, 2-3 min spoken)
  8. week wrap + outro (~150 words, 1 min spoken)

Tone: Bloomberg daily meets The Office. Specific names, specific
symbols, specific numbers. Drop at least one quotable LLM
inner-monologue line from the journal. The audience is technical;
lean into the strategy jargon (mean reversion, momentum, pairs
z-score) but explain on first use.

Format your output as a YAML doc with one key per segment.
"""
```

the payload is the weekly rollup + the 5 daily manifests' top-3 beats + 5 of each day's most quotable journal notes. ~5-10k tokens of context. the LLM call is ~$0.10-0.20 per week at Claude Sonnet pricing.

### stage 2: TTS

reuse `tts/run.py:316` `run_tts()` with the new `podcast_voice` provider and `podcast_weekly.txt` template:

```python
# src/tradefarm/render/podcast.py (sketch)
import subprocess
from tradefarm.tts.run import run_tts, TTSOpts

def synthesize_voice(week_id: str, script_path: Path, out_wav: Path) -> None:
    text = script_path.read_text(encoding="utf-8")
    # Strip YAML keys, keep only the spoken text.
    spoken = _yaml_to_prose(text)
    opts = TTSOpts(
        provider=settings.podcast_tts_provider,  # default: "openai" (cheapest)
        voice=settings.podcast_voice,            # default: "alloy"
        speaking_rate=1.05,                       # slightly faster than default 1.0
        output_path=out_wav,
    )
    run_tts(text=spoken, opts=opts)
```

**why `openai` not `elevenlabs`?** at $0.015/1k chars vs $0.30/1k chars, the cost difference for a 3500-word script (~$18k chars including formatting) is $0.27 vs $5.40 per week. openai's `tts-1-hd` voice quality is "noticeably worse than elevenlabs flash" per the autonomy-pipeline research (`docs/research/autonomy-pipeline.md:115`) but the 30-minute audio context forgives a lot — the audience is following a story, not listening to a meditation app. operators who want elevenlabs flip `podcast_tts_provider=elevenlabs` in `.env`. the `silence` provider stays as a no-cost default for CI / smoke tests.

**why one voice for all segments, not per-agent clones?** per-agent voice cloning (item `3.2` in `dev/feature-backlog.md:243` "TTS narrator") is the long-term ceiling — Mei Patel sounds different from Marcus Wagner — but it's a separate research problem. v0 ships with one unifying voice. the host *talks about* the agents; the agents don't talk. the script is in the third person throughout.

### stage 3: visual chassis (static card with ticker)

a single 1920x1080 background that plays for the full 30 minutes. the host's voice is the foreground; the visual is a "now playing" card:

```
+---------------------------------------------------------------+
| RIVALRY WEEK  ·  2026-W31  ·  Mon Aug 4 - Fri Aug 8           |
|                                                               |
|  POOL P&L  +1.42%    TRADES  212   AGENTS  100                |
|                                                               |
|  ── DAY 3 OF 5:  Wed Aug 6  ──                                |
|                                                               |
|  Mei Patel    AAPL    +6.0%  $1.2k notional                   |
|  Marcus Smith TSLA    -4.2%  $980 notional                    |
|  Bob Huang    NVDA    +3.1%  $1.5k notional                   |
|                                                               |
|  RIVALRY: Mei vs Bob, NVDA, 4 trades this week, Mei 3-1        |
|                                                               |
|  TICKER  AAPL 192.45 ▲  TSLA 245.10 ▼  NVDA 875.30 ▲  ...    |
+---------------------------------------------------------------+
```

this is a single `ffmpeg` invocation that loops a base background + overlays a per-segment text block. the per-segment text is generated once at compose time and baked into the video. the TTS voice plays over it.

```python
# src/tradefarm/render/podcast.py (sketch)
def render_static_card(week_id: str, segments: list[Segment], out_mp4: Path) -> None:
    # Generate one PNG per segment via Pillow.
    frames = [_render_card_frame(seg) for seg in segments]
    # ffmpeg concat into one mp4.
    concat_list = out_mp4.parent / f"_concat_{week_id}.txt"
    concat_list.write_text(
        "\n".join(f"file '{f.resolve()}'\n" for f in frames) +
        f"\nfile '{frames[-1].resolve()}'\n"  # last frame held for 1s
    )
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-i", str(voice_wav),
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(out_mp4),
    ])
```

each segment's frame is `1920x1080` × 1 second; `ffmpeg -shortest` clips the video to the voice duration. total file size estimate: 30 minutes at 1080p H.264 CRF 22 ≈ 350-450 MB.

### stage 4: intro / outro

reuse `render/shorts.py:120` `build_ffmpeg_argv` for the 9:16 vertical teaser:

```python
intro = build_ffmpeg_argv(
    in_path=out_mp4,
    out_path=intro_mp4,
    vertical=(1080, 1920),
    duration_sec=8,  # short teaser, ~8s
)
```

the intro is the first 8 seconds of the full video, cropped to 9:16, with a "WATCH THE FULL EPISODE" lower-third burned in. the outro is a separate static card with the next-week teaser + subscribe CTA.

## audio vs visual — audio first, visual as YouTube's "podcast" surface

the final `.mp4` is uploaded to YouTube as a "podcast" via the existing `yt/upload.py:283` `upload_episode()` with a new `category="podcast"` extension to the `episode.yaml` shape. YouTube's podcast surface indexes audio-only; the static card is just enough to satisfy the upload metadata. viewers who want a "real" video watch the daily recap reel (item 5.3 in the backlog, `dev/feature-backlog.md:351`); the podcast is for listeners.

**for Spotify / Apple Podcasts** — out of scope for v0. those platforms require an RSS feed; the upload path needs `feed.xml` generation. ship YouTube-only; the RSS feed is a v0.17.0 task.

## walk-through: Episode 1

concrete file list for `2026-W31`:

```
out/weekly/2026-W31/
  rollup.json                            (already written by weekly_rollup.py)
  podcast/
    script_2026-W31.txt                  18 KB  (3500 words, YAML segments)
    voice_2026-W31.wav                   62 MB  (30 min @ 22050 Hz mono PCM)
    week_card_2026-W31.mp4              410 MB  (30 min @ 1920x1080 H.264 + AAC)
    intro_2026-W31.mp4                   12 MB  (8s @ 1080x1920)
    outro_2026-W31.mp4                   10 MB  (8s @ 1080x1920)
    episode_2026-W31.mp4                432 MB  (final mux, intro + body + outro)
    episode_2026-W31.yaml                 2 KB  (episode metadata for yt.upload)
    cover_2026-W31.jpg                  180 KB  (1280x720 cover frame)
    pipeline_run.json                     1 KB  (stage timings + costs)
```

total: ~930 MB per week on disk. one quarter ≈ 12 GB; one year ≈ 50 GB. the existing `render.archive.py` (added 0.10.0) handles the offsite rsync — `vod_archive_on_failure=True` keeps failed weeks around too.

**runtime budget** (in CI / a dev box):

| stage | runtime | cost |
|---|---|---|
| script generation (LLM) | 15-30s | $0.10-0.20 |
| TTS synthesis | 30-60s | $0.20-0.30 (openai) |
| card frame generation | 2-3s | free (Pillow) |
| ffmpeg concat | 30-60s | free |
| intro/outro crop | 5-10s | free |
| youtube upload (existing) | 60-180s | free (already wired) |
| **total** | **~3-5 min** | **~$0.50/week** |

that's an order of magnitude cheaper than the daily VOD render (`render/pipeline.py:393` `run_pipeline()` is ~10-15 min per session × 5 days = 50-75 min/week) and the audience-facing product is *more* useful (audio-first, lower friction to consume).

## hosting format — script samples

the host wraps the week as one voice. sample script fragments:

**intro:**
> Welcome to Rivalry Week, the weekly podcast where we look at five days of simulated trading by 100 AI agents and figure out who was right. I'm your host, and this is week 31 of 2026, covering Monday August 4th through Friday August 8th. Five days, 212 trades, one paper account, and a pool P&L of plus one point four two percent. Let's get into it.

**day 1 (Tue Aug 5):**
> Day one, Tuesday. The opening bell rang at nine thirty and by nine forty-five, Mei Patel and Bob Huang were already on opposite sides of NVDA — Mei long, Bob short. That's the first of four times they'd take opposite sides of NVDA this week. Bob's read was "the move's exhausted, the chart's top-heavy." Mei's read was "this is the bottom of a pullback, the trend's your friend." The market sided with Mei — NVDA closed up three point one percent. Bob's short lost him eight hundred and forty dollars.

**week wrap:**
> So that's the week. Pool P&L plus one point four two. Mei Patel had the best week, up six point eight percent; Marcus Smith had the worst, down four point two. The strategy leaderboard: momentum plus five point three, mean reversion minus one point eight. The Mei-versus-Bob rivalry on NVDA finished three-one Mei. Next week, the strategy roster is shuffling — we're adding two new pairs agents and rotating the LSTM+LLM allocation. Should be a good one. See you Monday.

**the LLM inner-monologue pull** is the single most audience-ready line per day, pulled from the day's `agent_notes` table (`storage/journal.py:79`). one example from the round-8 doc (`docs/research/youtube-interesting.md:11`): `bb oversold px=99.5<lower=100.2`. the host reads these out verbatim — the audience loves jargon they can repeat.

## VOD studio — new tab + new rollup field

**new tab** in `web/src/vod/VodStudio.tsx`. add to the `SURFACES` array (`web/src/vod/VodStudio.tsx:53-58`):

```tsx
const SURFACES = [
  { id: "beats", label: "Beat Picker", sub: "per-beat" },
  { id: "pipeline", label: "Pipeline", sub: "run board" },
  { id: "session", label: "Session", sub: "control" },
  { id: "episode", label: "Episode", sub: "manifest" },
  { id: "interns", label: "Intern Watch", sub: "5 agents" },
  { id: "rivalries", label: "Rivalry Week", sub: "7-min format" },
  { id: "podcast", label: "Weekly Podcast", sub: "30-min audio" },  // NEW
] as const;
```

the new tab renders a `WeeklyPodcast` component that shows the last 4 weeks' episodes (mirrors the layout of `RivalryWeek` at `web/src/vod/RivalryWeek.tsx`), each with a `<video>` player + download link + "view on YouTube" link.

**new field** in the weekly rollup JSON (`session/weekly_rollup.py:245` `write_weekly_rollup`):

```python
return {
    "week_id": week_id,
    "date_range": [...],
    "strategy_rollup": ...,
    "rivalries": ...,
    "promotions": [...],
    "sessions": [...],
    "pool_pnl": ...,
    "pool_pnl_pct": ...,
    "podcast": {                          # NEW
        "path": "out/weekly/2026-W31/podcast/episode_2026-W31.mp4",
        "cover": "out/weekly/2026-W31/podcast/cover_2026-W31.jpg",
        "duration_sec": 1820,
        "size_bytes": 432_000_000,
        "uploaded_at": "2026-08-08T16:35:00Z",
        "youtube_video_id": "abc123",
    },
}
```

the field is optional — older rollups (pre-0.16.0) don't have it; new rollups populate it from `out/weekly/<week_id>/podcast/episode_*.mp4` if the file exists.

## CLI surface

```
# compose a weekly episode (assumes rollup.json + 5 daily manifests exist)
python -m tradefarm.render.podcast compose <week_id>

# dry-run: print the plan + costs
python -m tradefarm.render.podcast compose <week_id> --dry-run

# upload an existing episode to YouTube
python -m tradefarm.render.podcast upload <week_id>

# list available episodes
python -m tradefarm.render.podcast list

# regenerate script only (operator wants to tweak the LLM prompt)
python -m tradefarm.render.podcast script <week_id> --provider claude --voice alloy
```

`compose` is the operator's primary entry. `upload` is a thin wrapper over `yt.upload.upload_episode()` with the right `category="podcast"` and `playlist_ids=[<podcast_playlist>]`. the same `pipeline_runs` row pattern from the daily VOD scheduler (`src/tradefarm/orchestrator/scheduler.py:850`) wraps the compose run for crash-safety + restart idempotency.

## files to touch (impl checklist for the dev subagent)

| file | change | lines (est.) |
|---|---|---|
| `src/tradefarm/render/podcast.py` | new module: `compose_weekly_episode()`, `synthesize_voice()`, `render_static_card()`, `make_intro_outro()`, CLI | 600 |
| `src/tradefarm/render/pipeline.py` | new optional stage `podcast` (compose + upload), gated on `enable_podcast()` | 80 |
| `src/tradefarm/session/weekly_rollup.py` | add `podcast: {...}` field to the returned dict (read-on-demand, not computed in `compute_weekly_rollup`) | 30 |
| `src/tradefarm/tts/run.py` | extend `TTSOpts` with `podcast_mode: bool` (slight prosody tweaks — longer pauses at section breaks) | 30 |
| `src/tradefarm/yt/metadata.py` | new `kind="podcast"` branch in `build_episode_meta()` | 40 |
| `src/tradefarm/config.py` | add `podcast_tts_provider: str = "openai"`, `podcast_voice: str = "alloy"`, `podcast_enabled: bool = False` | 5 |
| `src/tradefarm/orchestrator/scheduler.py` | new `run_podcast_scheduler` task (fires Sat 09:00 ET, after the week's 5 daily sessions are settled) | 60 |
| `web/src/vod/WeeklyPodcast.tsx` | new tab component (lists last 4 weeks, video player per episode) | 200 |
| `web/src/vod/VodStudio.tsx` | add `podcast` to `SURFACES` array + tab route | 10 |
| `web/src/vod/types.ts` | add `WeeklyPodcast` to `Episode` type | 15 |
| `tests/render/test_podcast_compose.py` | new test — compose 1 week with a 5-day fixture, assert all expected files exist | 100 |
| `tests/render/test_podcast_script.py` | new test — LLM call is mocked; assert the YAML shape is correct | 60 |
| `docs/render/podcast.md` | new mini-doc in `docs/render/` (mirror the autonomy-pipeline style) | 200 |

**total: ~1430 lines.** larger than the recap scene (audio + video + new composer) but still under the `L` ceiling from item 4.5 (1 day). budget realistically 2-3 days for the first cut including the LLM prompt iteration; the test suite adds another ½ day.

## Recommendation

**build it.** the format fits the existing system, the cost is low (~$0.50/week + 5 min/week of compute), the audience ceiling is high (audio is the only YT surface for "long-form technical content you consume on a treadmill"), and the implementation reuses every existing module — `tts/run.py`, `render/shorts.py`, `yt/upload.py`, `session/weekly_rollup.py`. the only *new* code is the composer, the script prompt, the LLM voice config, and the VOD studio tab.

the alternative — a 30-minute *video* of the same content — costs 10x more (headless capture per beat × 5 days × 8-15 beats) and the audience doesn't get 10x value. the podcast is the right v0; a video version can be the v0.17.0 follow-up if the audience shows up.

ship with `openai` TTS (cost-conscious), `alloy` voice (the project's existing default — no new QA surface), and one static visual chassis. per-agent voice clones are a v0.18.0 follow-up that needs its own research doc.
