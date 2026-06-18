"""Thumbnail generator — picks the highest-scoring beat's clip, grabs
a mid-frame, overlays the episode title + pool P&L badge, writes
out/sessions/<id>/thumb.jpg (1280×720, JPEG).

Input:  out/sessions/<id>/beats.json     (to pick the best beat)
        out/sessions/<id>/clips/*.webm   (frame source via ffmpeg)
        (optional) script.json           (for episode_title override)
        (optional) manifest.json         (for pool P&L badge)
Output: out/sessions/<id>/thumb.jpg      (1280×720, ~150-250 KB)

Selection heuristic:
  1. Highest-score beat whose clip exists on disk.
  2. Fall back to the first available clip in chronological order.

Mid-frame grab via `ffmpeg -ss <half_dur> -i <clip> -vframes 1 -q:v 2`,
PNG → Pillow for the overlay so we don't need libfreetype in ffmpeg
(we already require system ffmpeg for the stitcher + mixer; Pillow is
already a dev dep). Result is JPEG at q=88 — sweet spot for YouTube's
2 MB upload cap.

Title: from script.json's `episode_title` if present, else
"Today on TradeFarm · EP NNN" using the session date for the number
fallback. Pool P&L badge pulled from the recap beat's metadata when
available; otherwise omitted cleanly.

System ffmpeg required (frame grab). Pillow required (overlay).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_QUALITY = 88
DEFAULT_TITLE = "Today on TradeFarm"


@dataclass
class ThumbPlan:
    session_id: str
    source_clip: Path
    grab_at_sec: float
    title: str
    badge_text: str | None
    out_path: Path
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT


@dataclass
class ThumbResult:
    ok: bool
    out_path: Path | None = None
    plan: ThumbPlan | None = None
    elapsed_ms: float | None = None
    error: str | None = None


# ----- helpers -----------------------------------------------------------


def _load_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_beats(beats_path: Path) -> list[dict[str, Any]]:
    if not beats_path.is_file():
        return []
    try:
        rows = json.loads(beats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def pick_source_beat(
    beats: list[dict[str, Any]],
    clips_dir: Path,
) -> tuple[dict[str, Any], Path] | None:
    """Highest-score beat whose clip exists; falls back to first
    existing clip in beats order."""
    if not beats:
        return None
    # Score-sorted candidates first.
    by_score = sorted(beats, key=lambda b: -(b.get("score", 0.0) or 0.0))
    for b in by_score:
        clip = clips_dir / f"{b['id']}.webm"
        if clip.is_file():
            return b, clip
    for b in beats:
        clip = clips_dir / f"{b['id']}.webm"
        if clip.is_file():
            return b, clip
    return None


def _format_money(n: float) -> str:
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


def derive_title(
    beats: list[dict[str, Any]],
    script: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    session_id: str,
) -> str:
    if script and isinstance(script.get("episode_title"), str) and script["episode_title"].strip():
        return script["episode_title"].strip()
    # Best beat's headline as a fallback (drops trailing "—" / "·" tails).
    if beats:
        best = max(beats, key=lambda b: b.get("score", 0.0) or 0.0)
        headline = (best.get("headline") or "").strip()
        if headline:
            return headline[:80]
    # Last-ditch: session date.
    if manifest:
        days = manifest.get("trading_days") or []
        if days:
            return f"{DEFAULT_TITLE} · {days[0]}"
    return f"{DEFAULT_TITLE} · {session_id}"


def derive_badge(beats: list[dict[str, Any]]) -> str | None:
    """If the recap beat exists, surface its pool P&L in the badge."""
    for b in beats:
        if b.get("kind") == "recap":
            md = b.get("metadata") or {}
            pnl = md.get("realized_pnl")
            if isinstance(pnl, (int, float)):
                return _format_money(float(pnl))
            sub = (b.get("sub") or "").strip()
            if sub:
                return sub[:32]
    return None


# ----- frame grab + overlay (impure) -------------------------------------


def _grab_frame(clip: Path, at_sec: float, out_png: Path) -> None:
    """Pull one PNG frame from `clip` at `at_sec` via ffmpeg."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{at_sec:.3f}",
            "-i",
            str(clip),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(out_png),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg frame grab failed: {r.stderr.strip()[:300]}")
    if not out_png.is_file():
        raise RuntimeError("ffmpeg grabbed no frame")


def _wrap_title(draw, text: str, font, max_width_px: int) -> list[str]:
    """Wrap `text` to lines that each fit within max_width_px pixels."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        candidate = " ".join(current + [w])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if (bbox[2] - bbox[0]) <= max_width_px or not current:
            current.append(w)
        else:
            lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
    return lines


def _compose_thumb(
    *,
    frame_png: Path,
    out_path: Path,
    title: str,
    badge_text: str | None,
    width: int,
    height: int,
    quality: int,
) -> None:
    """Render the final thumbnail: cover-fit the frame, dark gradient
    over the bottom-left, title text, optional badge."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover — env-dependent
        raise RuntimeError("Pillow not installed. `uv sync --extra dev` to pick it up.") from exc

    base = Image.open(frame_png).convert("RGB")
    # Cover-crop to the target aspect ratio.
    target_ratio = width / height
    src_ratio = base.width / base.height
    if src_ratio > target_ratio:
        # crop horizontal
        new_w = int(base.height * target_ratio)
        x0 = (base.width - new_w) // 2
        base = base.crop((x0, 0, x0 + new_w, base.height))
    elif src_ratio < target_ratio:
        new_h = int(base.width / target_ratio)
        y0 = (base.height - new_h) // 2
        base = base.crop((0, y0, base.width, y0 + new_h))
    base = base.resize((width, height), Image.Resampling.LANCZOS)

    # Dark gradient over bottom 55% so white text reads.
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    grad_top = int(height * 0.45)
    for y in range(grad_top, height):
        # 0 → 180 alpha as we go down.
        alpha = int(180 * (y - grad_top) / max(1, (height - grad_top)))
        od.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    composed = Image.alpha_composite(base.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(composed)
    title_font = _load_font(72)
    badge_font = _load_font(36)
    branding_font = _load_font(22)

    # Title — wrap to 2 lines max.
    title_lines = _wrap_title(draw, title, title_font, max_width_px=width - 100)[:2]
    line_height = int(72 * 1.15)
    block_h = line_height * len(title_lines)
    title_y = height - 80 - block_h
    for i, line in enumerate(title_lines):
        y = title_y + i * line_height
        # Stroke + fill for legibility against any frame.
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            draw.text((50 + dx, y + dy), line, font=title_font, fill=(0, 0, 0, 230))
        draw.text((50, y), line, font=title_font, fill=(255, 255, 255, 255))

    # Branding strip — small, top-left.
    draw.text((50, 36), "TRADEFARM · DAILY", font=branding_font, fill=(212, 160, 46, 220))

    if badge_text:
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        bw = bbox[2] - bbox[0] + 40
        bh = bbox[3] - bbox[1] + 24
        bx0 = width - bw - 50
        by0 = 36
        # Pill background.
        draw.rounded_rectangle(
            (bx0, by0, bx0 + bw, by0 + bh),
            radius=12,
            fill=(20, 40, 28, 220),
            outline=(52, 211, 153, 255),
            width=3,
        )
        draw.text(
            (bx0 + 20, by0 + 8),
            badge_text,
            font=badge_font,
            fill=(167, 243, 208, 255),
        )

    final = composed.convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path, format="JPEG", quality=quality, optimize=True)


def _load_font(size: int):
    """Pillow ImageFont — try a few well-known sans-serif paths, fall
    back to PIL's default if none are present."""
    from PIL import ImageFont

    candidates = (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for c in candidates:
        if Path(c).is_file():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ----- top-level ---------------------------------------------------------


def plan_thumb(
    *,
    session_id: str,
    sessions_dir: Path,
    out_path: Path | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> ThumbPlan | None:
    sdir = sessions_dir / session_id
    beats = _load_beats(sdir / "beats.json")
    pick = pick_source_beat(beats, sdir / "clips")
    if pick is None:
        return None
    beat, clip = pick
    script = _load_json(sdir / "script.json")
    manifest = _load_json(sdir / "manifest.json")
    title = derive_title(beats, script, manifest, session_id)
    badge = derive_badge(beats)
    grab_at = max(0.1, (beat.get("duration_sec") or 12) / 2.0)
    return ThumbPlan(
        session_id=session_id,
        source_clip=clip,
        grab_at_sec=grab_at,
        title=title,
        badge_text=badge,
        out_path=out_path or (sdir / "thumb.jpg"),
        width=width,
        height=height,
    )


def make_thumbnail(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    quality: int = DEFAULT_QUALITY,
    dry_run: bool = False,
) -> ThumbResult:
    started = time.perf_counter()
    base = sessions_dir or Path("out/sessions")
    plan = plan_thumb(
        session_id=session_id,
        sessions_dir=base,
        width=width,
        height=height,
    )
    if plan is None:
        return ThumbResult(
            ok=False,
            error=f"no rendered clips found for session {session_id!r}",
        )
    if dry_run:
        return ThumbResult(ok=True, plan=plan, out_path=plan.out_path)
    sdir = base / session_id
    tmp_png = sdir / ".thumb_frame.png"
    try:
        _grab_frame(plan.source_clip, plan.grab_at_sec, tmp_png)
        _compose_thumb(
            frame_png=tmp_png,
            out_path=plan.out_path,
            title=plan.title,
            badge_text=plan.badge_text,
            width=plan.width,
            height=plan.height,
            quality=quality,
        )
    except Exception as exc:  # noqa: BLE001
        plan.out_path.unlink(missing_ok=True)
        return ThumbResult(
            ok=False,
            plan=plan,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        tmp_png.unlink(missing_ok=True)
    return ThumbResult(
        ok=True,
        plan=plan,
        out_path=plan.out_path,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


# ----- CLI ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tradefarm.thumb.gen",
        description="Generate a 1280×720 thumbnail JPEG from the best beat clip.",
    )
    parser.add_argument("session_id")
    parser.add_argument("--out", type=Path, default=Path("out/sessions"))
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--quality", type=int, default=DEFAULT_QUALITY, help="JPEG quality 1-100 (default 88)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan without invoking ffmpeg / Pillow."
    )
    args = parser.parse_args(argv)

    result = make_thumbnail(
        args.session_id,
        sessions_dir=args.out,
        width=args.width,
        height=args.height,
        quality=args.quality,
        dry_run=args.dry_run,
    )
    if args.dry_run and result.plan is not None:
        p = result.plan
        print(f"session_id={args.session_id}")
        print(f"source_clip={p.source_clip}")
        print(f"grab_at={p.grab_at_sec:.2f}s")
        print(f"title={p.title}")
        print(f"badge={p.badge_text}")
        print(f"out={p.out_path}")
        return
    if not result.ok:
        print(f"FAIL: {result.error}", file=__import__("sys").stderr)
        raise SystemExit(1)
    print(
        f"session_id={args.session_id}\n"
        f"thumb={result.out_path}\n"
        f"elapsed={int(result.elapsed_ms or 0)}ms"
    )


if __name__ == "__main__":
    main()
