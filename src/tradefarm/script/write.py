"""LLM script writer — turns beats.json into per-beat narration lines
that downstream TTS reads aloud over the matching clip.

Input:  out/sessions/<id>/beats.json   (from session.beats)
        (optional) out/sessions/<id>/manifest.json for episode context
Output: out/sessions/<id>/script.json  — list of {beat_id, lines:[…]}

One batched Anthropic call per session: it's cheaper (ephemeral prompt
caching amortises the static system prompt), faster (~1-2s vs 10-15
sequential calls), and produces more coherent voice across the
episode. The model is asked to return JSON; we parse with one retry
on a malformed first shot.

Style is enforced by SYSTEM_PROMPT — *The Farm*'s tone: dry warmth,
no hype, agents as characters, specificity over adjectives. See the
docstring on SYSTEM_PROMPT for the full guide.

The writer never skips beats. Recap clips don't render today (the
recap scene isn't replay-aware yet), but the narration is ready for
when they do.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradefarm.config import settings


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 2048
# Cost-gate: budget the model to ~3 narration lines × ~15 words per
# beat; one extra retry on parse-fail; cap to keep a stuck session
# from running away.
DEFAULT_MAX_RETRIES = 1
WPM_TTS_PACE = 155  # used to estimate per-line duration


SYSTEM_PROMPT = """\
You are the narrator of *The Farm*, a daily 10-15 minute auto-generated
video about 100 AI agents paper-trading US equities. The audience is
curious developers and finance enthusiasts; the voice is dry warmth, a
slightly BBC-y cricket-commentator energy. Each beat below is a moment
auto-detected from one trading day; for each, write 2-3 short narration
lines that play over the matching 20-40 second video clip.

Voice principles:
- Agents are characters, not processes. Use their office names
  ("Marcus Wagner", "Mei Patel"). The number behind them is incidental.
- The market is the antagonist; agents react. Tape rolls, prints come
  in, the bell rings.
- Dry warmth, not hype. No "incredible", no "insane move". Earn the
  silence.
- Specificity over adjectives. "$9,600 of NVDA" beats "a massive trade".
- 2-3 lines per beat, 10-20 words each. Total roughly 30-50 words per
  beat. Concise, designed for TTS over ~30 seconds.

Per-kind tone:
- open: ceremony + stakes. Establish weather of the tape.
- big_fill: weight + consequence. State the size like you're putting
  it on a table.
- divergence: tension without taking sides. Two agents, one symbol,
  opposite signs. Don't resolve.
- streak: quiet momentum. Hint at fragility.
- top_winner: credit the read, not just the outcome. Luck and skill
  rhyme on a one-day chart.
- top_loser: empathy, never schadenfreude. The agent made a call; the
  tape disagreed.
- closing_burst: pace + accumulation. Short, clipped sentences.
- recap: reflective. Settle the day.

Hard guard-rails — treat as inviolable:
- Don't explain mechanics ("SMA-20 means…").
- Don't mention TradeFarm, Claude, the LLM, TTS, the pipeline, or
  "this video". Pretend the show is just a show.
- Don't open lines with "And", "So", "Well", "Now", or rhetorical
  questions.
- Don't predict tomorrow.
- No finance clichés: bulls/bears, knife-catching, FOMO, to the moon.

Output format: a SINGLE JSON object, no prose around it, matching:
  {
    "episode_title": "string, max 60 chars, no punctuation other than . -",
    "beats": [
      {"beat_id": "b_open",
       "lines": ["line 1", "line 2"]},
      ...
    ]
  }
Return EXACTLY one beat object per input beat, in the same order.
"""


# ----- record types --------------------------------------------------------


@dataclass(frozen=True)
class NarrationLine:
    text: str
    words: int
    duration_sec: float


@dataclass(frozen=True)
class BeatScript:
    beat_id: str
    lines: list[NarrationLine]


@dataclass
class Script:
    session_id: str
    episode_title: str
    model: str
    beats: list[BeatScript] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)  # input/output/cache tokens for cost tracking


# ----- prompt construction (pure) -----------------------------------------


def format_beat_for_prompt(beat: dict[str, Any]) -> str:
    """One compact paragraph per beat: enough context for the model to
    write a voiced line without leaking pipeline jargon."""
    bid = beat.get("id", "?")
    kind = beat.get("kind", "?")
    t = beat.get("t", "?")
    headline = (beat.get("headline") or "").strip()
    sub = (beat.get("sub") or "").strip()
    duration = beat.get("duration_sec", 30)
    parts = [f"id={bid}  kind={kind}  t={t}  duration={duration}s"]
    if headline:
        parts.append(f"  headline: {headline}")
    if sub:
        parts.append(f"  sub: {sub}")
    md = beat.get("metadata") or {}
    if md:
        # Compact key facts (notional, realized_pnl, streak length…) the
        # model can quote without inventing.
        keys = (
            "notional", "realized_pnl", "streak_length", "burst_ratio",
            "winning_trades", "closed_trades", "side", "qty", "price",
        )
        bits = [f"{k}={md[k]!r}" for k in keys if k in md]
        if bits:
            parts.append("  facts: " + ", ".join(bits))
    return "\n".join(parts)


def build_user_prompt(beats: list[dict[str, Any]], *, episode_label: str | None = None) -> str:
    """Assemble the user-side prompt: header + per-beat paragraphs.
    Stable formatting so prompt caching can mark the static parts."""
    header = "Here are the beats for one trading day. Write narration for each."
    if episode_label:
        header += f"\nEpisode label (for your title cue): {episode_label}"
    body = "\n\n".join(format_beat_for_prompt(b) for b in beats)
    return f"{header}\n\nBEATS:\n{body}\n"


# ----- response parsing (pure, robust) ------------------------------------


_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _line_duration_sec(text: str) -> float:
    """Approximate spoken duration of one line at WPM_TTS_PACE."""
    words = _count_words(text)
    return round(60.0 * words / WPM_TTS_PACE, 2) if words else 0.0


def _extract_json_object(s: str) -> str:
    """Pull the first JSON object out of the model's reply.

    Robust to common preambles ("Here is the JSON:") and to fenced
    code blocks (```json … ```). Falls back to `s` unchanged so the
    JSONDecodeError downstream still surfaces the underlying problem
    if there isn't a recognisable object at all.
    """
    s = s.strip()
    # Fenced block? Pull out the content between the fences.
    fence_match = re.search(r"```(?:[a-zA-Z]+)?\s*\n(.*?)\n?```", s, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # First brace-balanced object from the first '{' onward.
    start = s.find("{")
    if start < 0:
        return s
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return s[start:]


# Kept for backwards compatibility with existing tests.
def _strip_code_fences(s: str) -> str:
    return _extract_json_object(s)


def parse_response(
    raw_text: str,
    *,
    expected_beat_ids: list[str],
) -> tuple[str, list[BeatScript]]:
    """Parse the model's JSON response into (episode_title, beats).
    Raises ValueError on any structural problem; caller may retry."""

    text = _extract_json_object(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("top-level JSON must be an object")
    title = data.get("episode_title", "").strip()[:80] or "Today on TradeFarm"
    rows = data.get("beats")
    if not isinstance(rows, list):
        raise ValueError("expected `beats` array")

    # On duplicate beat_id keep the FIRST occurrence (chronological per
    # the detector). The reverse — last-wins — meant a model that
    # repeated a beat lost the earlier draft silently.
    by_id: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid = row.get("beat_id")
        if bid is not None and bid not in by_id:
            by_id[bid] = row
    out: list[BeatScript] = []
    missing: list[str] = []
    for bid in expected_beat_ids:
        row = by_id.get(bid)
        if not row:
            missing.append(bid)
            continue
        raw_lines = row.get("lines") or []
        if not isinstance(raw_lines, list):
            raise ValueError(f"beat {bid!r}: `lines` must be a list")
        lines = []
        for ln in raw_lines:
            if not isinstance(ln, str):
                raise ValueError(f"beat {bid!r}: line must be a string")
            stripped = ln.strip()
            if not stripped:
                continue
            lines.append(
                NarrationLine(
                    text=stripped,
                    words=_count_words(stripped),
                    duration_sec=_line_duration_sec(stripped),
                )
            )
        if not lines:
            raise ValueError(f"beat {bid!r}: produced no usable lines")
        out.append(BeatScript(beat_id=bid, lines=lines))

    if missing:
        raise ValueError(
            f"response missing narration for beats: {', '.join(missing[:5])}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else "")
        )

    return title, out


# ----- model call (impure; isolated) --------------------------------------


def _import_anthropic():
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "anthropic SDK not installed. Run `uv sync` to pick it up "
            "from the project dependencies."
        ) from exc
    return AsyncAnthropic


async def _call_model(
    *,
    user_prompt: str,
    model: str,
    api_key: str | None,
    max_tokens: int,
    prior_messages: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, int]]:
    """One call; returns (text, usage_dict). Caller handles retries.

    `prior_messages` is the conversation so far (the failed assistant
    reply + a clarifying user turn) so retries actually show the model
    *its own* previous output — appending a bare error string never
    helped because the model had no view of what it produced.
    """
    AsyncAnthropic = _import_anthropic()
    client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
    messages: list[dict[str, Any]] = list(prior_messages or [])
    messages.append({"role": "user", "content": user_prompt})
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        # ephemeral cache on the (static) system prompt. Within a single
        # write_script() invocation the retry will read from cache. The
        # 5-minute TTL means cross-session reuse only happens on rapid
        # re-runs (e.g. operator iterating on a failed script).
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
    )
    # Concatenate text content blocks (only ones we expect).
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    text = "".join(parts)
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
    }
    return text, usage


# ----- top-level entry ----------------------------------------------------


async def write_script(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    episode_label: str | None = None,
) -> Script:
    """Load beats.json, ask the model for narration, parse, return
    Script. Caller decides whether to write it to disk (see
    `script_to_dict` + `write_script_file`)."""

    base = sessions_dir or Path("out/sessions")
    beats_path = base / session_id / "beats.json"
    if not beats_path.is_file():
        raise FileNotFoundError(f"beats.json not found: {beats_path}")
    beats_raw = json.loads(beats_path.read_text(encoding="utf-8"))
    if not isinstance(beats_raw, list) or not beats_raw:
        raise ValueError(f"empty or malformed beats.json: {beats_path}")

    expected_ids = [str(b["id"]) for b in beats_raw if "id" in b]
    if not expected_ids:
        raise ValueError("beats have no `id` field")

    if episode_label is None:
        manifest_path = base / session_id / "manifest.json"
        if manifest_path.is_file():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                episode_label = m.get("session_id") or session_id
            except (OSError, json.JSONDecodeError):
                episode_label = session_id
        else:
            episode_label = session_id

    # Filter out beats without ids BEFORE building the prompt — otherwise
    # the model sees ghost entries it has no way to label coherently.
    beats_for_prompt = [b for b in beats_raw if "id" in b]
    user_prompt = build_user_prompt(beats_for_prompt, episode_label=episode_label)

    # Precheck the API key so we fail fast with a clear message instead
    # of bottoming out in the SDK's "Could not resolve auth" trace.
    resolved_key = api_key or (settings.anthropic_api_key or None)
    if not resolved_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to .env or pass api_key= explicitly."
        )

    accumulated_usage = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }
    title = "Today on TradeFarm"
    beats: list[BeatScript] = []
    # Conversation we'll grow across retries: previous assistant reply +
    # one corrective user turn each iteration.
    prior_messages: list[dict[str, Any]] = []
    next_user = user_prompt
    for attempt in range(max_retries + 1):
        # `last_text` carries the most recent assistant reply (if any),
        # so a parse failure on attempt N can show it back to the model
        # on attempt N+1. Network failures leave it unset.
        last_text: str | None = None
        try:
            last_text, usage = await _call_model(
                user_prompt=next_user,
                model=model,
                api_key=resolved_key,
                max_tokens=max_tokens,
                prior_messages=prior_messages,
            )
            for k, v in usage.items():
                accumulated_usage[k] += v
            title, beats = parse_response(last_text, expected_beat_ids=expected_ids)
            break
        except (ValueError, RuntimeError) as exc:
            if attempt >= max_retries:
                err = RuntimeError(
                    f"script writer failed after {attempt + 1} attempts: {exc}"
                )
                # Carry usage through the failure so callers / cost
                # tracking still see what they paid for.
                err.usage = accumulated_usage  # type: ignore[attr-defined]
                raise err from exc
            # Build the next turn: previous user prompt + the assistant
            # reply we just got (if any) + a corrective user turn that
            # quotes the validation failure. The model now sees its own
            # output and the specific complaint.
            prior_messages.append({"role": "user", "content": next_user})
            if last_text is not None:
                prior_messages.append({"role": "assistant", "content": last_text})
            next_user = (
                f"Your previous reply did not validate: {exc}\n"
                "Reply with ONLY the JSON object — no prose, no code fences. "
                "Keep the same beat ids and order."
            )

    return Script(
        session_id=session_id,
        episode_title=title,
        model=model,
        beats=beats,
        usage=accumulated_usage,
    )


# ----- I/O helpers --------------------------------------------------------


def script_to_dict(script: Script) -> dict[str, Any]:
    return {
        "session_id": script.session_id,
        "episode_title": script.episode_title,
        "model": script.model,
        "usage": script.usage,
        "total_words": sum(ln.words for b in script.beats for ln in b.lines),
        "total_duration_sec": round(
            sum(ln.duration_sec for b in script.beats for ln in b.lines), 2
        ),
        "beats": [
            {
                "beat_id": b.beat_id,
                "lines": [
                    {
                        "text": ln.text,
                        "words": ln.words,
                        "duration_sec": ln.duration_sec,
                    }
                    for ln in b.lines
                ],
            }
            for b in script.beats
        ],
    }


def write_script_file(script: Script, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(script_to_dict(script), indent=2), encoding="utf-8")


# ----- CLI ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """`python -m tradefarm.script.write <session_id>` reads beats.json,
    asks Claude for narration, writes script.json next to it."""

    parser = argparse.ArgumentParser(
        prog="tradefarm.script.write",
        description="Generate per-beat narration with Claude.",
    )
    parser.add_argument("session_id", help="Session id (matches out/sessions/<session_id>/).")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Max tokens for the response.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Re-prompt budget on parse failure.",
    )
    parser.add_argument(
        "--episode-label",
        default=None,
        help="Override for the title hint passed to the model.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt without calling the API.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        sessions_dir = args.out
        beats_path = sessions_dir / args.session_id / "beats.json"
        if not beats_path.is_file():
            raise SystemExit(f"beats.json not found: {beats_path}")
        beats = json.loads(beats_path.read_text(encoding="utf-8"))
        print(build_user_prompt(beats, episode_label=args.episode_label or args.session_id))
        return

    try:
        script = asyncio.run(
            write_script(
                args.session_id,
                sessions_dir=args.out,
                model=args.model,
                max_tokens=args.max_tokens,
                max_retries=args.max_retries,
                episode_label=args.episode_label,
            )
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"missing input: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"bad input: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(f"script writer failed: {exc}") from exc
    out_path = args.out / args.session_id / "script.json"
    write_script_file(script, out_path)

    total_words = sum(ln.words for b in script.beats for ln in b.lines)
    total_sec = sum(ln.duration_sec for b in script.beats for ln in b.lines)
    print(
        f"session_id={script.session_id}\n"
        f"script={out_path}\n"
        f"beats={len(script.beats)} words={total_words} "
        f"est_speech_sec={total_sec:.1f}\n"
        f"usage in={script.usage['input_tokens']} "
        f"out={script.usage['output_tokens']} "
        f"cache_read={script.usage['cache_read_input_tokens']}"
    )


if __name__ == "__main__":
    main()
