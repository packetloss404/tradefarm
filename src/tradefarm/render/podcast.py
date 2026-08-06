"""Rivalry Week weekly podcast composer.

Stitches 5 daily sessions into one ~30-min weekly podcast episode.
Audio-first: a single host voiceover over a static 1920x1080 "now
playing" card. Mirrors ``render/stitch.py``'s shape (one ffmpeg
invocation, audio + video inputs muxed) but the inputs are a
static card + a synthesised voice wav — not per-beat webm clips.

Pipeline::

    session/manifest_<dow>.json (5x)
    session/weekly_rollup_<week_id>.json (1x)
        |
        |  render.podcast.compose_weekly_episode(week_id, ...)
        v
   podcast/
     script_<week_id>.txt       (LLM script, ~3500 words, YAML)
     voice_<week_id>.wav       (TTS, ~30 min)
     week_card_<week_id>.mp4   (static visual, 1920x1080, ~30 min)
     intro_<week_id>.mp4       (vertical teaser, 9:16, 8s)
     outro_<week_id>.mp4       (vertical teaser, 9:16, 8s)
     episode_<week_id>.mp4     (final mux, 1920x1080, ~30 min)
     cover_<week_id>.jpg       (1280x720 cover frame)
     episode_<week_id>.yaml    (yt metadata payload)

Cost envelope: ~$0.50/week + ~3-5 min of wall time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from tradefarm.config import settings
from tradefarm.session import replay_query
from tradefarm.session.weekly_rollup import (
    read_weekly_rollup as _read_weekly_rollup,
)


# ----- constants ---------------------------------------------------------

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30
INTRO_OUTRO_SECONDS = 8
INTRO_OUTRO_VERTICAL = (1080, 1920)
COVER_WIDTH = 1280
COVER_HEIGHT = 720
CRF_VIDEO = 22
SAMPLE_RATE = 22_050
DAY_SEGMENTS = 5
DAY_KEYS: tuple[str, ...] = ("day_1", "day_2", "day_3", "day_4", "day_5")
SCRIPT_SEGMENT_KEYS: tuple[str, ...] = (
    "intro", "topline", "day_1", "day_2", "day_3", "day_4", "day_5", "wrap",
)

CANDIDATE_FONTS = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

try:  # Pillow is optional; the silence TTS path doesn't need it
    from PIL import Image as _PILImage  # type: ignore
    from PIL import ImageDraw as _PILImageDraw  # type: ignore
    from PIL import ImageFont as _PILImageFont  # type: ignore
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False


def _discover_font() -> str | None:
    for cand in CANDIDATE_FONTS:
        p = Path(cand)
        if p.is_file():
            return str(p)
    return None


log = structlog.get_logger()


# ----- record types ------------------------------------------------------


@dataclass
class Segment:
    """One host-narrated segment of the weekly episode."""

    day_idx: int | None
    headline: str
    sub: str
    body: str
    duration_sec: float = 0.0


# ----- paths + safety ----------------------------------------------------


def _weekly_dir(week_id: str, *, base: Path | None = None) -> Path:
    return (base or replay_query.DEFAULT_SESSIONS_DIR) / "weekly" / week_id


def _podcast_dir(week_id: str, *, base: Path | None = None) -> Path:
    return _weekly_dir(week_id, base=base) / "podcast"


def _safe_week_id(week_id: str) -> str:
    if not isinstance(week_id, str) or not week_id:
        raise ValueError("week_id must be a non-empty string")
    if ".." in week_id or "/" in week_id or "\\" in week_id or week_id.startswith("."):
        raise ValueError(f"invalid week_id {week_id!r}: traversal-like")
    if not re.match(r"^\d{4}-W\d{2}$", week_id):
        raise ValueError(
            f"invalid week_id {week_id!r}: must look like YYYY-Www (e.g. 2026-W31)"
        )
    return week_id


# ----- LLM script generation --------------------------------------------


SCRIPT_SYSTEM_PROMPT = """\
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


def build_script_prompt(
    *,
    week_id: str,
    date_str: str,
    date_range: str,
    rollup: dict[str, Any],
    daily_payloads: list[dict[str, Any]],
) -> str:
    payload_obj = {"rollup": rollup, "days": daily_payloads}
    return SCRIPT_SYSTEM_PROMPT.format(
        date=date_str,
        week_id=week_id,
        date_range=date_range,
        payload=json.dumps(payload_obj, indent=2, default=str),
    )


def _parse_script_yaml(text: str) -> dict[str, str]:
    """Lightweight YAML parser: walk line-by-line, collect the
    indented block following each ``key: |`` line. Forgiving — a
    missing key returns an empty string rather than raising."""
    out: dict[str, str] = {}
    lines = text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", lines[i].strip())
        if m and i + 1 < n and (lines[i + 1].startswith(" ") or lines[i + 1].startswith("\t")):
            key = m.group(1)
            j = i + 1
            block: list[str] = []
            while j < n and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                block.append(lines[j].lstrip())
                j += 1
            out[key] = " ".join(s.strip() for s in block if s.strip())
            i = j
            continue
        i += 1
    return out


# ----- LLM call ----------------------------------------------------------


def _call_llm_for_script(prompt: str) -> tuple[str, str, str]:
    """Call the configured LLM provider for the script. Returns
    ``(raw_text, provider_name, model_name)``. Raises on hard
    failure; callers fall back to the stub script."""
    try:
        from tradefarm.agents.llm_overlay import LlmOverlay
        from tradefarm.agents.llm_providers import AnthropicProvider, MinimaxProvider
    except ImportError as exc:
        raise RuntimeError(f"LLM provider unavailable: {exc}") from exc
    try:
        provider = LlmOverlay.from_settings().provider
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"no LLM creds: {exc}") from exc

    from tradefarm.runtime.http import get_shared_client, with_retries

    if isinstance(provider, AnthropicProvider):

        async def _run() -> str:
            msg = await provider.client.messages.create(
                model=provider.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text" and hasattr(b, "text"))

        return asyncio.run(_run()), provider.name, provider.model

    if isinstance(provider, MinimaxProvider):
        url = f"{provider.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": provider.model,
            "max_tokens": 4000,
            "temperature": 0.7,
            "messages": [{"role": "user", "content": prompt}],
        }

        async def _run() -> str:
            client = await get_shared_client()

            async def _post_once() -> dict:
                r = await client.post(url, json=body, headers=headers, timeout=60.0)
                r.raise_for_status()
                return r.json()

            data = await with_retries(_post_once, label="minimax_podcast_script")
            return data["choices"][0]["message"]["content"]

        return asyncio.run(_run()), provider.name, provider.model
    raise RuntimeError(f"unsupported LLM provider: {type(provider).__name__}")


def _stub_script(*, week_id: str, rollup: dict[str, Any]) -> dict[str, str]:
    """Hand-written fallback when no LLM provider is configured.
    Keeps the rest of the chain runnable in CI / dev boxes."""
    pool_pnl_pct = float(rollup.get("pool_pnl_pct") or 0.0)
    dr = rollup.get("date_range") or ["", ""]
    return {
        "intro": (
            f"Welcome to Rivalry Week, the weekly podcast where we look at five "
            f"days of simulated trading by one hundred AI agents. This is week "
            f"{week_id}, covering {dr[0]} through {dr[1]}."
        ),
        "topline": (
            f"Pool P&L this week: {pool_pnl_pct:+.2f} percent. The strategy "
            f"leaderboard had its usual mix of winners and losers. [stub script — "
            f"configure LLM creds for the real prose]"
        ),
        "day_1": "Day one. [stub script]",
        "day_2": "Day two. [stub script]",
        "day_3": "Day three. [stub script]",
        "day_4": "Day four. [stub script]",
        "day_5": "Day five. [stub script]",
        "wrap": f"That's the week. Pool P&L {pool_pnl_pct:+.2f} percent. See you Monday.",
    }


def generate_script(
    *,
    week_id: str,
    rollup: dict[str, Any],
    daily_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    dr = rollup.get("date_range") or ["", ""]
    date_range = (
        f"{dr[0]} to {dr[1]}"
        if isinstance(dr, list) and len(dr) == 2
        else "this week"
    )
    prompt = build_script_prompt(
        week_id=week_id,
        date_str=datetime.now(timezone.utc).date().isoformat(),
        date_range=date_range,
        rollup=rollup,
        daily_payloads=daily_payloads,
    )
    provider_name = "stub"
    model = ""
    raw: str
    try:
        raw, provider_name, model = _call_llm_for_script(prompt)
        segments = _parse_script_yaml(raw)
        if not segments:
            segments = {"wrap": raw.strip()}
    except Exception as exc:  # noqa: BLE001
        log.warning("podcast_script_llm_fallback", error=str(exc))
        segments = _stub_script(week_id=week_id, rollup=rollup)
        raw = "(stub — no LLM creds)"
    return {
        "week_id": week_id,
        "provider": provider_name,
        "model": model,
        "raw_response": raw,
        "segments": segments,
        "word_count": sum(len(s.split()) for s in segments.values()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_script_file(script: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# week_id: {script.get('week_id', 'unknown')}\n"
        f"# provider: {script.get('provider', 'stub')}\n"
        f"# model: {script.get('model', '')}\n"
        f"# generated_at: {script.get('generated_at', '')}\n"
        f"# word_count: {script.get('word_count', 0)}\n"
        f"# ----\n"
    )
    body = script.get("raw_response") or _segments_to_yaml(
        script.get("segments") or {}
    )
    out_path.write_text(header + body, encoding="utf-8")


def _segments_to_yaml(segments: dict[str, str]) -> str:
    out: list[str] = []
    for key, text in segments.items():
        out.append(f"{key}: |")
        for ln in text.splitlines():
            out.append(f"  {ln}")
        out.append("")
    return "\n".join(out)


def load_script_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"script file not found: {path}")
    text = path.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("# "))
    return _parse_script_yaml(body)


# ----- TTS synthesis -----------------------------------------------------


def synthesize_voice(
    script_path: Path,
    out_wav: Path,
    *,
    provider: str,
    voice: str,
) -> float:
    """Synthesise the whole script to one mono 22050 Hz wav."""
    if not script_path.is_file():
        raise FileNotFoundError(f"script file not found: {script_path}")
    segments = load_script_file(script_path)
    if not segments:
        raise ValueError(f"script file has no parseable segments: {script_path}")
    ordered = [(k, segments[k]) for k in SCRIPT_SEGMENT_KEYS if segments.get(k, "").strip()]
    for k, v in segments.items():
        if k not in SCRIPT_SEGMENT_KEYS and v.strip():
            ordered.append((k, v))

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    provider_lc = (provider or "silence").lower()
    if provider_lc in ("silence", "auto") and provider_lc == "silence":
        return _write_silence_wav(ordered, out_wav, voice)
    return _synthesize_cloud(ordered, out_wav, provider_lc, voice)


def _write_silence_wav(
    ordered: list[tuple[str, str]],
    out_wav: Path,
    voice: str,
) -> float:
    """Pure-Python silent wav sized to the total estimated speech.
    The 750ms tail per line mirrors SilentTtsProvider.PODCAST_TAIL_SEC
    — gives the host a dramatic pause between sections."""
    import wave

    wpm = 155
    tail_sec = 0.75
    total_words = sum(max(1, len(t.split())) for _, t in ordered)
    duration = round(60.0 * total_words / wpm + tail_sec * len(ordered), 2)
    n_frames = int(duration * SAMPLE_RATE)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * n_frames)
    log.info(
        "podcast_silence_voice",
        out=str(out_wav),
        duration_sec=duration,
        words=total_words,
        voice=voice,
    )
    return duration


def _synthesize_cloud(
    ordered: list[tuple[str, str]],
    out_wav: Path,
    provider: str,
    voice: str,
) -> float:
    """Cloud TTS path: one wav per segment + ffmpeg concat to one wav.
    The per-segment granularity lets the host add a 750ms silence
    between sections via the provider's `podcast_mode`."""
    from tradefarm.tts.run import build_provider

    obj = build_provider(provider)
    with tempfile.TemporaryDirectory(prefix="podcast_tts_") as tmp:
        tmp_dir = Path(tmp)
        segment_wavs: list[Path] = []
        for idx, (key, text) in enumerate(ordered):
            seg_wav = tmp_dir / f"{idx:02d}_{key}.wav"
            asyncio.run(
                obj.synthesize(
                    text,
                    voice=voice,
                    out_path=seg_wav,
                    podcast_mode=True,
                )
            )
            segment_wavs.append(seg_wav)
        list_file = tmp_dir / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in segment_wavs),
            encoding="utf-8",
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(out_wav),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed: "
                f"{(r.stderr or r.stdout or '').strip()[-400:]}"
            )
    duration = _wav_duration(out_wav)
    log.info(
        "podcast_cloud_voice",
        out=str(out_wav), provider=provider, voice=voice,
        duration_sec=duration, segments=len(ordered),
    )
    return duration


def _wav_duration(path: Path) -> float:
    import wave
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / (w.getframerate() or SAMPLE_RATE), 3)
    except (wave.Error, OSError):
        return 0.0


# ----- visual chassis (Pillow + ffmpeg) ----------------------------------


def _rollup_topline(rollup: dict[str, Any]) -> str:
    pool_pnl_pct = float(rollup.get("pool_pnl_pct") or 0.0)
    fill_count = sum(
        int(s.get("fill_count", 0) or 0)
        for s in (rollup.get("sessions") or [])
        if isinstance(s, dict)
    )
    sign = "+" if pool_pnl_pct >= 0 else ""
    return f"POOL P&L  {sign}{pool_pnl_pct:.2f}%    TRADES  {fill_count}   AGENTS  100"


def _top_rivals(rollup: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rollup.get("rivalries") or []:
        if isinstance(r, dict):
            out.append(r)
        if len(out) >= limit:
            break
    return out


def _ticker_line(rollup: dict[str, Any]) -> str:
    strat = rollup.get("strategy_rollup") or {}
    syms = list(strat.keys())[:6] if isinstance(strat, dict) else []
    bits = "   ".join(s.replace("_", " ").upper() for s in syms)
    return f"TICKER  {bits}" if bits else "TICKER  (no symbols yet)"


def _load_font(size: int):
    if not _PIL_AVAILABLE:
        return None
    path = _discover_font()
    if not path:
        return _PILImageFont.load_default()
    return _PILImageFont.truetype(path, size)


def render_static_card(
    week_id: str,
    segments: list[Segment],
    out_mp4: Path,
    voice_wav: Path,
    *,
    rollup: dict[str, Any] | None = None,
) -> None:
    """Render the body of the weekly episode: a single 1920x1080
    wallpaper that plays for the whole voice duration, with a
    per-segment text overlay baked in (one frame per segment, held
    for the segment's share of the voice duration)."""
    if not _PIL_AVAILABLE:
        raise RuntimeError(
            "Pillow is required for the podcast visual chassis "
            "(install pillow or run with --skip-card)."
        )
    if not voice_wav.is_file():
        raise FileNotFoundError(f"voice wav not found: {voice_wav}")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    voice_dur = _wav_duration(voice_wav)
    if voice_dur <= 0:
        voice_dur = sum(s.duration_sec for s in segments) or 1.0

    if rollup is None:
        rollup = _read_weekly_rollup(week_id) or {}
    total_words = sum(max(1, len(s.body.split())) for s in segments) or 1
    per_segment = [
        voice_dur * (max(1, len(s.body.split())) / total_words) for s in segments
    ]

    tmp = out_mp4.parent / f".podcast-card-{week_id}"
    tmp.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    try:
        for idx, seg in enumerate(segments):
            png = tmp / f"frame_{idx:02d}.png"
            _render_card_png(week_id=week_id, segment=seg, rollup=rollup, out_png=png)
            frames.append(png)
        if not frames:
            raise RuntimeError("no segments to render")

        list_file = tmp / "concat.txt"
        lines: list[str] = []
        for png, hold in zip(frames, per_segment):
            lines.append(f"file '{png.resolve().as_posix()}'")
            lines.append(f"duration {max(0.1, hold):.3f}")
        lines.append(f"file '{frames[-1].resolve().as_posix()}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-i", str(voice_wav),
            "-vsync", "vfr", "-r", str(DEFAULT_FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF_VIDEO),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart", str(out_mp4),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg card render failed: "
                f"{(r.stderr or r.stdout or '').strip()[-600:]}"
            )
        # Cover frame for the dashboard tab thumbnail.
        cover = out_mp4.parent / f"cover_{week_id}.jpg"
        try:
            if frames:
                # ``LANCZOS`` moved to ``Image.Resampling.LANCZOS`` in Pillow 9.1;
                # fall back to the legacy module-level attribute on older versions.
                _resampling = getattr(
                    _PILImage, "Resampling", _PILImage
                ).LANCZOS
                _PILImage.open(frames[0]).convert("RGB").resize(
                    (COVER_WIDTH, COVER_HEIGHT), _resampling
                ).save(cover, "JPEG", quality=85)
        except Exception as exc:  # noqa: BLE001
            log.warning("podcast_cover_failed", error=str(exc))
    finally:
        if not os.environ.get("KEEP_PODCAST_TMP"):
            for png in tmp.glob("frame_*.png"):
                png.unlink(missing_ok=True)
            for f in tmp.glob("concat.txt"):
                f.unlink(missing_ok=True)
            try:
                tmp.rmdir()
            except OSError:
                pass


def _render_card_png(
    *,
    week_id: str,
    segment: Segment,
    rollup: dict[str, Any],
    out_png: Path,
) -> None:
    """Compose one card frame via Pillow."""
    assert _PIL_AVAILABLE
    img = _PILImage.new("RGB", (DEFAULT_WIDTH, DEFAULT_HEIGHT), color=(12, 13, 16))
    draw = _PILImageDraw.Draw(img)
    font_l = _load_font(56)
    font_m = _load_font(36)
    font_s = _load_font(24)
    text = (231, 232, 236)
    dim = (94, 99, 111)
    accent = (212, 160, 46)

    dr = rollup.get("date_range") or ["", ""]
    dr_str = (
        f" · {dr[0]} to {dr[1]}"
        if isinstance(dr, list) and len(dr) == 2
        else ""
    )
    draw.text((60, 40), f"RIVALRY WEEK  ·  {week_id}{dr_str}", fill=text, font=font_m)
    draw.text((60, 100), _rollup_topline(rollup), fill=accent, font=font_m)
    day_label = (
        f"-- DAY {segment.day_idx} OF {DAY_SEGMENTS} --"
        if segment.day_idx is not None
        else segment.headline.upper() or "WEEKLY ROLLUP"
    )
    draw.text((60, 170), day_label, fill=dim, font=font_s)
    if segment.headline:
        draw.text((60, 230), segment.headline[:80], fill=text, font=font_l)
    rivals = _top_rivals(rollup, limit=3)
    if rivals:
        draw.text((60, 320), "RIVALRIES THIS WEEK", fill=dim, font=font_s)
        y = 350
        for r in rivals:
            line = (
                f"  agent #{r.get('a')} vs agent #{r.get('b')}  ·  "
                f"{r.get('symbol', '?')}  ·  {r.get('count', 0)} opposite-side fills"
            )
            draw.text((60, y), line, fill=text, font=font_s)
            y += 28
    draw.text((60, DEFAULT_HEIGHT - 80), _ticker_line(rollup), fill=dim, font=font_s)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png, "PNG")


# ----- intro / outro vertical teasers -----------------------------------


def make_intro_outro(
    *,
    week_id: str,
    body_mp4: Path,
    intro_mp4: Path,
    outro_mp4: Path,
) -> None:
    """Vertical 9:16 teasers. Intro = first 8s of body centre-cropped;
    outro = a static card with a "next week" headline. Mirrors the
    render/shorts.py crop formula."""
    if not body_mp4.is_file():
        raise FileNotFoundError(f"body mp4 not found: {body_mp4}")
    intro_mp4.parent.mkdir(parents=True, exist_ok=True)
    outro_mp4.parent.mkdir(parents=True, exist_ok=True)

    intro_argv = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", "0", "-t", str(INTRO_OUTRO_SECONDS),
        "-i", str(body_mp4),
        "-vf", "crop=ih*9/16:ih,scale=1080:1920:flags=lanczos",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF_VIDEO),
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        str(intro_mp4),
    ]
    r = subprocess.run(intro_argv, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg intro failed: {(r.stderr or r.stdout or '').strip()[-400:]}"
        )

    if _PIL_AVAILABLE:
        tmp = intro_mp4.parent / f".podcast-outro-{week_id}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            outro_png = tmp / "outro.png"
            _render_outro_png(week_id=week_id, out_png=outro_png)
            argv = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-i", str(outro_png),
                "-t", str(INTRO_OUTRO_SECONDS),
                "-vf", "crop=ih*9/16:ih,scale=1080:1920:flags=lanczos,format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF_VIDEO),
                "-r", str(DEFAULT_FPS), "-movflags", "+faststart",
                str(outro_mp4),
            ]
            r = subprocess.run(argv, capture_output=True, text=True, check=False)
            if r.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg outro failed: {(r.stderr or r.stdout or '').strip()[-400:]}"
                )
        finally:
            if not os.environ.get("KEEP_PODCAST_TMP"):
                for f in tmp.glob("*"):
                    f.unlink(missing_ok=True)
                try:
                    tmp.rmdir()
                except OSError:
                    pass
    else:
        # No Pillow → use the body as the outro source (truncated to 8s).
        argv = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", "0", "-t", str(INTRO_OUTRO_SECONDS),
            "-i", str(body_mp4),
            "-vf", "crop=ih*9/16:ih,scale=1080:1920:flags=lanczos",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF_VIDEO),
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            str(outro_mp4),
        ]
        r = subprocess.run(argv, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg outro fallback failed: "
                f"{(r.stderr or r.stdout or '').strip()[-400:]}"
            )


def _render_outro_png(*, week_id: str, out_png: Path) -> None:
    assert _PIL_AVAILABLE
    next_week = _next_week_id(week_id)
    img = _PILImage.new("RGB", (DEFAULT_WIDTH, DEFAULT_HEIGHT), color=(12, 13, 16))
    draw = _PILImageDraw.Draw(img)
    font_l = _load_font(96)
    font_m = _load_font(48)
    font_s = _load_font(28)
    draw.text((60, 200), "RIVALRY WEEK", fill=(212, 160, 46), font=font_l)
    draw.text((60, 320), f"week {week_id} wrap", fill=(231, 232, 236), font=font_m)
    draw.text(
        (60, DEFAULT_HEIGHT - 320), f"Next up: {next_week}",
        fill=(231, 232, 236), font=font_m,
    )
    draw.text(
        (60, DEFAULT_HEIGHT - 240), "Subscribe for the next episode",
        fill=(144, 148, 160), font=font_s,
    )
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png, "PNG")


def _next_week_id(week_id: str) -> str:
    year_str, _, week_str = week_id.partition("-W")
    try:
        from datetime import date as _date
        iso_year = int(year_str)
        iso_week = int(week_str)
        last = _date(iso_year, 12, 28).isocalendar()[1]
        if iso_week >= last:
            return f"{iso_year + 1:04d}-W01"
        return f"{iso_year:04d}-W{iso_week + 1:02d}"
    except (ValueError, TypeError):
        return f"{week_id}+1"


# ----- per-episode yaml metadata ----------------------------------------


def write_podcast_metadata(
    week_id: str,
    *,
    out_yaml: Path,
    episode_path: Path | None = None,
    cover_path: Path | None = None,
    duration_sec: int = 0,
    size_bytes: int = 0,
    uploaded_at: str | None = None,
    youtube_video_id: str | None = None,
    rollup: dict[str, Any] | None = None,
) -> None:
    if rollup is None:
        rollup = _read_weekly_rollup(week_id) or {}
    podcast_dir = _podcast_dir(week_id)
    ep = episode_path or (podcast_dir / f"episode_{week_id}.mp4")
    cover = cover_path or (podcast_dir / f"cover_{week_id}.jpg")
    meta = {
        "week_id": week_id,
        "kind": "podcast",
        "title": f"Rivalry Week · {week_id}",
        "description": _podcast_description(rollup),
        "tags": [
            "tradefarm", "ai trading", "paper trading",
            "rivalry week", "weekly podcast", "ai agents",
        ],
        "category_id": "22",
        "privacy_status": "private",
        "publish_at_iso": None,
        "duration_sec": int(duration_sec),
        "size_bytes": int(size_bytes),
        "uploaded_at": uploaded_at,
        "youtube_video_id": youtube_video_id,
        "video": str(ep) if ep.is_file() else None,
        "cover": str(cover) if cover.is_file() else None,
    }
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def _podcast_description(rollup: dict[str, Any]) -> str:
    pool_pnl_pct = rollup.get("pool_pnl_pct")
    dr = rollup.get("date_range") or []
    dr_str = (
        f" ({dr[0]} to {dr[1]})"
        if isinstance(dr, list) and len(dr) == 2
        else ""
    )
    pnl = ""
    if pool_pnl_pct is not None:
        sign = "+" if float(pool_pnl_pct) >= 0 else ""
        pnl = f" Pool P&L {sign}{float(pool_pnl_pct):.2f}%."
    return (
        f"Rivalry Week weekly podcast{dr_str}.{pnl} 30 minutes of paper "
        f"trading narrative across 5 daily sessions. Not financial advice."
    )


# ----- list / upload -----------------------------------------------------


def list_episodes(*, base_dir: Path | None = None) -> list[dict[str, Any]]:
    base = base_dir or replay_query.DEFAULT_SESSIONS_DIR
    out: list[dict[str, Any]] = []
    weekly_root = base / "weekly"
    if not weekly_root.is_dir():
        return out
    for week_dir in sorted(weekly_root.iterdir(), reverse=True):
        if not week_dir.is_dir():
            continue
        podcast_dir = week_dir / "podcast"
        if not podcast_dir.is_dir():
            continue
        candidates = sorted(podcast_dir.glob("episode_*.mp4"))
        if not candidates:
            continue
        episode = candidates[0]
        try:
            size_bytes = episode.stat().st_size
        except OSError:
            size_bytes = 0
        cover = podcast_dir / f"cover_{week_dir.name}.jpg"
        yaml_path = podcast_dir / f"episode_{week_dir.name}.yaml"
        out.append(
            {
                "week_id": week_dir.name,
                "path": str(episode),
                "cover": str(cover) if cover.is_file() else None,
                "duration_sec": _read_yaml_field(yaml_path, "duration_sec", 0),
                "size_bytes": size_bytes,
                "uploaded_at": _read_yaml_field(yaml_path, "uploaded_at", None),
                "youtube_video_id": _read_yaml_field(
                    yaml_path, "youtube_video_id", None
                ),
            }
        )
    return out


def _read_yaml_field(yaml_path: Path, field_name: str, default: Any) -> Any:
    if not yaml_path.is_file():
        return default
    try:
        data = json.loads(yaml_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if isinstance(data, dict):
        return data.get(field_name, default)
    return default


def upload_episode(week_id: str, *, dry_run: bool = False) -> str:
    """Upload the composed episode via the existing
    ``yt.upload.upload_episode`` path. Returns the YouTube video id
    (or ``"dry-run"`` in dry-run mode)."""
    import shutil

    from tradefarm.yt.metadata import build_episode_meta
    from tradefarm.yt.upload import upload_episode as _yt_upload

    _safe_week_id(week_id)
    base = replay_query.DEFAULT_SESSIONS_DIR
    meta = build_episode_meta(week_id, sessions_dir=base, kind="podcast")
    podcast_dir = base / "weekly" / week_id / "podcast"
    real_video = podcast_dir / f"episode_{week_id}.mp4"
    if not real_video.is_file():
        raise FileNotFoundError(f"episode mp4 missing: {real_video}")
    real_meta_path = podcast_dir / f"episode_{week_id}.yaml"

    if real_meta_path.is_file():
        try:
            existing = json.loads(real_meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict):
            try:
                existing["size_bytes"] = real_video.stat().st_size
            except OSError:
                pass
            existing["video"] = str(real_video)
            existing["uploaded_at"] = (
                existing.get("uploaded_at")
                or datetime.now(timezone.utc).isoformat()
            )
            real_meta_path.write_text(
                json.dumps(existing, indent=2, default=str), encoding="utf-8"
            )

    tmp_meta = podcast_dir / f"upload_{week_id}.json"
    tmp_meta.write_text(
        json.dumps(
            {
                "title": meta.title,
                "description": meta.description,
                "tags": list(meta.tags),
                "category_id": meta.category_id,
                "privacy_status": meta.privacy_status,
                "publish_at_iso": meta.publish_at_iso,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Build a temp session-like dir so yt.upload can find its
    # well-known inputs (`reel.mp4`, `thumb.jpg`, `episode.yaml`).
    with tempfile.TemporaryDirectory(prefix="podcast_upload_") as tmp:
        tmp_sdir = Path(tmp) / f"podcast_{week_id}"
        tmp_sdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real_video, tmp_sdir / "reel.mp4")
        if meta.thumbnail and meta.thumbnail.is_file():
            shutil.copy2(meta.thumbnail, tmp_sdir / "thumb.jpg")
        shutil.copy2(tmp_meta, tmp_sdir / "episode.yaml")
        result = asyncio.run(
            _yt_upload(
                tmp_sdir.name,
                sessions_dir=Path(tmp),
                upload_thumbnail=meta.thumbnail is not None,
                dry_run=dry_run,
            )
        )
    try:
        tmp_meta.unlink(missing_ok=True)
    except OSError:
        pass
    if not result.ok:
        raise RuntimeError(f"youtube upload failed: {result.error}")
    video_id = result.video_id or "dry-run"
    if real_meta_path.is_file():
        try:
            data = json.loads(real_meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            data["youtube_video_id"] = video_id
            data["uploaded_at"] = datetime.now(timezone.utc).isoformat()
            real_meta_path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
    return video_id


# ----- daily payload collector -----------------------------------------


def collect_daily_payloads(
    week_id: str,
    *,
    sessions_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Read the 5 daily session manifests that fall inside the
    trading week and return a slim payload per day. Used as the
    LLM's per-day context."""
    from tradefarm.session.weekly_rollup import _week_window  # internal but stable

    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    start, end = _week_window(week_id)
    out: list[dict[str, Any]] = []
    for sid_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        manifest_path = sid_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        started_at = manifest.get("started_at")
        if not started_at or not isinstance(started_at, str):
            continue
        try:
            t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t < start or t > end:
            continue
        beats_path = sid_dir / "beats.json"
        beats: list[dict[str, Any]] = []
        if beats_path.is_file():
            try:
                beats = json.loads(beats_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                beats = []
        top_beats = sorted(
            [b for b in beats if isinstance(b, dict)],
            key=lambda b: b.get("score", 0.0) or 0.0,
            reverse=True,
        )[:3]
        out.append(
            {
                "session_id": manifest.get("session_id") or sid_dir.name,
                "started_at": started_at,
                "fill_count": int(manifest.get("fill_count", 0) or 0),
                "strategy_rollup": manifest.get("strategy_rollup") or {},
                "rivalries": manifest.get("rivalries") or [],
                "top_beats": top_beats,
            }
        )
    return out[:DAY_SEGMENTS]


# ----- top-level compose -------------------------------------------------


def _segments_for_card(
    script: dict[str, Any],
    *,
    week_id: str,
    rollup: dict[str, Any],
) -> list[Segment]:
    segs = script.get("segments") or {}
    out: list[Segment] = []
    out.append(
        Segment(
            day_idx=None,
            headline=f"Rivalry Week · {week_id}",
            sub=_rollup_topline(rollup),
            body=segs.get("intro", ""),
        )
    )
    for idx, key in enumerate(DAY_KEYS, start=1):
        body = segs.get(key, "")
        first = body.split(".")[0] if body else f"Day {idx}"
        headline = first.strip()[:80] or f"Day {idx}"
        out.append(
            Segment(
                day_idx=idx,
                headline=headline,
                sub=f"Day {idx} of {DAY_SEGMENTS}",
                body=body,
            )
        )
    out.append(
        Segment(
            day_idx=None,
            headline="Week wrap + next-week teaser",
            sub=_rollup_topline(rollup),
            body=segs.get("wrap", ""),
        )
    )
    return out


def _mux_intro_body_outro(
    *,
    intro_mp4: Path,
    body_mp4: Path,
    outro_mp4: Path,
    out_mp4: Path,
) -> None:
    for p in (intro_mp4, body_mp4, outro_mp4):
        if not p.is_file():
            raise FileNotFoundError(f"concat input missing: {p}")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_mp4.parent / f".concat_{out_mp4.stem}.txt"
    list_file.write_text(
        "\n".join(
            f"file '{p.resolve().as_posix()}'"
            for p in (intro_mp4, body_mp4, outro_mp4)
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(out_mp4),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed: "
                f"{(r.stderr or r.stdout or '').strip()[-400:]}"
            )
    finally:
        list_file.unlink(missing_ok=True)


def compose_weekly_episode(
    week_id: str,
    *,
    sessions_dir: Path | None = None,
    voice: str | None = None,
    provider: str | None = None,
    dry_run: bool = False,
    skip_card: bool = False,
) -> Path:
    """Top-level entry: compose a weekly episode end-to-end."""
    started = time.perf_counter()
    _safe_week_id(week_id)
    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    rollup = _read_weekly_rollup(week_id, sessions_dir=base)
    if not rollup:
        raise FileNotFoundError(
            f"weekly rollup not found for {week_id} (run "
            "`tradefarm.session.weekly_rollup.compute_weekly_rollup` first)"
        )
    podcast_dir = _podcast_dir(week_id, base=base)
    podcast_dir.mkdir(parents=True, exist_ok=True)
    script_path = podcast_dir / f"script_{week_id}.txt"
    voice_path = podcast_dir / f"voice_{week_id}.wav"
    card_path = podcast_dir / f"week_card_{week_id}.mp4"
    intro_path = podcast_dir / f"intro_{week_id}.mp4"
    outro_path = podcast_dir / f"outro_{week_id}.mp4"
    episode_path = podcast_dir / f"episode_{week_id}.mp4"
    cover_path = podcast_dir / f"cover_{week_id}.jpg"
    metadata_path = podcast_dir / f"episode_{week_id}.yaml"

    eff_voice = voice or settings.podcast_voice
    eff_provider = provider or settings.podcast_tts_provider

    daily_payloads = collect_daily_payloads(week_id, sessions_dir=base)
    script = generate_script(
        week_id=week_id, rollup=rollup, daily_payloads=daily_payloads,
    )
    write_script_file(script, script_path)
    if dry_run:
        return script_path

    duration_sec = synthesize_voice(
        script_path=script_path, out_wav=voice_path,
        provider=eff_provider, voice=eff_voice,
    )
    segments = _segments_for_card(script, week_id=week_id, rollup=rollup)

    if not skip_card:
        render_static_card(
            week_id=week_id, segments=segments,
            out_mp4=card_path, voice_wav=voice_path,
            rollup=rollup,
        )
    else:
        card_path.write_bytes(b"")  # placeholder so the mux stage finds a file

    make_intro_outro(
        week_id=week_id, body_mp4=card_path,
        intro_mp4=intro_path, outro_mp4=outro_path,
    )

    if not skip_card:
        _mux_intro_body_outro(
            intro_mp4=intro_path, body_mp4=card_path,
            outro_mp4=outro_path, out_mp4=episode_path,
        )
    else:
        # In --skip-card mode the "episode" is just the (empty) body.
        if card_path.is_file():
            episode_path.write_bytes(card_path.read_bytes())

    size_bytes = 0
    if episode_path.is_file():
        try:
            size_bytes = episode_path.stat().st_size
        except OSError:
            pass
    write_podcast_metadata(
        week_id=week_id, out_yaml=metadata_path,
        episode_path=episode_path,
        cover_path=cover_path if cover_path.is_file() else None,
        duration_sec=int(duration_sec), size_bytes=size_bytes,
        rollup=rollup,
    )
    log.info(
        "podcast_composed",
        week_id=week_id, episode=str(episode_path),
        duration_sec=round(duration_sec, 2),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return episode_path


# ----- CLI --------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """`python -m tradefarm.render.podcast {compose,upload,list,script} ...`"""
    parser = argparse.ArgumentParser(
        prog="tradefarm.render.podcast",
        description=(
            "Compose the Rivalry Week weekly podcast (audio-first, 30-min) "
            "from 5 daily sessions + the weekly rollup. See "
            "docs/research/podcast-format.md for the design."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_compose = sub.add_parser("compose", help="Compose a weekly podcast episode end-to-end.")
    p_compose.add_argument("week_id")
    p_compose.add_argument("--out", type=Path, default=None)
    p_compose.add_argument("--voice", default=None, help=f"TTS voice (default: {settings.podcast_voice}).")
    p_compose.add_argument(
        "--provider", default=None,
        choices=["auto", "elevenlabs", "openai", "silence"],
        help=f"TTS provider (default: {settings.podcast_tts_provider}).",
    )
    p_compose.add_argument("--dry-run", action="store_true",
                           help="Run script generation only; skip TTS / ffmpeg.")
    p_compose.add_argument("--skip-card", action="store_true",
                           help="Skip the visual chassis render (tests / CI only).")

    p_upload = sub.add_parser("upload", help="Upload a composed episode to YouTube.")
    p_upload.add_argument("week_id")
    p_upload.add_argument("--dry-run", action="store_true")

    p_list = sub.add_parser("list", help="List every composed weekly episode.")
    p_list.add_argument("--out", type=Path, default=None)

    p_script = sub.add_parser("script", help="Regenerate the LLM script only.")
    p_script.add_argument("week_id")
    p_script.add_argument("--out", type=Path, default=None)
    p_script.add_argument("--provider", default=None)
    p_script.add_argument("--voice", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "compose":
        out = compose_weekly_episode(
            args.week_id, sessions_dir=args.out, voice=args.voice,
            provider=args.provider, dry_run=args.dry_run, skip_card=args.skip_card,
        )
        print(f"week_id={args.week_id}\nout={out}")
        return
    if args.cmd == "upload":
        vid = upload_episode(args.week_id, dry_run=args.dry_run)
        print(f"week_id={args.week_id}\nyoutube_video_id={vid}")
        return
    if args.cmd == "list":
        rows = list_episodes(base_dir=args.out)
        print(f"episodes={len(rows)}")
        for row in rows:
            print(
                f"  {row['week_id']}  size={row['size_bytes']:,}  "
                f"duration={row['duration_sec']}s  "
                f"yt={row['youtube_video_id'] or '-'}"
            )
        return
    if args.cmd == "script":
        base = args.out or replay_query.DEFAULT_SESSIONS_DIR
        rollup = _read_weekly_rollup(args.week_id)
        if not rollup:
            raise SystemExit(f"rollup not found for {args.week_id}")
        daily = collect_daily_payloads(args.week_id, sessions_dir=base)
        script = generate_script(
            week_id=args.week_id, rollup=rollup, daily_payloads=daily,
        )
        out_path = _podcast_dir(args.week_id, base=base) / f"script_{args.week_id}.txt"
        write_script_file(script, out_path)
        print(
            f"week_id={args.week_id}\nscript={out_path}\n"
            f"provider={script['provider']}  model={script['model']}\n"
            f"word_count={script['word_count']}"
        )
        return
    parser.error(f"unknown subcommand {args.cmd!r}")


if __name__ == "__main__":
    main()
