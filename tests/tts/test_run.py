"""TTS runner — pure-function tests + silence-provider integration.

Real-cloud-provider tests (elevenlabs / openai) are env-gated and
skip-by-default. The silence provider is the workhorse for offline
end-to-end checks of the pipeline shape.
"""

from __future__ import annotations

import json
import os
import wave
from pathlib import Path

import pytest

from tradefarm.tts.run import (
    DEFAULT_SAMPLE_RATE,
    SilentTtsProvider,
    _slug,
    _wav_duration_sec,
    available_providers,
    build_provider,
    has_tts_creds,
    run_tts,
    should_auto_include_tts,
)


# ----- helpers / silence provider ----------------------------------------


def test_slug_strips_unsafe_chars():
    assert _slug("b_open") == "b_open"
    assert _slug("b/with bad-chars:1") == "b_with_bad-chars_1"


def test_wav_duration_sec_returns_zero_on_missing(tmp_path: Path):
    assert _wav_duration_sec(tmp_path / "missing.wav") == 0.0


async def test_silent_provider_writes_valid_wav(tmp_path: Path):
    p = SilentTtsProvider()
    out = tmp_path / "x.wav"
    duration = await p.synthesize("two words here", voice="ignored", out_path=out)
    assert out.is_file()
    # Verify it's a real wav we can re-open and that the duration
    # matches our reported value.
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == DEFAULT_SAMPLE_RATE
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        actual_dur = w.getnframes() / w.getframerate()
    assert duration == pytest.approx(actual_dur, abs=0.01)
    # And our scaler: 3 words at 155 wpm + 0.25s tail.
    assert duration == pytest.approx(60.0 * 3 / 155 + 0.25, abs=0.01)


# ----- provider factory --------------------------------------------------


def test_build_provider_silence_always_available(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = build_provider("silence")
    assert p.name == "silence"


def test_build_provider_auto_picks_silence_when_no_keys(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert build_provider("auto").name == "silence"


def test_build_provider_auto_prefers_elevenlabs(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    assert build_provider("auto").name == "elevenlabs"


def test_build_provider_auto_falls_back_to_openai(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    assert build_provider("auto").name == "openai"


def test_build_provider_elevenlabs_requires_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        build_provider("elevenlabs")


def test_build_provider_openai_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_provider("openai")


def test_build_provider_unknown_raises():
    with pytest.raises(RuntimeError, match="unknown provider"):
        build_provider("hal9000")


# ----- end-to-end with silence provider ----------------------------------


def _write_script(base: Path, session_id: str, *, beats: list[dict]) -> Path:
    sdir = base / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "script.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "episode_title": "Test",
                "model": "silence",
                "usage": {},
                "total_words": 0,
                "total_duration_sec": 0,
                "beats": beats,
            }
        ),
        encoding="utf-8",
    )
    return sdir


async def test_run_tts_produces_wav_per_line(tmp_path: Path):
    _write_script(
        tmp_path,
        "s_tts",
        beats=[
            {
                "beat_id": "b_open",
                "lines": [
                    {"text": "Bell rings, agents settle in.", "words": 5, "duration_sec": 1.9},
                    {"text": "Tape is quiet this morning.", "words": 5, "duration_sec": 1.9},
                ],
            },
            {
                "beat_id": "b_close",
                "lines": [
                    {"text": "And then the close arrived.", "words": 5, "duration_sec": 1.9},
                ],
            },
        ],
    )
    result = await run_tts("s_tts", sessions_dir=tmp_path, provider_name="silence")
    assert result.provider == "silence"
    assert len(result.lines) == 3
    for line in result.lines:
        assert line.wav.is_file()
        assert line.duration_sec > 0
    # Index file lists every line in order.
    index = json.loads((result.vo_dir / "index.json").read_text())
    keys = [(r["beat_id"], r["line_idx"]) for r in index["lines"]]
    assert keys == [("b_open", 0), ("b_open", 1), ("b_close", 0)]


async def test_run_tts_skips_empty_lines(tmp_path: Path):
    _write_script(
        tmp_path,
        "s_skip",
        beats=[
            {
                "beat_id": "b1",
                "lines": [
                    {"text": "real one"},
                    {"text": "   "},
                    {"text": ""},
                    {"text": "another real one"},
                ],
            },
        ],
    )
    result = await run_tts("s_skip", sessions_dir=tmp_path, provider_name="silence")
    assert len(result.lines) == 2


async def test_run_tts_is_idempotent_when_force_false(tmp_path: Path):
    """A second run with the same script + force=False reuses the
    wav files and reports them in `skipped`."""
    _write_script(
        tmp_path,
        "s_idem",
        beats=[
            {"beat_id": "b1", "lines": [{"text": "one line"}]},
        ],
    )
    first = await run_tts("s_idem", sessions_dir=tmp_path, provider_name="silence")
    assert len(first.lines) == 1 and first.skipped == []
    # Tamper with the wav so we can prove the second run didn't rewrite.
    wav = first.lines[0].wav
    wav.write_bytes(b"sentinel")
    second = await run_tts("s_idem", sessions_dir=tmp_path, provider_name="silence")
    assert wav.read_bytes() == b"sentinel"
    assert len(second.skipped) == 1


async def test_run_tts_force_overwrites(tmp_path: Path):
    _write_script(
        tmp_path,
        "s_force",
        beats=[
            {"beat_id": "b1", "lines": [{"text": "one line"}]},
        ],
    )
    first = await run_tts("s_force", sessions_dir=tmp_path, provider_name="silence")
    wav = first.lines[0].wav
    wav.write_bytes(b"sentinel")
    second = await run_tts("s_force", sessions_dir=tmp_path, provider_name="silence", force=True)
    assert wav.read_bytes() != b"sentinel"
    assert second.skipped == []


async def test_run_tts_records_provider_failure(tmp_path: Path, monkeypatch):
    """A provider that raises should land in `result.failed` without
    killing the rest of the run."""
    from tradefarm.tts import run as runner

    _write_script(
        tmp_path,
        "s_fail",
        beats=[
            {"beat_id": "b_good", "lines": [{"text": "ok"}]},
            {"beat_id": "b_bad", "lines": [{"text": "boom"}]},
        ],
    )

    class FlakyProvider:
        name = "flaky"
        sample_rate = DEFAULT_SAMPLE_RATE

        async def synthesize(self, text, *, voice, out_path):
            if text == "boom":
                raise RuntimeError("simulated provider explosion")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.sample_rate)
                w.writeframes(b"\x00\x00" * 1000)
            return 0.05

    monkeypatch.setattr(runner, "build_provider", lambda *a, **kw: FlakyProvider())
    result = await run_tts("s_fail", sessions_dir=tmp_path, provider_name="ignored")
    assert len(result.lines) == 1
    assert len(result.failed) == 1
    assert "boom" in result.failed[0][1] or "explosion" in result.failed[0][1]


async def test_run_tts_missing_script_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        await run_tts("never", sessions_dir=tmp_path)


# ----- env-gated cloud-provider tests ------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_TTS_TESTS") != "1" or not os.environ.get("ELEVENLABS_API_KEY"),
    reason="Set RUN_TTS_TESTS=1 + ELEVENLABS_API_KEY to enable (real API).",
)
async def test_integration_elevenlabs(tmp_path: Path):
    _write_script(
        tmp_path,
        "s_el",
        beats=[
            {"beat_id": "b1", "lines": [{"text": "Bell rings."}]},
        ],
    )
    result = await run_tts("s_el", sessions_dir=tmp_path, provider_name="elevenlabs")
    assert not result.failed
    assert result.lines[0].wav.is_file()
    assert result.lines[0].duration_sec > 0


# ----- 0.11.0 — env wiring (auto-include) --------------------------------
#
# These are the helpers the chain's `_resolve_enabled` uses to decide
# whether to add the `tts` step to the default enabled set when the
# operator hasn't explicitly set `include_tts`. They read the env at
# call time so a process that imports the module with no TTS keys
# still works — a hot-reload that injects ELEVENLABS_API_KEY into
# os.environ at runtime takes effect on the next call.


def test_available_providers_empty_when_no_keys(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert available_providers() == []


def test_available_providers_lists_elevenlabs_when_set(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert available_providers() == ["elevenlabs"]


def test_available_providers_lists_openai_when_only_openai_set(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    assert available_providers() == ["openai"]


def test_available_providers_prefers_elevenlabs_order_when_both_set(monkeypatch):
    """The order matches `build_provider`'s auto: elevenlabs first.
    `available_providers()[0]` is the same pick the auto path takes."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    assert available_providers() == ["elevenlabs", "openai"]


def test_has_tts_creds_true_when_any_key_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert has_tts_creds() is True


def test_has_tts_creds_false_when_no_keys(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert has_tts_creds() is False


def test_should_auto_include_tts_true_when_creds_and_flag_default(monkeypatch):
    """Default `vod_tts_auto_include=True` + any TTS key → auto-include."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert should_auto_include_tts() is True


def test_should_auto_include_tts_false_when_no_creds(monkeypatch):
    """No TTS key in env → don't auto-include, even with the flag on."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert should_auto_include_tts() is False


def test_should_auto_include_tts_false_when_flag_disabled(monkeypatch):
    """Operator opted out via vod_tts_auto_include=False → no auto."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    assert should_auto_include_tts(vod_tts_auto_include=False) is False


def test_should_auto_include_tts_false_when_no_creds_and_flag_off(monkeypatch):
    """Both off — same answer, but covered for symmetry."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert should_auto_include_tts(vod_tts_auto_include=False) is False
