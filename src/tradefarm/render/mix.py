"""Audio mixer — combines silent_reel.mp4 + per-line VO wavs + an
optional music bed into the final narrated reel.mp4.

Input:  out/sessions/<id>/silent_reel.mp4   (from render.stitch)
        out/sessions/<id>/vo/index.json     (from tts.run)
        out/sessions/<id>/vo/*.wav
        (optional) --music <path>           music bed mp3 / wav / ogg
        out/sessions/<id>/clips/<beat_id>.json   (sidecars from render.headless,
                                                  used to time VO onto the reel)
Output: out/sessions/<id>/reel.mp4

Audio graph (one ffmpeg invocation, one re-encode of the audio
stream; video is stream-copied with -c:v copy):

  silent_reel video  →  (no audio in)
  vo[0..N]           →  per-line `adelay` to the line's onset, then
                        `amix` with `dropout_transition=0`. Each line
                        starts at `clip.scene_ready_at_ms_offset +
                        sum(prior_line.duration_sec) + 0.5s lead-in`.
  music              →  loop to reel duration, `volume=0.18`, sidechain
                        ducked under VO (compander, threshold low, ratio
                        high). Music dropped if --no-music or no file.

The per-clip onset is computed from each clip's sidecar JSON written
by the headless renderer: each beat occupies a known window of the
reel that the stitcher built. The mixer assumes the stitcher kept
beats in order and crossfade-trimmed by `xfade_sec` between clips
(see render.stitch.build_xfade_command's offset math) — same
constants live here so the alignment stays coherent.

System ffmpeg required (probed before any work).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradefarm.render.stitch import DEFAULT_XFADE_SEC, ffmpeg_info, ffprobe_duration, load_reel_meta


VO_LEAD_IN_SEC = 0.5  # delay from a beat's start before VO begins
DEFAULT_MUSIC_VOLUME = 0.18
DEFAULT_DUCK_THRESHOLD = 0.05  # 0..1 linear; below this music plays full
# Music gain reduction (dB) when VO is loud. compander outputs the
# sidechain envelope so we cap it as a fixed gain ramp.
DUCK_REDUCTION_DB = 12.0


@dataclass(frozen=True)
class VoLine:
    beat_id: str
    line_idx: int
    wav: Path
    duration_sec: float
    onset_sec: float  # absolute offset into the reel


@dataclass
class MixPlan:
    session_id: str
    silent_reel: Path
    vo_lines: list[VoLine]
    music_path: Path | None
    out_path: Path
    music_volume: float = DEFAULT_MUSIC_VOLUME
    duck_reduction_db: float = DUCK_REDUCTION_DB
    reel_duration_sec: float = 0.0  # filled from ffprobe


@dataclass
class MixResult:
    ok: bool
    out_path: Path | None = None
    plan: MixPlan | None = None
    elapsed_ms: float | None = None
    error: str | None = None


# ----- helpers ------------------------------------------------------------


# Canonical ffprobe helper lives in render.stitch; kept here as a local
# alias so tests that monkeypatch `mix._ffprobe_duration` (they exist)
# continue to work.
_ffprobe_duration = ffprobe_duration


def _load_sidecars(clips_dir: Path) -> dict[str, dict[str, Any]]:
    """beat_id → sidecar JSON dict from the headless renderer."""
    out: dict[str, dict[str, Any]] = {}
    if not clips_dir.is_dir():
        return out
    for p in sorted(clips_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        bid = data.get("beat_id")
        if bid:
            out[bid] = data
    return out


def _load_beats_order(beats_path: Path) -> list[str]:
    """Beat ids in their on-screen order (matches the stitcher's
    chronological sort)."""
    if not beats_path.is_file():
        return []
    rows = json.loads(beats_path.read_text(encoding="utf-8"))
    return [str(r["id"]) for r in rows if "id" in r]


def _line_clip_duration_sec(sidecar: dict[str, Any]) -> float:
    """How long this beat's *trimmed* clip occupies in the reel (the
    same number the stitcher used to compute xfade offsets)."""
    return float(sidecar.get("duration_ms", 0)) / 1000.0


# ----- plan builder -------------------------------------------------------


def plan_mix(
    *,
    session_id: str,
    sessions_dir: Path,
    music_path: Path | None,
    out_path: Path | None = None,
    xfade_sec: float = DEFAULT_XFADE_SEC,
    vo_lead_in_sec: float = VO_LEAD_IN_SEC,
    music_volume: float = DEFAULT_MUSIC_VOLUME,
    duck_reduction_db: float = DUCK_REDUCTION_DB,
) -> MixPlan:
    """Build the mix plan: per-line onsets relative to the silent reel.

    Onsets are computed from the same xfade arithmetic the stitcher
    used: for clip i (0-indexed), its on-screen start in the reel is
        sum(duration_j for j<i) - xfade_sec * i
    VO line k of clip i then starts at
        clip_start_i + vo_lead_in_sec + sum(line_j.duration_sec for j<k)
    """

    sdir = sessions_dir / session_id
    silent_reel = sdir / "silent_reel.mp4"
    vo_index_path = sdir / "vo" / "index.json"
    clips_dir = sdir / "clips"
    beats_path = sdir / "beats.json"
    final = out_path or (sdir / "reel.mp4")

    sidecars = _load_sidecars(clips_dir)
    beat_order = _load_beats_order(beats_path)
    vo_index_data = (
        json.loads(vo_index_path.read_text(encoding="utf-8")) if vo_index_path.is_file() else {}
    )
    vo_rows: list[dict[str, Any]] = vo_index_data.get("lines") or []

    # Index VO rows by beat_id → list of (line_idx, wav, duration).
    vo_by_beat: dict[str, list[tuple[int, Path, float]]] = {}
    for r in vo_rows:
        bid = str(r.get("beat_id") or "")
        idx = int(r.get("line_idx") or 0)
        wav_name = r.get("wav") or ""
        wav_path = (sdir / "vo" / wav_name) if wav_name else None
        if not bid or not wav_path or not wav_path.is_file():
            continue
        vo_by_beat.setdefault(bid, []).append((idx, wav_path, float(r.get("duration_sec", 0.0))))
    for v in vo_by_beat.values():
        v.sort(key=lambda t: t[0])

    # Filter to beats that actually got rendered first — the stitcher
    # only chained xfades between *existing* clips, so the mixer must
    # use the same "rendered beats" list as the source of truth. Walking
    # all of beat_order and `continue`-ing on missing sidecars used to
    # subtract a phantom xfade after the second-to-last clip whenever a
    # recap beat (default-skipped by the renderer) sat at the end of
    # the day, drifting every VO onset by `xfade_sec`.
    rendered = [bid for bid in beat_order if bid in sidecars]

    vo_lines: list[VoLine] = []
    clip_start = 0.0
    for i, beat_id in enumerate(rendered):
        sidecar = sidecars[beat_id]
        clip_dur = _line_clip_duration_sec(sidecar)
        # Lay out VO onsets within this clip.
        local_cursor = vo_lead_in_sec
        for line_idx, wav_path, dur in vo_by_beat.get(beat_id, []):
            onset = clip_start + local_cursor
            vo_lines.append(
                VoLine(
                    beat_id=beat_id,
                    line_idx=line_idx,
                    wav=wav_path,
                    duration_sec=dur,
                    onset_sec=round(onset, 3),
                )
            )
            local_cursor += dur + 0.1  # small breath between lines
        # Advance to the next clip. Last clip has no trailing xfade.
        clip_start += clip_dur - (xfade_sec if i < len(rendered) - 1 else 0.0)

    return MixPlan(
        session_id=session_id,
        silent_reel=silent_reel,
        vo_lines=vo_lines,
        music_path=music_path,
        out_path=final,
        music_volume=music_volume,
        duck_reduction_db=duck_reduction_db,
        reel_duration_sec=_ffprobe_duration(silent_reel),
    )


# ----- command builder ----------------------------------------------------


def build_mix_command(plan: MixPlan) -> list[str]:
    """Construct one ffmpeg call that:
    - copies the video stream from silent_reel.mp4
    - mixes N delayed VO wavs into one audio stream
    - optionally adds a looped, ducked music bed
    """

    if plan.reel_duration_sec <= 0:
        raise ValueError(f"reel duration unknown for {plan.silent_reel}")

    inputs: list[str] = ["-i", str(plan.silent_reel)]
    vo_in_indices: list[int] = []
    for ln in plan.vo_lines:
        inputs.extend(["-i", str(ln.wav)])
        vo_in_indices.append(len(vo_in_indices) + 1)  # silent reel is input 0

    music_in_idx: int | None = None
    if plan.music_path is not None:
        inputs.extend(["-stream_loop", "-1", "-i", str(plan.music_path)])
        music_in_idx = len(vo_in_indices) + 1

    # Build filter_complex
    filter_parts: list[str] = []

    # 1. Delay every VO line to its onset, then mix.
    vo_mix_label = "vo"
    if vo_in_indices:
        for ln_idx, in_idx in enumerate(vo_in_indices):
            delay_ms = int(plan.vo_lines[ln_idx].onset_sec * 1000)
            # asetpts → start at 0 then adelay shifts forward. apad
            # pushes the wav out to the reel length so amix doesn't
            # short-circuit on shorter inputs.
            filter_parts.append(
                f"[{in_idx}:a]adelay={delay_ms}|{delay_ms},"
                f"apad=whole_dur={plan.reel_duration_sec:.3f}"
                f"[vo{ln_idx}]"
            )
        vo_streams = "".join(f"[vo{i}]" for i in range(len(vo_in_indices)))
        filter_parts.append(
            f"{vo_streams}amix=inputs={len(vo_in_indices)}:"
            f"duration=longest:dropout_transition=0"
            f"[{vo_mix_label}]"
        )

    # 2. Music bed (looped, volume-scaled, optionally ducked under VO).
    if music_in_idx is not None:
        # Loop is already on the input side via -stream_loop. Cap to
        # reel duration with `atrim`. Scale + light fade in/out.
        filter_parts.append(
            f"[{music_in_idx}:a]"
            f"atrim=duration={plan.reel_duration_sec:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={plan.music_volume:.3f},"
            f"afade=t=in:st=0:d=1,"
            f"afade=t=out:st={max(0.0, plan.reel_duration_sec - 2):.3f}:d=2"
            f"[mus]"
        )
        if vo_in_indices:
            # Sidechain duck. sidechaincompress reads [vo] as the
            # sidechain key; output drops [mus] gain when VO is active.
            duck_ratio = max(2.0, 10 ** (plan.duck_reduction_db / 20))
            filter_parts.append(
                f"[mus][{vo_mix_label}]"
                f"sidechaincompress=threshold=0.05:ratio={duck_ratio:.2f}:"
                f"attack=80:release=400:level_sc=1"
                f"[mus_ducked]"
            )
            filter_parts.append(
                f"[mus_ducked][{vo_mix_label}]"
                f"amix=inputs=2:duration=longest:dropout_transition=0"
                f"[aout]"
            )
        else:
            filter_parts.append("[mus]anull[aout]")
    elif vo_in_indices:
        filter_parts.append(f"[{vo_mix_label}]anull[aout]")
    else:
        # No VO, no music → no audio track. Just stream-copy the video.
        return [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(plan.silent_reel),
            "-c:v",
            "copy",
            "-an",
            "-movflags",
            "+faststart",
            str(plan.out_path),
        ]

    filter_complex = ";".join(filter_parts)
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-c:v",
        "copy",
        "-map",
        "[aout]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(plan.out_path),
    ]


# ----- runner -------------------------------------------------------------


def mix_session(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    music_path: Path | None = None,
    music_volume: float = DEFAULT_MUSIC_VOLUME,
    duck_reduction_db: float = DUCK_REDUCTION_DB,
    xfade_sec: float | None = None,
    vo_lead_in_sec: float = VO_LEAD_IN_SEC,
    dry_run: bool = False,
) -> MixResult:
    started = time.perf_counter()
    base = sessions_dir or Path("out/sessions")
    sdir = base / session_id
    out_path = sdir / "reel.mp4"

    if not (sdir / "silent_reel.mp4").is_file():
        return MixResult(ok=False, error=f"silent_reel.mp4 not found in {sdir}")

    # Prefer the xfade the stitcher actually used (persisted to
    # reel.meta.json). Falls back to the operator's CLI flag, then the
    # DEFAULT — so an operator who passes --xfade to the stitcher but
    # forgets to pass it to the mixer can't silently drift the VO.
    reel_meta = load_reel_meta(sdir)
    if xfade_sec is None:
        xfade_sec = float(reel_meta.get("xfade_sec", DEFAULT_XFADE_SEC))

    plan = plan_mix(
        session_id=session_id,
        sessions_dir=base,
        music_path=music_path,
        out_path=out_path,
        xfade_sec=xfade_sec,
        vo_lead_in_sec=vo_lead_in_sec,
        music_volume=music_volume,
        duck_reduction_db=duck_reduction_db,
    )
    if plan.reel_duration_sec <= 0:
        return MixResult(ok=False, plan=plan, error="ffprobe could not read reel duration")

    if dry_run:
        return MixResult(ok=True, plan=plan, out_path=out_path)

    ok_ff, info = ffmpeg_info()
    if not ok_ff:
        return MixResult(ok=False, plan=plan, error=f"ffmpeg not available: {info}")

    cmd = build_mix_command(plan)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:
        return MixResult(
            ok=False, plan=plan, error=str(e), elapsed_ms=(time.perf_counter() - started) * 1000
        )
    if r.returncode != 0:
        out_path.unlink(missing_ok=True)
        return MixResult(
            ok=False,
            plan=plan,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=(r.stderr or r.stdout or "").strip()[-600:],
        )
    return MixResult(
        ok=True,
        plan=plan,
        out_path=out_path,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


# ----- CLI ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tradefarm.render.mix",
        description="Mix silent_reel + VO + optional music → reel.mp4.",
    )
    parser.add_argument("session_id")
    parser.add_argument("--out", type=Path, default=Path("out/sessions"))
    parser.add_argument("--music", type=Path, default=None, help="Music bed audio file (optional).")
    parser.add_argument("--music-volume", type=float, default=DEFAULT_MUSIC_VOLUME)
    parser.add_argument(
        "--duck-db",
        type=float,
        default=DUCK_REDUCTION_DB,
        help="Music gain reduction (dB) when VO is loud.",
    )
    parser.add_argument(
        "--vo-lead-in",
        type=float,
        default=VO_LEAD_IN_SEC,
        help="Seconds of clip head-time before VO starts.",
    )
    parser.add_argument(
        "--xfade",
        type=float,
        default=DEFAULT_XFADE_SEC,
        help="Stitcher's crossfade seconds (must match for alignment).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan + ffmpeg command without running it."
    )
    args = parser.parse_args(argv)

    result = mix_session(
        args.session_id,
        sessions_dir=args.out,
        music_path=args.music,
        music_volume=args.music_volume,
        duck_reduction_db=args.duck_db,
        vo_lead_in_sec=args.vo_lead_in,
        xfade_sec=args.xfade,
        dry_run=args.dry_run,
    )

    if args.dry_run and result.plan is not None:
        print(f"session_id={args.session_id}")
        print(f"silent_reel={result.plan.silent_reel}")
        print(f"reel_duration={result.plan.reel_duration_sec:.2f}s")
        print(f"vo_lines={len(result.plan.vo_lines)}")
        for ln in result.plan.vo_lines:
            print(
                f"  {ln.beat_id}.{ln.line_idx:02d} onset={ln.onset_sec:.2f}s dur={ln.duration_sec:.2f}s"
            )
        if result.plan.music_path:
            print(f"music={result.plan.music_path} vol={result.plan.music_volume}")
        print("\n# ffmpeg command:")
        print("  " + " ".join(build_mix_command(result.plan)))
        return

    if not result.ok:
        print(f"FAIL: {result.error}", file=__import__("sys").stderr)
        raise SystemExit(1)
    print(
        f"session_id={args.session_id}\n"
        f"out={result.out_path}\n"
        f"elapsed={int(result.elapsed_ms or 0)}ms"
    )


if __name__ == "__main__":
    main()
