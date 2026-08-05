"""Tests for the VOD autonomy settings in ``tradefarm.config.Settings``.

The new settings (``vod_pipeline_enabled``, ``vod_market_close_offset_min``,
``vod_publish_at_et``, ``vod_notify_webhook``) follow the existing
pydantic-settings pattern. We assert:

- **defaults are sane** — every field has a usable value out of the
  box, so a fresh clone + ``uv run`` doesn't need a `.env` to behave
  reasonably.
- **env override works** — the operator can flip a setting via
  ``.env`` and ``Settings`` reflects it.
- **offset bounds** — the cool-off window is a non-negative integer
  in [0, 120] minutes. Outside that range is a pydantic ValidationError.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tradefarm.config import Settings


def test_vod_defaults_are_sane(monkeypatch) -> None:
    """Every VOD setting has a non-empty / non-zero default that
    makes sense for a fresh clone."""
    # Defensive: clear any env vars that might be set in the test
    # environment (CI runners, dev's .env, etc.) so we're testing
    # the model's own defaults.
    for key in (
        "VOD_PIPELINE_ENABLED",
        "VOD_MARKET_CLOSE_OFFSET_MIN",
        "VOD_PUBLISH_AT_ET",
        "VOD_NOTIFY_WEBHOOK",
    ):
        monkeypatch.delenv(key, raising=False)

    s = Settings()
    # Master switch defaults OFF — autonomy is opt-in.
    assert s.vod_pipeline_enabled is False
    # 5 minute cool-off after close matches the operator's
    # documented `sleep 16:05 && python -m tradefarm.render.pipeline`
    # workflow.
    assert s.vod_market_close_offset_min == 5
    # 16:30 ET = 30 min after close = matches yt.metadata's
    # `default_publish_at()` for `private` uploads.
    assert s.vod_publish_at_et == "16:30"
    # No webhook by default — opt-in notification.
    assert s.vod_notify_webhook == ""


def test_vod_env_overrides(monkeypatch) -> None:
    """Each setting can be overridden via the corresponding env var."""
    monkeypatch.setenv("VOD_PIPELINE_ENABLED", "true")
    monkeypatch.setenv("VOD_MARKET_CLOSE_OFFSET_MIN", "10")
    monkeypatch.setenv("VOD_PUBLISH_AT_ET", "17:00")
    monkeypatch.setenv("VOD_NOTIFY_WEBHOOK", "https://ntfy.sh/my-topic/notify")

    s = Settings()
    assert s.vod_pipeline_enabled is True
    assert s.vod_market_close_offset_min == 10
    assert s.vod_publish_at_et == "17:00"
    assert s.vod_notify_webhook == "https://ntfy.sh/my-topic/notify"


def test_vod_offset_rejects_negative(monkeypatch) -> None:
    """``vod_market_close_offset_min`` must be >= 0 — a negative
    cool-off would fire before the market closed, which is the
    opposite of the documented contract."""
    monkeypatch.setenv("VOD_MARKET_CLOSE_OFFSET_MIN", "-5")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "vod_market_close_offset_min" in str(exc_info.value)


def test_vod_offset_rejects_too_large(monkeypatch) -> None:
    """``vod_market_close_offset_min`` is capped at 120 min — the
    operator can wait up to 2h, but not longer. A 5h cool-off
    would be a misconfiguration; the cap catches it."""
    monkeypatch.setenv("VOD_MARKET_CLOSE_OFFSET_MIN", "999")
    with pytest.raises(ValidationError):
        Settings()
