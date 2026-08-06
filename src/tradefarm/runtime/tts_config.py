"""Process-wide runtime TTS configuration.

0.17.0 — the dashboard's TTS settings panel flips the active provider
at runtime (no env-var restart). This module owns the singleton; the
``TtsConfig`` shape is read by the recap/podcast synthesis paths and
the daily VOD pipeline's TTS step.

The runtime config overrides `settings.podcast_tts_provider` and
`settings.podcast_voice`. If the operator has never touched the panel,
``get_tts_config()`` returns a config built from settings defaults
(so the existing env-var-driven behavior is preserved). The switch
takes effect on the *next* TTS call — the in-flight synthesis
completes with the old config (a provider object is per-call).

Single-process only. A multi-worker deployment would need to push the
config into a shared store (DB or Redis); not a current concern (the
sandbox runs one orchestrator + one web process on the same host).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from tradefarm.config import settings


# Allowed accent / color values for the lower_third / stream_banner events.
# Mirrored from the stream-side literal in ``useStreamCommands`` so the
# backend never has to guess at runtime.
VALID_TTS_PROVIDERS: frozenset[str] = frozenset({"openai", "elevenlabs", "silence"})

# Voice lists per provider. The OpenAI list is the SDK's stock set
# (https://platform.openai.com/docs/guides/text-to-speech/voice-options).
# The ElevenLabs list is a small subset of well-known stock voices;
# operators with custom clones pass the voice id directly via env.
OPENAI_VOICES: tuple[str, ...] = (
    "alloy", "echo", "fable", "onyx", "nova", "shimmer",
)
ELEVENLABS_VOICES: tuple[str, ...] = (
    "rachel", "domi", "bella", "antoni", "elli", "josh",
    "arnold", "adam", "sam",
)
# The silence provider has no voice concept but the UI wants a label.
SILENCE_VOICES: tuple[str, ...] = ("silent",)

VOICES_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "openai": OPENAI_VOICES,
    "elevenlabs": ELEVENLABS_VOICES,
    "silence": SILENCE_VOICES,
}

# Per-character cost (USD) for a 1000-char line, per provider. Rough
# order-of-magnitude numbers for the spend estimate; the real bill is
# what the cloud provider charges. Used by the dashboard's "preview"
# button + the daily spend counter.
COST_PER_1K_CHARS_USD: dict[str, float] = {
    "openai": 0.015,       # tts-1-hd
    "elevenlabs": 0.30,    # flash v2_5
    "silence": 0.0,
}


@dataclass(frozen=True)
class TtsConfig:
    """Effective TTS settings used by the synthesis paths.

    `speaking_rate` mirrors the `rate` parameter the OpenAI SDK accepts
    (0.25 - 4.0; default 1.0). Cloud providers all support it; the
    silent provider ignores it (the duration is computed from the
    word count + a fixed WPM).
    """

    provider: str
    voice: str
    speaking_rate: float = 1.0

    def to_payload(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "voice": self.voice,
            "speaking_rate": self.speaking_rate,
        }


_DEFAULT_CONFIG = TtsConfig(
    provider=settings.podcast_tts_provider,
    voice=settings.podcast_voice,
    speaking_rate=1.0,
)

_lock = threading.Lock()
_current: TtsConfig = _DEFAULT_CONFIG


def get_tts_config() -> TtsConfig:
    """Return the active TTS config (snapshot — read-only)."""
    with _lock:
        return _current


def set_tts_config(config: TtsConfig) -> TtsConfig:
    """Replace the active config. Returns the previous config so the
    caller (admin endpoint) can include it in the response.

    Validation: provider must be in `VALID_TTS_PROVIDERS`; voice must
    be non-empty. The caller (admin endpoint) is expected to have
    validated `has_tts_creds` first so a missing-key switch doesn't
    leak into the synthesis path.
    """
    if config.provider not in VALID_TTS_PROVIDERS:
        raise ValueError(f"unknown provider: {config.provider!r}")
    if not config.voice or not config.voice.strip():
        raise ValueError("voice must be a non-empty string")
    if not 0.25 <= config.speaking_rate <= 4.0:
        raise ValueError("speaking_rate must be in [0.25, 4.0]")

    global _current
    with _lock:
        previous = _current
        _current = config
    return previous


def reset_tts_config() -> TtsConfig:
    """Reset to the env-var defaults. Useful for tests + the
    operator's "revert to env defaults" button (not yet a UI
    affordance but easy to add)."""
    global _current
    with _lock:
        previous = _current
        _current = TtsConfig(
            provider=settings.podcast_tts_provider,
            voice=settings.podcast_voice,
            speaking_rate=1.0,
        )
    return previous


def estimate_cost_usd(provider: str, text: str) -> float:
    """Return the rough cost (USD) of synthesizing ``text`` at the
    given provider's per-char rate. Used by the preview button to
    show "this will cost ~$0.0012" before the operator commits."""
    rate = COST_PER_1K_CHARS_USD.get(provider, 0.0)
    return round(rate * len(text) / 1000.0, 6)
