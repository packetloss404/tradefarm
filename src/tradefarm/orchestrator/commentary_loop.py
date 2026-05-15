"""Live LLM commentary — Bloomberg-style one-liners every ~45s.

Polls the Orchestrator every ``poll_interval_sec`` seconds and asks the active
LLM provider to write ONE short sentence about the current state of the farm
(top P&L agents, recent fills, SPY drift, provider name). The result is
published as ``stream_commentary`` for the broadcast app to render.

Failure modes:
- LLM call raises             → emit a fallback caption from a small pool
                                 (``source="fallback"``).
- LLM response unparseable    → fallback (same).
- Nothing interesting to say  → skip the tick entirely (cost gate).

The trading agents' SYSTEM_PROMPT is NOT reused — commentary needs a different
contract (return ``{"text", "kind"}``, not a trade decision). We talk directly
to the provider's underlying client so we can swap the prompt + parser without
touching the trade-decision path. ``AnthropicProvider.client`` and
``MinimaxProvider.api_key/base_url`` are the interfaces this module assumes.
"""
from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import httpx
import structlog

from tradefarm.agents.llm_overlay import LlmOverlay
from tradefarm.agents.llm_providers import (
    AnthropicProvider,
    LlmProvider,
    MinimaxProvider,
)
from tradefarm.api.events import publish_event
from tradefarm.config import settings

if TYPE_CHECKING:
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()

POLL_INTERVAL_SEC: float = 45.0
MARKET_SYMBOL: str = "SPY"
SPY_QUIET_PCT: float = 0.003  # 0.3% — below this with zero fills, skip the tick.
MAX_TEXT_CHARS: int = 140
TOP_N_AGENTS: int = 5
RECENT_FILLS: int = 5

CommentaryKind = Literal["color", "play_by_play"]

COMMENTARY_SYSTEM_PROMPT = """You are a Bloomberg-style market commentator narrating a 100-agent AI paper-trading stream live on air.

Given the recent state below, write ONE short sentence (<= 140 chars) that a TV commentator would say live. Vary your style: sometimes a play-by-play of a specific fill, sometimes a color comment about the market mood. Be specific when possible (name agents, name symbols, name moves). No hedging, no preamble, no quotes around the sentence.

Respond with JSON only, exactly this shape:
{"text": "<one sentence, <=140 chars>", "kind": "play_by_play" | "color"}

Pick "play_by_play" when narrating a specific fill/event, "color" for ambient observation."""

# Fallback pool, keyed on the dominant state signal. Picked deterministically
# from a small bucket so the stream still moves when the LLM is down.
_FALLBACK_QUIET: tuple[str, ...] = (
    "Quiet tape — agents on the sidelines, waiting for a setup.",
    "Lull across the farm. No new prints, just patience.",
    "Slow grind. Models in observe-mode while the tape consolidates.",
)
_FALLBACK_ACTIVE: tuple[str, ...] = (
    "Fills printing across the farm — agents working the order book.",
    "Order flow picking up. Multiple strategies engaging at once.",
    "Activity heating up — the LSTM cohort is leaning in.",
)
_FALLBACK_SPY_UP: tuple[str, ...] = (
    "SPY catching a bid — risk-on tone setting the table.",
    "Tape lifting. Agents tilting long into the move.",
)
_FALLBACK_SPY_DOWN: tuple[str, ...] = (
    "SPY giving it back — defensive postures coming on.",
    "Selling pressure on SPY. Stops getting tested.",
)


@dataclass
class _AgentSnap:
    id: int
    name: str
    strategy: str
    symbol: str | None
    pnl: float
    pnl_pct: float


@dataclass
class _FillSnap:
    agent_name: str
    side: str
    qty: float
    symbol: str
    price: float


@dataclass
class _StateSnapshot:
    top_agents: list[_AgentSnap]
    recent_fills: list[_FillSnap]
    spy_mark: float | None
    spy_pct: float  # vs. session baseline; 0.0 if baseline not yet set.
    provider_name: str


@dataclass
class CommentaryLoop:
    """Periodically asks the active LLM provider for a single-sentence take.

    Started/stopped from :class:`Orchestrator` alongside AutoDirector.
    """

    orch: "Orchestrator"
    poll_interval_sec: float = POLL_INTERVAL_SEC

    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)
    _spy_baseline: float | None = field(default=None, init=False, repr=False)
    _last_fill_keys: tuple[str, ...] = field(default=(), init=False, repr=False)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="orch_commentary_loop")
        log.info("commentary_loop_started", interval_sec=self.poll_interval_sec)

    async def stop(self) -> None:
        self._stopped = True
        t = self._task
        if t is None:
            return
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("commentary_loop_failed", error=str(e))
            await asyncio.sleep(self.poll_interval_sec)

    # ------------------------------------------------------------------
    # Snapshot & cost gate.
    # ------------------------------------------------------------------

    def _snapshot(self) -> _StateSnapshot:
        marks = self.orch.last_marks
        starting = settings.agent_starting_capital

        agent_snaps: list[_AgentSnap] = []
        for a in self.orch.agents:
            book = getattr(a.state, "book", None)
            if book is None or starting <= 0:
                continue
            equity = book.equity(marks)
            pnl = equity - starting
            pct = pnl / starting if starting > 0 else 0.0
            agent_snaps.append(
                _AgentSnap(
                    id=a.state.id,
                    name=a.state.name,
                    strategy=a.state.strategy,
                    symbol=getattr(a, "symbol", None),
                    pnl=pnl,
                    pnl_pct=pct,
                )
            )
        agent_snaps.sort(key=lambda s: s.pnl, reverse=True)
        top = agent_snaps[:TOP_N_AGENTS]

        # Recent fills: there's no fill-buffer on the orchestrator itself, so
        # we surface "recent activity" by reading each agent's open positions
        # / most-recent fill metadata. The cheapest signal is "did any agent
        # transact since we last looked" — we use the optimistic-marks dict
        # the scheduler populates at submit time as a coarse proxy.
        recent = self._recent_fills_from_orch()

        spy_mark = marks.get(MARKET_SYMBOL)
        if self._spy_baseline is None and spy_mark is not None and spy_mark > 0:
            self._spy_baseline = spy_mark
        spy_pct = 0.0
        if spy_mark is not None and self._spy_baseline:
            spy_pct = (spy_mark - self._spy_baseline) / self._spy_baseline

        provider_name = settings.llm_provider
        return _StateSnapshot(
            top_agents=top,
            recent_fills=recent,
            spy_mark=spy_mark,
            spy_pct=spy_pct,
            provider_name=provider_name,
        )

    def _recent_fills_from_orch(self) -> list[_FillSnap]:
        """Best-effort recent-fill listing pulled from agent positions.

        We snapshot each agent's largest currently-open position as a stand-in
        for "recent activity". This avoids adding a fill ring buffer to the
        Orchestrator just for commentary. The list is capped at RECENT_FILLS.
        """
        out: list[_FillSnap] = []
        marks = self.orch.last_marks
        for agent in self.orch.agents:
            book = getattr(agent.state, "book", None)
            if book is None:
                continue
            for sym, pos in book.positions.items():
                if pos.qty <= 0:
                    continue
                out.append(
                    _FillSnap(
                        agent_name=agent.state.name,
                        side="long",
                        qty=float(pos.qty),
                        symbol=sym,
                        price=float(marks.get(sym, pos.avg_price)),
                    )
                )
        # Heaviest notional first; keep top N.
        out.sort(key=lambda f: f.qty * f.price, reverse=True)
        return out[:RECENT_FILLS]

    @staticmethod
    def _is_quiet(snap: _StateSnapshot) -> bool:
        return len(snap.recent_fills) == 0 and abs(snap.spy_pct) < SPY_QUIET_PCT

    # ------------------------------------------------------------------
    # Prompt assembly + LLM call.
    # ------------------------------------------------------------------

    def _user_message(self, snap: _StateSnapshot) -> str:
        lines: list[str] = []
        lines.append(f"Active LLM provider: {snap.provider_name}")
        if snap.spy_mark is not None:
            lines.append(
                f"SPY: ${snap.spy_mark:.2f} ({snap.spy_pct * 100:+.2f}% vs session baseline)"
            )
        else:
            lines.append("SPY: no mark yet")

        if snap.top_agents:
            lines.append("Top agents by P&L today:")
            for a in snap.top_agents:
                sym = f" {a.symbol}" if a.symbol else ""
                lines.append(
                    f"- {a.name} ({a.strategy}{sym}): "
                    f"{a.pnl_pct * 100:+.2f}% (${a.pnl:+.2f})"
                )
        else:
            lines.append("No agent P&L data yet.")

        if snap.recent_fills:
            lines.append("Recent open positions (heaviest notional):")
            for f in snap.recent_fills:
                lines.append(
                    f"- {f.agent_name} {f.side} {f.qty:g} {f.symbol} @ ${f.price:.2f}"
                )
        else:
            lines.append("No open positions across the farm.")

        lines.append("")
        lines.append("Return the JSON now.")
        return "\n".join(lines)

    async def _call_llm(self, snap: _StateSnapshot) -> tuple[str, CommentaryKind]:
        """Call the active provider with the commentary prompt.

        Returns (text, kind). Raises if the call or parse fails — the caller
        catches and falls back.
        """
        overlay = LlmOverlay.from_settings()
        provider = overlay.provider
        user = self._user_message(snap)
        # 20s hard cap so a hung provider can't stall the 45s loop indefinitely.
        # MinimaxProvider already uses httpx with its own timeout; this also
        # protects the Anthropic SDK path which has no override.
        raw = await asyncio.wait_for(_commentary_completion(provider, user), timeout=20.0)
        return _parse_commentary_json(raw)

    # ------------------------------------------------------------------
    # Main tick.
    # ------------------------------------------------------------------

    async def tick_once(self) -> dict[str, Any] | None:
        """Run one commentary cycle. Returns the published payload, or None
        if cost-gated (nothing interesting to say).
        """
        snap = self._snapshot()
        if self._is_quiet(snap):
            log.debug(
                "commentary_skip_quiet",
                fills=len(snap.recent_fills),
                spy_pct=snap.spy_pct,
            )
            return None

        text: str
        kind: CommentaryKind
        source: Literal["llm", "fallback"]
        try:
            text, kind = await self._call_llm(snap)
            source = "llm"
        except Exception as e:
            log.warning(
                "commentary_llm_failed",
                error=str(e),
                provider=snap.provider_name,
            )
            text, kind = _fallback_for(snap)
            source = "fallback"

        text = _truncate(text, MAX_TEXT_CHARS)
        if not text:
            # Defensive: empty text means malformed LLM output; pick a fallback.
            text, kind = _fallback_for(snap)
            source = "fallback"

        self._counter += 1
        commentary_id = f"commentary-{self._counter}"
        payload = {
            "id": commentary_id,
            "text": text,
            "kind": kind,
            "source": source,
        }
        await publish_event("stream_commentary", payload)
        log.info("commentary_emit", source=source, kind=kind, text=text)
        return payload


# ---------------------------------------------------------------------------
# Provider-specific commentary completion.
#
# We can't reuse provider.decide() — that wraps the trade-decision SYSTEM_PROMPT
# and parses a different schema. So we re-do the minimum needed for the
# commentary prompt against the same underlying API client.
# ---------------------------------------------------------------------------


async def _commentary_completion(provider: LlmProvider, user_message: str) -> str:
    if isinstance(provider, AnthropicProvider):
        msg = await provider.client.messages.create(
            model=provider.model,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": COMMENTARY_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )
    if isinstance(provider, MinimaxProvider):
        url = f"{provider.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": provider.model,
            "max_tokens": 200,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": COMMENTARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"]
    raise RuntimeError(f"unsupported llm provider for commentary: {type(provider).__name__}")


def _parse_commentary_json(raw: str) -> tuple[str, CommentaryKind]:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    data = json.loads(s)
    text = str(data.get("text", "")).strip()
    kind_raw = str(data.get("kind", "color")).strip().lower()
    kind: CommentaryKind = "play_by_play" if kind_raw == "play_by_play" else "color"
    if not text:
        raise ValueError("commentary text is empty")
    return text, kind


def _truncate(text: str, limit: int) -> str:
    t = text.strip().strip('"').strip("'")
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _fallback_for(snap: _StateSnapshot) -> tuple[str, CommentaryKind]:
    """Pick a fallback caption based on the dominant state."""
    if snap.spy_pct >= 0.005:
        return random.choice(_FALLBACK_SPY_UP), "color"
    if snap.spy_pct <= -0.005:
        return random.choice(_FALLBACK_SPY_DOWN), "color"
    if len(snap.recent_fills) >= 3:
        return random.choice(_FALLBACK_ACTIVE), "color"
    return random.choice(_FALLBACK_QUIET), "color"
