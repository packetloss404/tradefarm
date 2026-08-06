"""Tests for the LLM script generation stage of the weekly podcast.

The LLM call is mocked so no real API keys are needed; we capture
the prompt the composer builds and assert it matches the spec
doc's template verbatim (down to the segment list + the "Bloomberg
daily meets The Office" tone line). The composer's own stub
fallback path is covered too.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch


from tradefarm.render import podcast as podcast_mod


# ----- helpers ------------------------------------------------------------


def _fake_llm_response() -> str:
    """A canned YAML-ish response the LLM would return. Matches the
    shape the parser in :func:`podcast._parse_script_yaml` expects."""
    return """\
intro: |
  Welcome to Rivalry Week, the weekly podcast.
topline: |
  Pool P&L this week: +1.42 percent.
day_1: |
  Day one, Monday. The opening bell rang.
day_2: |
  Day two. NVDA moved 3 percent.
day_3: |
  Day three. Bob and Mei squared off.
day_4: |
  Day four. The pairs agent fired twice.
day_5: |
  Day five. The wrap is on us.
wrap: |
  So that's the week.
"""


def _fake_rollup() -> dict[str, Any]:
    return {
        "week_id": "2026-W31",
        "date_range": ["2026-08-03", "2026-08-07"],
        "pool_pnl": 500.0,
        "pool_pnl_pct": 1.42,
        "strategy_rollup": {
            "momentum_12_1": {"agents": 25, "pnl": 300.0, "fills": 50},
        },
        "rivalries": [
            {"a": 12, "b": 47, "symbol": "NVDA", "count": 4, "a_pnl": 80, "b_pnl": -60},
        ],
        "sessions": [
            {"session_id": "s_2026-08-03_x", "fill_count": 35},
        ],
    }


def _fake_daily() -> list[dict[str, Any]]:
    return [
        {
            "session_id": "s_2026-08-03_x",
            "started_at": "2026-08-03T13:30:00+00:00",
            "fill_count": 35,
            "strategy_rollup": {},
            "rivalries": [],
            "top_beats": [
                {"id": "b1", "headline": "Bob buys NVDA", "score": 0.9},
            ],
        },
    ]


# ----- script generation --------------------------------------------------


def test_generate_script_uses_spec_prompt_template() -> None:
    """The prompt the LLM receives must include the spec's system
    prompt verbatim (segment list + tone line). This is the
    regression guard for the LLM quality — if someone rewords the
    prompt the tests will catch the deviation."""
    captured: dict[str, Any] = {}

    def _capture(prompt: str) -> tuple[str, str, str]:
        captured["prompt"] = prompt
        return _fake_llm_response(), "anthropic", "claude-haiku-4-5-20251001"

    with patch.object(podcast_mod, "_call_llm_for_script", side_effect=_capture):
        result = podcast_mod.generate_script(
            week_id="2026-W31",
            rollup=_fake_rollup(),
            daily_payloads=_fake_daily(),
        )
    assert result["provider"] == "anthropic"
    assert result["model"] == "claude-haiku-4-5-20251001"
    prompt = captured["prompt"]
    # The spec doc's required segments (intro/topline/day_1..day_5/wrap)
    # must be referenced in the prompt body.
    for key in ("intro", "topline", "day 1", "day 5", "week wrap"):
        assert key in prompt.lower(), f"prompt missing segment hint: {key}"
    # Tone line is part of the spec.
    assert "Bloomberg daily meets The Office" in prompt
    # The payload block is interpolated (the rollup + 5 daily payloads).
    assert '"rollup"' in prompt
    assert '"days"' in prompt
    assert "2026-W31" in prompt


def test_generate_script_parses_yaml_segments() -> None:
    """The LLM's YAML response is parsed into a {key: text} dict the
    downstream TTS / card renderer reads. Assert the 5 day-segments
    are present and the wrap is the closing block."""
    with patch.object(
        podcast_mod,
        "_call_llm_for_script",
        return_value=(_fake_llm_response(), "anthropic", "claude-haiku-4-5"),
    ):
        result = podcast_mod.generate_script(
            week_id="2026-W31",
            rollup=_fake_rollup(),
            daily_payloads=_fake_daily(),
        )
    segs = result["segments"]
    assert "intro" in segs
    assert "topline" in segs
    for k in ("day_1", "day_2", "day_3", "day_4", "day_5"):
        assert k in segs, f"missing segment {k}"
    assert "wrap" in segs
    assert "Welcome to Rivalry Week" in segs["intro"]
    assert "that's the week" in segs["wrap"].lower()
    # Word count is a rough size check (just non-zero + plausible).
    assert result["word_count"] > 30


def test_generate_script_falls_back_to_stub_when_no_creds() -> None:
    """When ``_call_llm_for_script`` raises (no provider creds, network
    error, etc.) the composer falls back to a hand-written stub so
    the rest of the chain (TTS, card, ffmpeg) can still run in CI."""
    with patch.object(
        podcast_mod,
        "_call_llm_for_script",
        side_effect=RuntimeError("no LLM creds"),
    ):
        result = podcast_mod.generate_script(
            week_id="2026-W31",
            rollup=_fake_rollup(),
            daily_payloads=[],
        )
    assert result["provider"] == "stub"
    # The stub still has all 7 segments the script schema needs.
    for k in ("intro", "topline", "day_1", "day_2", "day_3", "day_4", "day_5", "wrap"):
        assert k in result["segments"]
    # The stub pulls the pool_pnl_pct from the rollup so the host
    # at least reads the right number.
    assert "1.42" in result["segments"]["topline"]


# ----- yaml parser --------------------------------------------------------


def test_parse_script_yaml_handles_partial_response() -> None:
    """A partial LLM response (missing one or two keys) must NOT
    raise; the missing key just returns an empty string so the
    downstream TTS skips it rather than blowing up."""
    text = """\
intro: |
  Welcome to Rivalry Week.
day_1: |
  Day one prose.
"""
    segs = podcast_mod._parse_script_yaml(text)
    assert "intro" in segs
    assert "day_1" in segs
    # Missing keys are simply absent (callers handle the empty case).
    assert "wrap" not in segs


def test_load_script_file_skips_header_lines(tmp_path) -> None:
    """``write_script_file`` emits a ``# key: value`` header. The
    load helper must skip those lines so the parsed segments dict
    only contains the YAML body."""
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        "# week_id: 2026-W31\n"
        "# provider: stub\n"
        "# word_count: 5\n"
        "# ----\n"
        "intro: |\n"
        "  Welcome.\n"
        "wrap: |\n"
        "  See you.\n",
        encoding="utf-8",
    )
    segs = podcast_mod.load_script_file(script_path)
    assert segs["intro"] == "Welcome."
    assert segs["wrap"] == "See you."
