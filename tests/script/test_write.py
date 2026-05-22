"""Script writer — pure-function tests + LLM call gated behind env var."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tradefarm.script.write import (
    NarrationLine,
    BeatScript,
    Script,
    _count_words,
    _line_duration_sec,
    _strip_code_fences,
    build_user_prompt,
    format_beat_for_prompt,
    parse_response,
    script_to_dict,
    write_script_file,
)


# ----- prompt construction ------------------------------------------------


def test_format_beat_includes_id_kind_t_and_headline():
    beat = {
        "id": "b_open",
        "kind": "open",
        "t": "2026-05-21T13:30:00+00:00",
        "duration_sec": 12,
        "headline": "Market open",
        "sub": "100 agents",
        "metadata": {},
    }
    s = format_beat_for_prompt(beat)
    # Now wrapped in <beat>…</beat> with repr()-quoted ids per the
    # audit fix for prompt-injection (H16).
    assert "id='b_open'" in s
    assert "kind='open'" in s
    assert "2026-05-21T13:30:00+00:00" in s
    assert "Market open" in s
    assert "100 agents" in s
    assert s.startswith("<beat ") and s.endswith("</beat>")


def test_format_beat_only_emits_facts_with_known_keys():
    """metadata can carry arbitrary keys but we only surface the ones
    the narrator can quote without inventing context."""
    beat = {
        "id": "b1",
        "kind": "big_fill",
        "t": "x",
        "headline": "h",
        "sub": "s",
        "duration_sec": 30,
        "metadata": {
            "notional": 9600,
            "side": "buy",
            "session_internal_ref": "ignore-me",
        },
    }
    s = format_beat_for_prompt(beat)
    assert "notional=9600" in s
    assert "side='buy'" in s
    assert "session_internal_ref" not in s


def test_build_user_prompt_includes_episode_label():
    p = build_user_prompt(
        [{"id": "b1", "kind": "open", "t": "x", "headline": "h", "sub": "", "duration_sec": 12}],
        episode_label="s_2026-05-21_test",
    )
    assert "s_2026-05-21_test" in p
    assert "BEATS:" in p


# ----- response parsing --------------------------------------------------


def test_parse_response_happy_path():
    raw = json.dumps(
        {
            "episode_title": "Quiet Tuesday",
            "beats": [
                {"beat_id": "b_open", "lines": ["Bell rings.", "100 agents settle in."]},
                {"beat_id": "b_close", "lines": ["The tape closes flat.", "Tomorrow."]},
            ],
        }
    )
    title, beats = parse_response(raw, expected_beat_ids=["b_open", "b_close"])
    assert title == "Quiet Tuesday"
    assert [b.beat_id for b in beats] == ["b_open", "b_close"]
    # words + duration estimates populated
    first_line = beats[0].lines[0]
    assert first_line.words == 2 and first_line.duration_sec > 0


def test_parse_response_strips_code_fences():
    """Models love to wrap JSON in ```json … ``` even when asked not to."""
    raw = (
        "```json\n"
        + json.dumps({"episode_title": "t", "beats": [{"beat_id": "b1", "lines": ["one"]}]})
        + "\n```"
    )
    title, beats = parse_response(raw, expected_beat_ids=["b1"])
    assert title == "t"
    assert beats[0].beat_id == "b1"


def test_parse_response_preserves_order_of_expected_ids():
    """The model may return beats in any order; we re-sort to match
    the input so the TTS pipeline stays aligned."""
    raw = json.dumps(
        {
            "episode_title": "t",
            "beats": [
                {"beat_id": "b2", "lines": ["second"]},
                {"beat_id": "b1", "lines": ["first"]},
            ],
        }
    )
    _, beats = parse_response(raw, expected_beat_ids=["b1", "b2"])
    assert [b.beat_id for b in beats] == ["b1", "b2"]


def test_parse_response_drops_empty_lines():
    raw = json.dumps(
        {
            "episode_title": "t",
            "beats": [{"beat_id": "b1", "lines": ["", "  ", "real"]}],
        }
    )
    _, beats = parse_response(raw, expected_beat_ids=["b1"])
    assert [ln.text for ln in beats[0].lines] == ["real"]


def test_parse_response_raises_on_missing_beat():
    raw = json.dumps({"episode_title": "t", "beats": [{"beat_id": "b1", "lines": ["a"]}]})
    with pytest.raises(ValueError, match="missing narration"):
        parse_response(raw, expected_beat_ids=["b1", "b2"])


def test_parse_response_raises_on_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_response("hello not json", expected_beat_ids=["b1"])


def test_parse_response_raises_on_missing_beats_key():
    with pytest.raises(ValueError, match="beats"):
        parse_response(json.dumps({"episode_title": "t"}), expected_beat_ids=["b1"])


def test_parse_response_raises_on_beat_with_no_lines():
    raw = json.dumps(
        {
            "episode_title": "t",
            "beats": [{"beat_id": "b1", "lines": ["", "  "]}],
        }
    )
    with pytest.raises(ValueError, match="no usable lines"):
        parse_response(raw, expected_beat_ids=["b1"])


# ----- word + duration helpers -------------------------------------------


def test_word_counting_handles_punctuation_and_unicode():
    # em-dash and commas shouldn't inflate the count. `\b\w+\b` treats
    # the apostrophe in "Marcus'" as a word boundary (one token, not
    # two) — matches how TTS counts syllables for pacing.
    text = "Marcus' read on AVGO — eight winners, no losses."
    assert _count_words(text) == 8


def test_line_duration_scales_with_words():
    short = _line_duration_sec("two words")
    long_ = _line_duration_sec("this line has a few more words in it")
    assert long_ > short > 0


def test_strip_code_fences_handles_plain_json():
    raw = '{"a": 1}'
    assert _strip_code_fences(raw) == raw


def test_strip_code_fences_handles_fenced_json():
    raw = '```json\n{"a": 1}\n```'
    assert _strip_code_fences(raw) == '{"a": 1}'


def test_extract_json_handles_leading_prose():
    """Common Claude failure mode: 'Here is the JSON:\\n```json\\n…\\n```'
    The extractor must grab the JSON body anyway."""
    raw = 'Here is the JSON:\n```json\n{"a": 1}\n```\nHope this helps!'
    assert _strip_code_fences(raw) == '{"a": 1}'


def test_extract_json_handles_unfenced_object_with_preamble():
    """No fence at all, just prose then an object."""
    raw = 'Sure! {"episode_title": "t", "beats": []}'
    title, beats = parse_response(raw, expected_beat_ids=[])
    assert title == "t"
    assert beats == []


def test_parse_response_dedupes_beat_ids_keeping_first():
    """A model that repeats a beat shouldn't lose the earlier draft.
    Regression: previous version did last-wins via dict comprehension."""
    raw = json.dumps(
        {
            "episode_title": "t",
            "beats": [
                {"beat_id": "b1", "lines": ["first version"]},
                {"beat_id": "b1", "lines": ["second version — should be ignored"]},
            ],
        }
    )
    _, beats = parse_response(raw, expected_beat_ids=["b1"])
    assert beats[0].lines[0].text == "first version"


async def test_write_script_missing_api_key_raises_cleanly(tmp_path: Path, monkeypatch):
    """Used to bottom out inside the SDK with an opaque trace."""
    from tradefarm.script import write as writer

    monkeypatch.setattr(writer.settings, "anthropic_api_key", "")
    sdir = tmp_path / "s_nokey"
    sdir.mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b1",
                    "kind": "open",
                    "t": "x",
                    "headline": "h",
                    "sub": "",
                    "duration_sec": 10,
                    "metadata": {},
                },
            ]
        )
    )
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await writer.write_script("s_nokey", sessions_dir=tmp_path)


async def test_write_script_retry_passes_prior_assistant_turn(tmp_path: Path, monkeypatch):
    """The retry must show the model its own previous reply, not just
    append the error to the user prompt."""
    from tradefarm.script import write as writer

    monkeypatch.setattr(writer.settings, "anthropic_api_key", "test-key")
    sdir = tmp_path / "s_retry2"
    sdir.mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b1",
                    "kind": "open",
                    "t": "x",
                    "headline": "h",
                    "sub": "",
                    "duration_sec": 10,
                    "metadata": {},
                },
            ]
        )
    )
    seen: list[list[dict]] = []

    async def fake_call_model(*, user_prompt, prior_messages, **kwargs):
        seen.append(prior_messages or [])
        if not seen[-1]:
            return "garbage", {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            }
        return json.dumps({"episode_title": "t", "beats": [{"beat_id": "b1", "lines": ["ok"]}]}), {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    monkeypatch.setattr(writer, "_call_model", fake_call_model)
    await writer.write_script("s_retry2", sessions_dir=tmp_path)
    # Second call's prior_messages should contain a user + assistant pair.
    assert len(seen) == 2
    roles = [m["role"] for m in seen[1]]
    assert "user" in roles and "assistant" in roles
    # The assistant turn should be the previous "garbage" reply.
    assistant_turn = next(m for m in seen[1] if m["role"] == "assistant")
    assert assistant_turn["content"] == "garbage"


# ----- script_to_dict + write ---------------------------------------------


def test_script_to_dict_round_trip(tmp_path: Path):
    s = Script(
        session_id="s_test",
        episode_title="A Day",
        model="claude-haiku-4-5-20251001",
        beats=[
            BeatScript(
                beat_id="b1",
                lines=[NarrationLine(text="hi", words=1, duration_sec=0.39)],
            )
        ],
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 100,
        },
    )
    d = script_to_dict(s)
    assert d["session_id"] == "s_test"
    assert d["beats"][0]["lines"][0]["text"] == "hi"
    assert d["total_words"] == 1
    # round-trips through json without loss
    rt = json.loads(json.dumps(d))
    assert rt["beats"][0]["beat_id"] == "b1"


def test_write_script_file_creates_parent(tmp_path: Path):
    target = tmp_path / "out" / "deep" / "script.json"
    write_script_file(
        Script(session_id="s", episode_title="t", model="m", beats=[]),
        target,
    )
    assert target.is_file()
    assert json.loads(target.read_text())["session_id"] == "s"


# ----- async entry: mock the API call -------------------------------------


async def test_write_script_uses_mocked_model(tmp_path: Path, monkeypatch):
    """End-to-end through write_script() with the API call mocked so
    the test stays offline."""
    from tradefarm.script import write as writer

    sdir = tmp_path / "s_mock"
    sdir.mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b1",
                    "kind": "open",
                    "t": "x",
                    "headline": "h",
                    "sub": "s",
                    "duration_sec": 10,
                    "metadata": {},
                },
                {
                    "id": "b2",
                    "kind": "big_fill",
                    "t": "y",
                    "headline": "h2",
                    "sub": "s2",
                    "duration_sec": 20,
                    "metadata": {"notional": 5000},
                },
            ]
        )
    )

    async def fake_call_model(**kwargs):
        return json.dumps(
            {
                "episode_title": "Mock Day",
                "beats": [
                    {"beat_id": "b1", "lines": ["First.", "Second."]},
                    {"beat_id": "b2", "lines": ["Third.", "Fourth.", "Fifth."]},
                ],
            }
        ), {
            "input_tokens": 800,
            "output_tokens": 60,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 800,
        }

    monkeypatch.setattr(writer, "_call_model", fake_call_model)
    script = await writer.write_script("s_mock", sessions_dir=tmp_path)

    assert script.episode_title == "Mock Day"
    assert [b.beat_id for b in script.beats] == ["b1", "b2"]
    assert sum(len(b.lines) for b in script.beats) == 5
    assert script.usage["output_tokens"] == 60


async def test_write_script_retries_on_parse_failure(tmp_path: Path, monkeypatch):
    """First call returns garbage → second call is allowed (re-prompted
    with the validation error) and succeeds."""
    from tradefarm.script import write as writer

    sdir = tmp_path / "s_retry"
    sdir.mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b1",
                    "kind": "open",
                    "t": "x",
                    "headline": "h",
                    "sub": "",
                    "duration_sec": 10,
                    "metadata": {},
                },
            ]
        )
    )

    calls: list[str] = []

    async def flaky_call_model(*, user_prompt, **kwargs):
        calls.append(user_prompt)
        if len(calls) == 1:
            return "not even close to json", {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            }
        return json.dumps(
            {
                "episode_title": "Recovered",
                "beats": [{"beat_id": "b1", "lines": ["got it"]}],
            }
        ), {
            "input_tokens": 20,
            "output_tokens": 5,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 0,
        }

    monkeypatch.setattr(writer, "_call_model", flaky_call_model)
    script = await writer.write_script("s_retry", sessions_dir=tmp_path)

    assert len(calls) == 2
    assert script.episode_title == "Recovered"
    # The second prompt must mention the validation failure.
    assert "previous reply did not validate" in calls[1]


async def test_write_script_gives_up_after_max_retries(tmp_path: Path, monkeypatch):
    from tradefarm.script import write as writer

    sdir = tmp_path / "s_fail"
    sdir.mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b1",
                    "kind": "open",
                    "t": "x",
                    "headline": "h",
                    "sub": "",
                    "duration_sec": 10,
                    "metadata": {},
                },
            ]
        )
    )

    async def always_garbage(**kwargs):
        return "still not json", {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    monkeypatch.setattr(writer, "_call_model", always_garbage)
    with pytest.raises(RuntimeError, match="failed after"):
        await writer.write_script("s_fail", sessions_dir=tmp_path, max_retries=1)


async def test_write_script_missing_beats_raises(tmp_path: Path):
    from tradefarm.script.write import write_script

    with pytest.raises(FileNotFoundError):
        await write_script("never", sessions_dir=tmp_path)


# ----- env-gated real-API integration ------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="Set RUN_LLM_TESTS=1 + ANTHROPIC_API_KEY to enable.",
)
async def test_integration_real_anthropic_call(tmp_path: Path):
    """Hit the real API. Costs ~$0.01 per run. Set
    RUN_LLM_TESTS=1 + ANTHROPIC_API_KEY=… to enable."""
    from tradefarm.script.write import write_script

    sdir = tmp_path / "s_real"
    sdir.mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b_open",
                    "kind": "open",
                    "t": "2026-05-21T13:30:00+00:00",
                    "headline": "Market open · 100 agents back at their desks",
                    "sub": "Pre-market gap +0.4%",
                    "duration_sec": 12,
                    "metadata": {},
                },
                {
                    "id": "b_big",
                    "kind": "big_fill",
                    "t": "2026-05-21T14:00:00+00:00",
                    "headline": "Marcus Wagner goes long NVDA — $9,600 notional",
                    "sub": "80 × $120.00 · 14:00 ET",
                    "duration_sec": 30,
                    "metadata": {"notional": 9600, "side": "buy", "qty": 80, "price": 120},
                },
            ]
        )
    )
    script = await write_script("s_real", sessions_dir=tmp_path)
    assert len(script.beats) == 2
    assert sum(len(b.lines) for b in script.beats) >= 2
    assert script.usage["output_tokens"] > 0
