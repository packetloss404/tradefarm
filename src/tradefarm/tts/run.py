"""TTS runner — turns script.json into per-line .wav files.

Input:  out/sessions/<id>/script.json   (from script.write)
Output: out/sessions/<id>/vo/<beat_id>_<line_idx>.wav
        out/sessions/<id>/vo/index.json (durations + filenames)

Three providers, picked by `--provider` (default: env-detect):

  elevenlabs  — POST to api.elevenlabs.io/v1/text-to-speech, mp3→wav
                via ffmpeg, ELEVENLABS_API_KEY required
  openai      — OpenAI's audio.speech.create, OPENAI_API_KEY required
  silence     — synthesises a silent .wav of the estimated duration.
                Useful for offline testing, dry runs, and any
                ffmpeg-only end-to-end smoke that doesn't care about
                actual voice quality.

The fancy providers (piper.exe local, alternative voices) are
deliberately deferred — the v0 contract is "an output .wav per line"
and `silence` covers tests + downstream pipeline development without
burning API credits. Real-voice runs use elevenlabs / openai when
keys are present.

Idempotent: re-running over an existing vo/ directory skips files
that already exist unless --force is set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tradefarm.runtime.http import get_shared_client, with_retries  # noqa: F401  (re-exported for tests)


DEFAULT_PROVIDER = "auto"  # "auto" → first available based on env keys
DEFAULT_VOICE = "Daniel"
DEFAULT_MODEL = ""  # provider-specific default
DEFAULT_SAMPLE_RATE = 22_050
DEFAULT_FORMAT = "wav"


# ----- provider protocol --------------------------------------------------


class TtsProvider(Protocol):
    name: str
    sample_rate: int

    async def synthesize(self, text: str, *, voice: str, out_path: Path) -> float:
        """Render `text` to `out_path` (.wav). Returns actual duration."""
        ...


# ----- silent provider (always available) ---------------------------------


class SilentTtsProvider:
    """Writes a silent wav whose duration matches the script's pacing
    estimate. Pure-Python (`wave` stdlib), no system deps. Used for
    dry runs, tests, and pipeline development without API credits."""

    name = "silence"
    sample_rate = DEFAULT_SAMPLE_RATE
    WPM = 155

    async def synthesize(self, text: str, *, voice: str, out_path: Path) -> float:
        words = max(1, len(text.split()))
        duration = round(60.0 * words / self.WPM + 0.25, 2)  # tiny tail
        n_frames = int(duration * self.sample_rate)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)  # 16-bit
            w.setframerate(self.sample_rate)
            w.writeframes(b"\x00\x00" * n_frames)
        return duration


# ----- elevenlabs provider (httpx; lazy import) ---------------------------


class ElevenLabsTtsProvider:
    """Cloud TTS via api.elevenlabs.io. Requires the system `ffmpeg`
    binary to convert the returned mp3 to wav at our sample rate.

    `voice` is treated as an ElevenLabs voice id (e.g. the default
    "21m00Tcm4TlvDq8ikWAM" for Rachel) OR a friendly name from a small
    built-in map. Custom voices go through their id; pass --voice
    explicitly.
    """

    name = "elevenlabs"
    sample_rate = DEFAULT_SAMPLE_RATE

    # A tiny default map for the well-known stock voices; otherwise
    # caller passes the id directly.
    VOICE_IDS = {
        "Daniel": "onwK4e9ZLuTAKqWW03F9",
        "Rachel": "21m00Tcm4TlvDq8ikWAM",
        "Adam": "pNInz6obpgDQGcFmaJgB",
    }

    DEFAULT_MODEL_ID = "eleven_flash_v2_5"

    def __init__(self, *, api_key: str, model_id: str | None = None):
        self.api_key = api_key
        self.model_id = model_id or self.DEFAULT_MODEL_ID

    async def synthesize(self, text: str, *, voice: str, out_path: Path) -> float:
        import subprocess

        voice_id = self.VOICE_IDS.get(voice, voice)
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        # 0.12.0 — Round-5 AA follow-up. Reuse the shared httpx client +
        # retry helper so the elevenlabs POST benefits from keepalive +
        # transient-error retries the same way ``MinimaxProvider.decide``
        # + ``commentary_loop._commentary_completion`` already do. Without
        # this, every line of every episode paid a fresh TLS handshake.
        client = await get_shared_client()

        async def _post_once() -> bytes:
            r = await client.post(
                url,
                headers={
                    "xi-api-key": self.api_key,
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": self.model_id,
                    "voice_settings": {"stability": 0.55, "similarity_boost": 0.75},
                },
                timeout=30.0,
            )
            if r.status_code != 200:
                # Raise a non-retryable error on 4xx (other than 429 which
                # the retry helper handles); the helper re-raises 5xx.
                # Anything that ultimately bubbles to the caller means the
                # synthesis for this line is dead — we record the failure
                # in the result and move on.
                if r.status_code < 500 and r.status_code != 429:
                    raise RuntimeError(
                        f"elevenlabs returned {r.status_code}: {r.text[:200]}"
                    )
                r.raise_for_status()
            return r.content

        content = await with_retries(_post_once, label="elevenlabs")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = out_path.with_suffix(".mp3")
        mp3_path.write_bytes(content)
        # Transcode to mono 22050 Hz wav via ffmpeg. The mixer downstream
        # is happier with a uniform sample-rate input.
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(mp3_path),
                "-ac",
                "1",
                "-ar",
                str(self.sample_rate),
                str(out_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        mp3_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:400]}")
        return _wav_duration_sec(out_path)


# ----- openai provider ----------------------------------------------------


class OpenAiTtsProvider:
    """Cloud TTS via OpenAI's audio.speech.create. The SDK is lazy
    imported so the project doesn't gain a hard openai dep — anyone
    using this provider already wants the SDK installed."""

    name = "openai"
    sample_rate = DEFAULT_SAMPLE_RATE
    DEFAULT_MODEL_ID = "tts-1"

    # Friendly name → OpenAI voice. Their named voices are limited.
    VOICE_MAP = {
        "Daniel": "onyx",
        "Rachel": "nova",
        "Adam": "alloy",
    }

    def __init__(self, *, api_key: str, model_id: str | None = None):
        self.api_key = api_key
        self.model_id = model_id or self.DEFAULT_MODEL_ID

    async def synthesize(self, text: str, *, voice: str, out_path: Path) -> float:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed — `uv add openai` to use this provider"
            ) from exc
        client = AsyncOpenAI(api_key=self.api_key)
        mapped = self.VOICE_MAP.get(voice, voice)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Audit fix (H15): use the documented stable streaming API
        # instead of `resp.content` / `resp.read()`, which return a
        # coroutine in some SDK versions (would have silently written
        # `b"<coroutine object …>"` to the wav). stream_to_file
        # handles the binary correctly across SDK versions.
        async with client.audio.speech.with_streaming_response.create(
            model=self.model_id,
            voice=mapped,
            input=text,
            response_format="wav",
        ) as response:
            await response.stream_to_file(out_path)
        return _wav_duration_sec(out_path)


# ----- helpers ------------------------------------------------------------


def _wav_duration_sec(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or DEFAULT_SAMPLE_RATE
        return round(frames / rate, 3)
    except (wave.Error, OSError):
        return 0.0


def build_provider(
    name: str, *, api_key: str | None = None, voice_model: str | None = None
) -> TtsProvider:
    """Pick a provider by name. `auto` selects elevenlabs → openai →
    silence based on which env keys are present."""
    if name == "auto":
        if os.environ.get("ELEVENLABS_API_KEY"):
            name = "elevenlabs"
        elif os.environ.get("OPENAI_API_KEY"):
            name = "openai"
        else:
            name = "silence"
    if name == "silence":
        return SilentTtsProvider()
    if name == "elevenlabs":
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set (or pass --api-key)")
        return ElevenLabsTtsProvider(api_key=key, model_id=voice_model or None)
    if name == "openai":
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set (or pass --api-key)")
        return OpenAiTtsProvider(api_key=key, model_id=voice_model or None)
    raise RuntimeError(f"unknown provider {name!r}")


# Provider → env key that gates the auto-detect path. Used by
# :func:`available_providers` and the chain's auto-include logic.
_PROVIDER_KEYS: dict[str, str] = {
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def available_providers() -> list[str]:
    """List the providers with at least one env key present.

    The order matches :func:`build_provider`'s ``auto`` selection
    (elevenlabs → openai → silence-as-fallback) so callers that
    want a single ``auto`` decision can read ``available_providers()[0]``
    when the list is non-empty. The ``silence`` provider is always
    available and is NOT in this list (it has no key to check).
    """
    return [
        name
        for name, key in _PROVIDER_KEYS.items()
        if os.environ.get(key)
    ]


def has_tts_creds() -> bool:
    """True if any TTS provider has a key in the env.

    Used by the chain's default enabled set: when the operator has
    TTS creds configured, the ``tts`` step is auto-included in the
    chain so they don't have to remember ``--include-tts`` (or the
    HTTP wrapper's ``include_tts`` request body) on every run.
    """
    return bool(available_providers())


def should_auto_include_tts(*, vod_tts_auto_include: bool = True) -> bool:
    """Combine the operator's `vod_tts_auto_include` config with the
    presence of provider keys.

    Returns True when both conditions hold:
    1. The operator has ``vod_tts_auto_include`` enabled (the default
       is True — operators who want a hard "no tts" default can
       disable it in the env).
    2. At least one TTS provider key is present in the env.

    The HTTP wrapper's per-request ``include_tts`` body field is
    the second-class override: when the request body says
    ``include_tts=False``, the chain respects that regardless of
    the auto-include decision.
    """
    return bool(vod_tts_auto_include) and has_tts_creds()


# ----- record types -------------------------------------------------------


@dataclass(frozen=True)
class TtsLine:
    beat_id: str
    line_idx: int
    text: str
    wav: Path
    duration_sec: float
    provider: str
    voice: str


@dataclass
class TtsResult:
    session_id: str
    vo_dir: Path
    provider: str
    voice: str
    lines: list[TtsLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # already-existed reasons
    failed: list[tuple[str, str]] = field(default_factory=list)  # (id, error)


def _slug(s: str) -> str:
    """Sanitise an id for use as a filename."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


# ----- top-level runner ---------------------------------------------------


def _load_script(script_path: Path) -> list[dict[str, Any]]:
    if not script_path.is_file():
        raise FileNotFoundError(f"script.json not found: {script_path}")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    beats = data.get("beats")
    if not isinstance(beats, list):
        raise ValueError(f"script.json has no `beats` array: {script_path}")
    return beats


def _index_path(vo_dir: Path) -> Path:
    return vo_dir / "index.json"


def _existing_index(vo_dir: Path) -> dict[str, dict[str, Any]]:
    """Map of `<beat_id>_<line_idx>` → existing index row, if any."""
    p = _index_path(vo_dir)
    if not p.is_file():
        return {}
    try:
        rows = json.loads(p.read_text(encoding="utf-8")).get("lines") or []
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = f"{r.get('beat_id')}_{r.get('line_idx')}"
        out[key] = r
    return out


async def run_tts(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    provider_name: str = DEFAULT_PROVIDER,
    voice: str = DEFAULT_VOICE,
    api_key: str | None = None,
    voice_model: str | None = None,
    force: bool = False,
) -> TtsResult:
    """Read script.json, synth each line, write per-line .wav + a
    summary index.json. Re-uses existing wavs when force=False."""

    base = sessions_dir or Path("out/sessions")
    sdir = base / session_id
    script_path = sdir / "script.json"
    vo_dir = sdir / "vo"
    vo_dir.mkdir(parents=True, exist_ok=True)

    beats = _load_script(script_path)
    provider = build_provider(provider_name, api_key=api_key, voice_model=voice_model)
    existing = _existing_index(vo_dir) if not force else {}

    result = TtsResult(
        session_id=session_id,
        vo_dir=vo_dir,
        provider=provider.name,
        voice=voice,
    )

    for beat in beats:
        beat_id = str(beat.get("beat_id") or "")
        if not beat_id:
            continue
        lines = beat.get("lines") or []
        for idx, ln in enumerate(lines):
            if not isinstance(ln, dict):
                continue
            text = (ln.get("text") or "").strip()
            if not text:
                continue
            stem = f"{_slug(beat_id)}_{idx:02d}"
            wav_path = vo_dir / f"{stem}.wav"
            key = f"{beat_id}_{idx}"

            if not force and key in existing and wav_path.is_file():
                row = existing[key]
                result.lines.append(
                    TtsLine(
                        beat_id=beat_id,
                        line_idx=idx,
                        text=text,
                        wav=wav_path,
                        duration_sec=float(row.get("duration_sec", 0.0)),
                        provider=row.get("provider", provider.name),
                        voice=row.get("voice", voice),
                    )
                )
                result.skipped.append(stem)
                continue

            try:
                dur = await provider.synthesize(text, voice=voice, out_path=wav_path)
            except Exception as exc:  # noqa: BLE001
                result.failed.append((stem, f"{type(exc).__name__}: {exc}"))
                continue
            result.lines.append(
                TtsLine(
                    beat_id=beat_id,
                    line_idx=idx,
                    text=text,
                    wav=wav_path,
                    duration_sec=dur,
                    provider=provider.name,
                    voice=voice,
                )
            )

    # Write the index. Sorted by (beat order, line idx) — matches the
    # order the mixer will splice them in.
    index = {
        "session_id": session_id,
        "provider": provider.name,
        "voice": voice,
        "sample_rate": getattr(provider, "sample_rate", DEFAULT_SAMPLE_RATE),
        "lines": [
            {
                "beat_id": ln.beat_id,
                "line_idx": ln.line_idx,
                "text": ln.text,
                "wav": ln.wav.name,
                "duration_sec": ln.duration_sec,
                "provider": ln.provider,
                "voice": ln.voice,
            }
            for ln in result.lines
        ],
    }
    _index_path(vo_dir).write_text(json.dumps(index, indent=2), encoding="utf-8")
    return result


# ----- CLI ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tradefarm.tts.run",
        description="Synthesise per-line .wav files from script.json.",
    )
    parser.add_argument("session_id")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=["auto", "elevenlabs", "openai", "silence"],
        help="TTS backend. 'auto' picks first-available based on env keys, falling back to 'silence'.",
    )
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--api-key", default=None, help="Override env-derived key.")
    parser.add_argument("--voice-model", default=None, help="Provider-specific model id.")
    parser.add_argument(
        "--force", action="store_true", help="Re-synth even when wav already exists."
    )
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(
            run_tts(
                args.session_id,
                sessions_dir=args.out,
                provider_name=args.provider,
                voice=args.voice,
                api_key=args.api_key,
                voice_model=args.voice_model,
                force=args.force,
            )
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"missing input: {exc}") from exc
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"tts failed: {exc}") from exc

    total = sum(ln.duration_sec for ln in result.lines)
    print(
        f"session_id={result.session_id}\n"
        f"vo_dir={result.vo_dir}\n"
        f"provider={result.provider} voice={result.voice}\n"
        f"lines={len(result.lines)} reused={len(result.skipped)} failed={len(result.failed)}\n"
        f"total_speech_sec={total:.1f}"
    )
    for stem, err in result.failed[:5]:
        print(f"  FAIL {stem}: {err}", file=__import__("sys").stderr)
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
