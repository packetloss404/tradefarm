"""Tests for ``tradefarm.api.pipeline._fire_webhook`` — terminal-state
notification dispatch.

The webhook is the operator's "your reel is on YouTube" or
"today's run failed" signal. We assert:

- empty env var → no HTTP call (no-op)
- done payload shape: ``{run_id, session_id, status: 'done', at, ...}``
- failed payload shape: ``{run_id, session_id, status: 'failed', error, at}``
- ``httpx.HTTPError`` and a generic exception (e.g. invalid URL scheme)
  are swallowed so a webhook outage can never fail a run
- the dispatch is best-effort: a 4xx / 5xx response from the endpoint
  is logged but doesn't raise

We patch ``httpx.post`` directly rather than spinning a local server
to keep the tests fast and isolated.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx

import tradefarm.api.pipeline as api_pipeline
from tradefarm.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(status: str = "done", error: str | None = None) -> api_pipeline.PipelineRun:
    return api_pipeline.PipelineRun(
        run_id="d34db33f1234",
        session_id="s_2026-08-04_abcdef",
        date="2026-08-04",
        enabled=["session", "beats", "headless"],
        force=False,
        dry_run=False,
        status=status,
        error=error,
    )


# ---------------------------------------------------------------------------
# Empty env var = no-op
# ---------------------------------------------------------------------------


def test_webhook_noop_when_env_var_empty(monkeypatch) -> None:
    """No env var, no call. The operator hasn't set up notifications."""
    monkeypatch.setattr(settings, "vod_notify_webhook", "")
    with patch("tradefarm.api.pipeline.httpx.post") as mock_post:
        api_pipeline._fire_webhook(_make_run())
        mock_post.assert_not_called()


def test_webhook_noop_when_env_var_whitespace(monkeypatch) -> None:
    """A whitespace-only env var is treated as empty (operator typo)."""
    monkeypatch.setattr(settings, "vod_notify_webhook", "   ")
    with patch("tradefarm.api.pipeline.httpx.post") as mock_post:
        api_pipeline._fire_webhook(_make_run())
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Done payload
# ---------------------------------------------------------------------------


def test_webhook_fires_done_payload(monkeypatch) -> None:
    """A done run fires POST with the documented payload shape."""
    monkeypatch.setattr(settings, "vod_notify_webhook", "https://example.com/hook")
    captured: dict[str, Any] = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(200, request=httpx.Request("POST", url))

    with patch("tradefarm.api.pipeline.httpx.post", side_effect=fake_post):
        api_pipeline._fire_webhook(_make_run(status="done"))

    assert captured["url"] == "https://example.com/hook"
    assert captured["json"]["run_id"] == "d34db33f1234"
    assert captured["json"]["session_id"] == "s_2026-08-04_abcdef"
    assert captured["json"]["status"] == "done"
    assert "at" in captured["json"]
    # The failed-payload field must NOT be present on a done run.
    assert "error" not in captured["json"]
    # 5s timeout per the contract.
    assert captured["timeout"] == 5.0


# ---------------------------------------------------------------------------
# Failed payload
# ---------------------------------------------------------------------------


def test_webhook_fires_failed_payload_with_error(monkeypatch) -> None:
    """A failed run fires POST with the error string included."""
    monkeypatch.setattr(settings, "vod_notify_webhook", "https://discord.com/api/webhooks/abc")
    captured: dict[str, Any] = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(204, request=httpx.Request("POST", url))

    with patch("tradefarm.api.pipeline.httpx.post", side_effect=fake_post):
        api_pipeline._fire_webhook(
            _make_run(status="failed", error="step 'headless' failed: TimeoutError")
        )

    assert captured["url"] == "https://discord.com/api/webhooks/abc"
    assert captured["json"]["status"] == "failed"
    assert captured["json"]["error"] == "step 'headless' failed: TimeoutError"
    assert captured["json"]["run_id"] == "d34db33f1234"
    assert captured["json"]["session_id"] == "s_2026-08-04_abcdef"


# ---------------------------------------------------------------------------
# Best-effort: errors are swallowed
# ---------------------------------------------------------------------------


def test_webhook_swallows_httpx_http_error(monkeypatch) -> None:
    """An ``httpx.HTTPError`` (timeout, connect error, etc.) is logged
    and swallowed — a webhook outage must never fail a run."""
    monkeypatch.setattr(settings, "vod_notify_webhook", "https://example.com/down")
    with patch(
        "tradefarm.api.pipeline.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        # Must not raise.
        api_pipeline._fire_webhook(_make_run())


def test_webhook_swallows_generic_exception(monkeypatch) -> None:
    """A non-httpx exception (e.g. invalid URL scheme) is also swallowed."""
    monkeypatch.setattr(settings, "vod_notify_webhook", "not-a-valid-url")
    with patch(
        "tradefarm.api.pipeline.httpx.post",
        side_effect=ValueError("invalid url"),
    ):
        # Must not raise.
        api_pipeline._fire_webhook(_make_run())


def test_webhook_swallows_5xx_response(monkeypatch) -> None:
    """A 5xx response from the endpoint doesn't fail the run — the
    webhook is best-effort. (The contract is "POST and don't worry
    about the response"; Discord / Slack both return 204 on success
    but might 5xx under transient load.)"""
    monkeypatch.setattr(settings, "vod_notify_webhook", "https://example.com/hook")
    with patch(
        "tradefarm.api.pipeline.httpx.post",
        return_value=httpx.Response(503, request=httpx.Request("POST", "https://example.com/hook")),
    ):
        # Must not raise even on 5xx.
        api_pipeline._fire_webhook(_make_run())


# ---------------------------------------------------------------------------
# End-to-end: webhook fires after the run task completes
# ---------------------------------------------------------------------------


def test_webhook_invoked_at_terminal_state(monkeypatch) -> None:
    """End-to-end: drive ``_run_pipeline_task`` with a stubbed runner
    + httpx.post, assert the webhook fires once at terminal state
    with the right payload.

    Patches the DB-persist step to a no-op so the test isn't
    coupled to the global ``tradefarm.db`` (which the default
    test loop has open connections to). The webhook contract is
    independent of the DB layer — the persist is just a side
    effect.
    """
    import tradefarm.render.pipeline as pipeline_mod

    monkeypatch.setattr(settings, "vod_notify_webhook", "https://example.com/hook")

    # No-op the DB persist (aiosqlite's worker thread is bound to
    # the test client's event loop in the other tests; here we run
    # the task in a fresh asyncio.run loop, which makes the global
    # SessionLocal unusable).
    async def _noop_persist(run):
        return None

    monkeypatch.setattr(api_pipeline, "_ensure_persisted", _noop_persist)

    captured: list[dict[str, Any]] = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured.append({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(200, request=httpx.Request("POST", url))

    def stub_run_pipeline(
        *, session_id, opts, enabled, force, dry_run, sink=None, return_timings=False
    ):
        if sink:
            sink("DONE")
        return [] if return_timings else None

    monkeypatch.setattr(pipeline_mod, "run_pipeline", stub_run_pipeline)
    monkeypatch.setattr("tradefarm.api.pipeline.httpx.post", fake_post)

    import asyncio

    run = _make_run(status="pending")
    asyncio.run(
        api_pipeline._run_pipeline_task(
            run,
            pipeline_mod.PipelineOpts(
                sessions_dir=__import__("pathlib").Path("/tmp"),
                music=None,
                tts_provider="auto",
                tts_voice="alloy",
                upload_dry_run=True,
                stitch_xfade=0.4,
                force=False,
            ),
        )
    )
    # Exactly one POST fired, with the done payload.
    assert len(captured) == 1
    assert captured[0]["json"]["status"] == "done"
    assert captured[0]["url"] == "https://example.com/hook"
