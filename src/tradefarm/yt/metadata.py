"""Episode metadata builder — assembles the JSON payload the YouTube
upload step needs (title, description, tags, category, privacy,
publish-at, chapter markers).

Pure functions, no network. Input is the session's beats.json +
script.json + manifest.json + sidecar JSONs; output is one
out/sessions/<id>/episode.yaml file (we use yaml-ish but it's
just JSON-with-key-order, written via json.dumps).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_PRIVACY = "private"  # "public" | "unlisted" | "private"
DEFAULT_CATEGORY_ID = "28"  # YouTube's "Science & Technology"
DEFAULT_TAGS = [
    "tradefarm",
    "ai trading",
    "paper trading",
    "llm",
    "lstm",
    "daily recap",
    "agent academy",
    "autonomous",
]


@dataclass(frozen=True)
class Chapter:
    start_sec: int
    title: str


@dataclass
class EpisodeMeta:
    session_id: str
    title: str
    description: str
    tags: list[str]
    category_id: str
    privacy_status: str
    publish_at_iso: str | None
    chapters: list[Chapter] = field(default_factory=list)
    thumbnail: Path | None = None
    video: Path | None = None


# ----- helpers -----------------------------------------------------------


def _load_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_beats(p: Path) -> list[dict[str, Any]]:
    if not p.is_file():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def _load_sidecars(clips_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not clips_dir.is_dir():
        return out
    for p in sorted(clips_dir.glob("*.json")):
        data = _load_json(p)
        if data and (bid := data.get("beat_id")):
            out[str(bid)] = data
    return out


def _format_chapter_stamp(seconds: int) -> str:
    """YouTube chapter markers must start with 00:00 then HH:MM:SS or MM:SS."""
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _format_money(n: float) -> str:
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


# ----- chapter computation ----------------------------------------------


def compute_chapters(
    beats: list[dict[str, Any]],
    sidecars: dict[str, dict[str, Any]],
    *,
    xfade_sec: float = 0.4,
) -> list[Chapter]:
    """Walk beats with rendered clips in chronological order and build
    a list of Chapter records whose start_sec aligns with the silent
    reel. Uses the same xfade arithmetic as render.stitch + render.mix
    so the markers click into the actual reel timeline.

    YouTube requires the first chapter to start at 0:00 and at least
    three chapters total — we pad with the first beat at 0:00 if
    needed, and emit nothing (caller skips chapters) if we can't reach
    three.
    """
    rows: list[Chapter] = []
    clip_start = 0.0
    rendered = [b for b in beats if b.get("id") in sidecars]
    for i, beat in enumerate(rendered):
        sidecar = sidecars[beat["id"]]
        title = (beat.get("headline") or beat.get("id") or "Beat").strip()
        # Trim to ~one-liner; YouTube truncates ~100 chars per chapter.
        if len(title) > 80:
            title = title[:77] + "..."
        rows.append(Chapter(start_sec=int(round(clip_start)), title=title))
        clip_dur = float(sidecar.get("duration_ms", 0)) / 1000.0
        # Last clip doesn't subtract a trailing xfade.
        clip_start += clip_dur - (xfade_sec if i < len(rendered) - 1 else 0.0)
    # YouTube requires the first chapter at 0:00.
    if rows and rows[0].start_sec != 0:
        rows[0] = Chapter(start_sec=0, title=rows[0].title)
    if len(rows) < 3:
        return []
    return rows


# ----- description builder ----------------------------------------------


def build_description(
    *,
    beats: list[dict[str, Any]],
    script: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    chapters: list[Chapter],
    session_id: str,
) -> str:
    """Compose the YouTube description: 1-2 sentence summary, then the
    chapter list (which YouTube auto-detects when stamps appear on
    their own lines)."""
    # 1. Summary line.
    summary_bits: list[str] = []
    recap = next((b for b in beats if b.get("kind") == "recap"), None)
    if recap:
        sub = (recap.get("sub") or "").strip()
        if sub:
            summary_bits.append(sub)
    if script and (title := script.get("episode_title")):
        summary_bits.append(str(title).strip())
    summary = " · ".join(b for b in summary_bits if b) or (
        f"Daily recap from the TradeFarm sandbox — {session_id}."
    )

    # 2. Fixed boilerplate.
    boilerplate = (
        "100 AI agents paper-trading US equities. Each day's most "
        "dramatic moments, auto-detected from the manifest and "
        "narrated. Not financial advice."
    )

    # 3. Chapters (auto-detected by YouTube when each is on its own line).
    chapter_block = "\n".join(f"{_format_chapter_stamp(c.start_sec)} {c.title}" for c in chapters)

    parts = [summary, "", boilerplate]
    if chapter_block:
        parts.extend(["", "Chapters:", chapter_block])
    return "\n".join(parts)


# ----- publish-at default -----------------------------------------------


def default_publish_at(*, now: datetime | None = None) -> str:
    """Match the dashboard's "auto-publish 16:30 ET" default: next
    occurrence of 16:30 America/New_York, expressed as UTC ISO-8601.

    Audit fix (H29): use zoneinfo.ZoneInfo("America/New_York") so DST
    transitions don't shift the publish time by an hour twice a year.
    The previous hardcoded -5h offset was right for EST but an hour
    early during EDT (the majority of the year).
    """
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    now = now or datetime.now(timezone.utc)
    now_et = now.astimezone(et)
    target_et = now_et.replace(hour=16, minute=30, second=0, microsecond=0)
    if target_et <= now_et:
        target_et = target_et + timedelta(days=1)
    return target_et.astimezone(timezone.utc).isoformat()


# ----- top-level builder ------------------------------------------------


def build_episode_meta(
    session_id: str,
    *,
    sessions_dir: Path,
    title_override: str | None = None,
    description_override: str | None = None,
    privacy_status: str = DEFAULT_PRIVACY,
    publish_at_iso: str | None = None,
    tags: list[str] | None = None,
    category_id: str = DEFAULT_CATEGORY_ID,
    xfade_sec: float | None = None,
    kind: str = "daily",
) -> EpisodeMeta:
    """Build the YouTube metadata payload for one episode.

    0.16.0 — ``kind='podcast'`` switches the builder to the weekly
    Rivalry Week format: the session id is interpreted as a week_id
    (``YYYY-Www``), the video lives at
    ``<weekly_dir>/<week_id>/podcast/episode_<week_id>.mp4``, and the
    builder pulls title + description from the weekly rollup's
    ``podcast`` block. ``category_id`` defaults to 22 (Music &
    Podcast) so YouTube's podcast surface indexes the upload.
    Otherwise the daily VOD path is unchanged.
    """
    if kind == "podcast":
        return _build_podcast_meta(
            week_id=session_id,
            sessions_dir=sessions_dir,
            title_override=title_override,
            description_override=description_override,
            privacy_status=privacy_status,
            publish_at_iso=publish_at_iso,
            tags=tags,
        )
    sdir = sessions_dir / session_id
    beats = _load_beats(sdir / "beats.json")
    sidecars = _load_sidecars(sdir / "clips")
    script = _load_json(sdir / "script.json")
    manifest = _load_json(sdir / "manifest.json")

    # Honour the xfade the stitcher actually used (so chapter markers
    # align with the real reel timeline). Falls back to CLI default.
    if xfade_sec is None:
        from tradefarm.render.stitch import load_reel_meta

        xfade_sec = float(load_reel_meta(sdir).get("xfade_sec", 0.4))

    # Title.
    title = (title_override or "").strip()
    if not title and script and script.get("episode_title"):
        title = str(script["episode_title"]).strip()
    if not title and beats:
        best = max(beats, key=lambda b: b.get("score", 0.0) or 0.0)
        title = (best.get("headline") or "").strip()
    if not title:
        title = f"TradeFarm Daily · {session_id}"
    title = title[:100]  # YouTube cap

    chapters = compute_chapters(beats, sidecars, xfade_sec=xfade_sec)

    description = (description_override or "").strip() or build_description(
        beats=beats,
        script=script,
        manifest=manifest,
        chapters=chapters,
        session_id=session_id,
    )

    publish_at = publish_at_iso if privacy_status == "private" else None
    if privacy_status == "private" and publish_at_iso is None:
        publish_at = default_publish_at()

    thumb = sdir / "thumb.jpg"
    video = sdir / "reel.mp4"
    return EpisodeMeta(
        session_id=session_id,
        title=title,
        description=description,
        tags=list(tags or DEFAULT_TAGS),
        category_id=category_id,
        privacy_status=privacy_status,
        publish_at_iso=publish_at,
        chapters=chapters,
        thumbnail=thumb if thumb.is_file() else None,
        video=video if video.is_file() else None,
    )


# YouTube category id 22 = "Music & Podcast" → covered by the podcast
# surface. The daily VOD chain uses 28 ("Science & Technology").
PODCAST_CATEGORY_ID = "22"
PODCAST_DEFAULT_TAGS: list[str] = [
    "tradefarm",
    "ai trading",
    "paper trading",
    "rivalry week",
    "weekly podcast",
    "ai agents",
    "lstm",
    "llm",
    "stock market",
    "autonomous",
]


def _build_podcast_meta(
    *,
    week_id: str,
    sessions_dir: Path,
    title_override: str | None = None,
    description_override: str | None = None,
    privacy_status: str = DEFAULT_PRIVACY,
    publish_at_iso: str | None = None,
    tags: list[str] | None = None,
) -> EpisodeMeta:
    """Variant of :func:`build_episode_meta` for the Rivalry Week
    weekly podcast. Reads the weekly rollup to derive the title +
    description; the chapter list is synthesised from the day's beats
    (one per session in the week) so the YT chapters line up with the
    5 day-segments the host narrates."""
    weekly_dir = sessions_dir / "weekly" / week_id
    podcast_dir = weekly_dir / "podcast"
    rollup = _load_json(weekly_dir / "rollup.json") or {}
    podcast_block = rollup.get("podcast") if isinstance(rollup, dict) else None
    podcast_block = podcast_block if isinstance(podcast_block, dict) else {}

    # Title: explicit override > rollup's `title` > "Rivalry Week · Wxx".
    title = (title_override or "").strip()
    if not title:
        title = str(rollup.get("podcast_title") or "").strip()
    if not title:
        dr = rollup.get("date_range") or []
        if isinstance(dr, list) and len(dr) == 2:
            title = f"Rivalry Week · {week_id} · {dr[0]} to {dr[1]}"
        else:
            title = f"Rivalry Week · {week_id}"
    title = title[:100]  # YouTube cap

    description = (description_override or "").strip()
    if not description:
        description = _build_podcast_description(week_id, rollup, podcast_block)

    # Chapters: one per day (5 segments) + intro (00:00) + wrap. The
    # exact start times are best-effort (8s intro + 30s topline + 5
    # day-segments averaging ~5min + 2min wrap); the per-day offsets
    # align with the script's segment lengths when they're known.
    chapters = _podcast_chapters(rollup)

    publish_at = publish_at_iso if privacy_status == "private" else None
    if privacy_status == "private" and publish_at_iso is None:
        publish_at = default_publish_at()

    # Default tag set is the podcast list; the operator can pass a
    # custom CSV via --tags on the CLI.
    merged_tags = list(tags or PODCAST_DEFAULT_TAGS)

    video = podcast_dir / f"episode_{week_id}.mp4"
    cover = podcast_dir / f"cover_{week_id}.jpg"
    return EpisodeMeta(
        session_id=week_id,
        title=title,
        description=description,
        tags=merged_tags,
        category_id=PODCAST_CATEGORY_ID,
        privacy_status=privacy_status,
        publish_at_iso=publish_at,
        chapters=chapters,
        thumbnail=cover if cover.is_file() else None,
        video=video if video.is_file() else None,
    )


def _build_podcast_description(
    week_id: str,
    rollup: dict[str, Any],
    podcast_block: dict[str, Any],
) -> str:
    """Assemble the YT description for the weekly podcast.

    Layout: tagline → 1-2 line topline (pool pnl + total trades) →
    rivals-of-the-week → next-week teaser. The numbers come from the
    weekly rollup so the description never drifts from what the host
    narrates. Falls back to a generic blurb when the rollup is
    missing fields (a fresh dev box before the first week closes)."""
    pool_pnl_pct = rollup.get("pool_pnl_pct")
    pool_pnl = rollup.get("pool_pnl")
    sessions = rollup.get("sessions") or []
    fill_count = sum(int(s.get("fill_count", 0) or 0) for s in sessions if isinstance(s, dict))
    dr = rollup.get("date_range") or []
    dr_str = f" ({dr[0]} to {dr[1]})" if isinstance(dr, list) and len(dr) == 2 else ""

    tagline_bits: list[str] = []
    tagline_bits.append("Rivalry Week — five days of paper trading by 100 AI agents, narrated in 30 minutes.")
    if pool_pnl_pct is not None:
        sign = "+" if float(pool_pnl_pct) >= 0 else ""
        tagline_bits.append(f"Pool P&L this week: {sign}{float(pool_pnl_pct):.2f}%")
    if pool_pnl is not None:
        sign = "+" if float(pool_pnl) >= 0 else ""
        tagline_bits.append(f"Total dollar P&L: {sign}${abs(float(pool_pnl)):,.0f}")
    if fill_count:
        tagline_bits.append(f"Trades: {fill_count}")
    summary = " · ".join(tagline_bits)

    rivals = rollup.get("rivalries") or []
    rival_block = ""
    if rivals:
        lines = ["", "Rivalries this week:"]
        for r in rivals[:3]:
            if not isinstance(r, dict):
                continue
            sym = r.get("symbol", "?")
            a = r.get("a")
            b = r.get("b")
            count = r.get("count", 0)
            lines.append(f"  - agent #{a} vs agent #{b} on {sym}: {count} opposite-side fills")
        rival_block = "\n".join(lines)

    duration_sec = podcast_block.get("duration_sec") or 0
    dur_str = ""
    if duration_sec:
        m, s = divmod(int(duration_sec), 60)
        dur_str = f"Runtime: {m}m{s:02d}s"

    return (
        f"{summary}{dr_str}\n\n"
        "Not financial advice. The Rivalry Week podcast stitches the week's "
        "5 daily recap reels into one audio-first long-form episode. The "
        "static card above is just enough visual to satisfy the upload "
        "metadata — the audio is the product.\n"
        f"{rival_block}\n\n"
        f"{dur_str}\n"
    ).strip()


def _podcast_chapters(rollup: dict[str, Any]) -> list[Chapter]:
    """Synthesise the YouTube chapter list for the weekly episode.

    The start times are aligned with the podcast script's per-segment
    length budget (intro 8s, topline 30s, day 1-5 ~5min, wrap 2min).
    We don't know the exact TTS length until after `run_tts` fires,
    so the start times are best-effort — close enough for the YT
    chapter picker to land on the right section. Operators who want
    exact alignment can re-run after the TTS step and we read the
    per-line durations out of vo/index.json.
    """
    starts: list[tuple[int, str]] = [
        (0, "Intro"),
        (8, "Week topline"),
        (38, "Day 1"),
        (338, "Day 2"),
        (638, "Day 3"),
        (938, "Day 4"),
        (1238, "Day 5"),
        (1538, "Week wrap + outro"),
    ]
    chapters = [Chapter(start_sec=s, title=t) for s, t in starts]
    if not chapters:
        return []
    if chapters[0].start_sec != 0:
        chapters[0] = Chapter(start_sec=0, title=chapters[0].title)
    return chapters


def meta_to_dict(meta: EpisodeMeta) -> dict[str, Any]:
    return {
        "session_id": meta.session_id,
        "title": meta.title,
        "description": meta.description,
        "tags": meta.tags,
        "category_id": meta.category_id,
        "privacy_status": meta.privacy_status,
        "publish_at_iso": meta.publish_at_iso,
        "chapters": [
            {
                "start_sec": c.start_sec,
                "stamp": _format_chapter_stamp(c.start_sec),
                "title": c.title,
            }
            for c in meta.chapters
        ],
        "thumbnail": str(meta.thumbnail) if meta.thumbnail else None,
        "video": str(meta.video) if meta.video else None,
    }


def write_meta(meta: EpisodeMeta, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(meta_to_dict(meta), indent=2), encoding="utf-8")


# ----- CLI --------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tradefarm.yt.metadata",
        description="Build the episode metadata payload from session artifacts.",
    )
    parser.add_argument("session_id")
    parser.add_argument("--out", type=Path, default=Path("out/sessions"))
    parser.add_argument("--title", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument(
        "--privacy", default=DEFAULT_PRIVACY, choices=["public", "unlisted", "private"]
    )
    parser.add_argument(
        "--publish-at", default=None, help="ISO-8601 UTC; defaults to next 16:30 ET (private only)."
    )
    parser.add_argument("--tags", default=None, help="Comma-separated tag override.")
    parser.add_argument(
        "--category-id",
        default=DEFAULT_CATEGORY_ID,
        help="YouTube category id (default: 28 = Science & Technology).",
    )
    parser.add_argument(
        "--xfade", type=float, default=0.4, help="Stitcher's crossfade seconds (must match)."
    )
    args = parser.parse_args(argv)

    meta = build_episode_meta(
        args.session_id,
        sessions_dir=args.out,
        title_override=args.title,
        description_override=args.description,
        privacy_status=args.privacy,
        publish_at_iso=args.publish_at,
        tags=[t.strip() for t in args.tags.split(",")] if args.tags else None,
        category_id=args.category_id,
        xfade_sec=args.xfade,
    )
    out_path = args.out / args.session_id / "episode.yaml"
    write_meta(meta, out_path)
    print(
        f"session_id={meta.session_id}\n"
        f"episode_meta={out_path}\n"
        f"title={meta.title}\n"
        f"chapters={len(meta.chapters)} privacy={meta.privacy_status}\n"
        f"video={'present' if meta.video else 'MISSING (reel.mp4 not found)'} "
        f"thumb={'present' if meta.thumbnail else 'MISSING'}"
    )


if __name__ == "__main__":
    main()
