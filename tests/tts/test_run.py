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


# ----- 0.12.0 — shared httpx client for the elevenlabs provider --------
#
# The elevenlabs path used to instantiate its own ``httpx.AsyncClient``
# per call (TLS handshake + connection-pool init per line). 0.12.0
# migrates it to ``tradefarm.runtime.http.get_shared_client`` +
# ``with_retries`` so the keepalive + retry behaviour matches the
# LLM hot path.


class _FakeResp:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content
        self.text = ""

    def raise_for_status(self) -> None:
        # Mirror httpx.Response: 4xx/5xx raise so the retry helper
        # can re-invoke; 2xx/3xx are silent. The retry helper only
        # catches ``httpx.HTTPStatusError`` + ``httpx.RequestError``,
        # so we instantiate the real exception class.
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("POST", "https://api.elevenlabs.io")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


class _RecordingClient:
    """Fake shared httpx client. Records POSTs + replays scripted
    ``(status, body)`` responses in order. Non-2xx raises so the
    retry helper re-runs the call."""

    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url: str, *, json=None, headers=None, timeout=None, **_) -> _FakeResp:  # noqa: ANN001
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if not self._responses:
            raise RuntimeError("no scripted response")
        return self._responses.pop(0)


def _patch_shared_client(monkeypatch, fake: _RecordingClient) -> None:
    async def _get() -> _RecordingClient:
        return fake

    from tradefarm.tts import run as tts_run

    monkeypatch.setattr(tts_run, "get_shared_client", _get)


async def test_elevenlabs_uses_shared_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tradefarm.tts.run import ElevenLabsTtsProvider

    # 200 OK returns mp3 bytes the downstream ffmpeg transcode
    # would consume. The test doesn't actually need the wav to
    # be valid; ffmpeg will fail and we don't care — we just
    # assert the provider's HTTP shape and the shared-client use.
    fake = _RecordingClient(
        [_FakeResp(200, content=b"\xff\xfb\x90\x00" + b"\x00" * 100)]
    )
    _patch_shared_client(monkeypatch, fake)

    # Replace ffmpeg so the test doesn't shell out.
    def _no_ffmpeg(*args, **kwargs):
        from subprocess import CompletedProcess

        return CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("subprocess.run", _no_ffmpeg)

    p = ElevenLabsTtsProvider(api_key="fake")
    # Intercept the ffmpeg call by monkey-patching subprocess at the
    # call-site module (the elevenlabs provider does `import subprocess`
    # at the top, so we patch the module that the import resolves to).
    import sys

    sys.modules["subprocess"].run = _no_ffmpeg  # type: ignore[attr-defined]

    out = tmp_path / "line.wav"
    # We expect this to succeed even though the mp3 is bogus,
    # because the elevenlabs provider just writes the bytes to
    # ``.mp3`` and shells out to ffmpeg (which we no-op'd).
    await p.synthesize("hello world", voice="ignored", out_path=out)

    assert len(fake.calls) == 1
    assert "api.elevenlabs.io" in fake.calls[0]["url"]
    assert fake.calls[0]["headers"]["xi-api-key"] == "fake"
    # The shared client is passed `timeout=30.0` per request; the
    # provider's old `async with httpx.AsyncClient(timeout=30.0)`
    # is gone.
    assert fake.calls[0]["timeout"] == 30.0


async def test_elevenlabs_retries_on_5xx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Transient 5xx should be retried by the shared retry helper
    (max 3 attempts). The provider records a single successful
    line on the third try."""
    from tradefarm.tts.run import ElevenLabsTtsProvider

    # 503, 503, 200 → retry helper retries 2x, third succeeds.
    fake = _RecordingClient(
        [
            _FakeResp(503, content=b"server error"),
            _FakeResp(503, content=b"server error"),
            _FakeResp(200, content=b"\xff\xfb\x90\x00" + b"\x00" * 100),
        ]
    )
    _patch_shared_client(monkeypatch, fake)

    import sys
    from subprocess import CompletedProcess

    sys.modules["subprocess"].run = lambda *a, **kw: CompletedProcess(  # type: ignore[attr-defined]
        args=a, returncode=0, stdout=b"", stderr=b""
    )

    p = ElevenLabsTtsProvider(api_key="fake")
    out = tmp_path / "line.wav"
    await p.synthesize("hi", voice="ignored", out_path=out)
    # 3 POSTs total = 2 retries + 1 success.
    assert len(fake.calls) == 3


async def test_elevenlabs_4xx_does_not_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A 4xx (other than 429) is a real failure, not a transient
    blip. The provider records the failed line in ``result.failed``
    and the orchestrator moves on to the next line — the retry
    helper MUST NOT re-raise and force the chain into a retry loop."""
    from tradefarm.tts.run import run_tts

    fake = _RecordingClient([_FakeResp(400, content=b"bad voice id")])
    _patch_shared_client(monkeypatch, fake)

    import sys
    from subprocess import CompletedProcess

    sys.modules["subprocess"].run = lambda *a, **kw: CompletedProcess(  # type: ignore[attr-defined]
        args=a, returncode=0, stdout=b"", stderr=b""
    )

    _write_script(
        tmp_path,
        "s_bad",
        beats=[
            {"beat_id": "b1", "lines": [{"text": "hi"}]},
        ],
    )
    # We expect a single POST (no retry on 400) and the line to
    # land in ``result.failed`` (not crash the whole run).
    result = await run_tts("s_bad", sessions_dir=tmp_path, provider_name="elevenlabs", api_key="fake")
    assert len(fake.calls) == 1
    assert len(result.lines) == 0
    assert len(result.failed) == 1
