"""Session beat detector — turns a manifest into a ranked list of dramatic
moments for the VOD pipeline.

Input:  out/sessions/<id>/manifest.json  (written by tradefarm.session.run)
Output: out/sessions/<id>/beats.json     (a list of `Beat` records)

The detector is pure: a function of the manifest contents plus a few
tunable thresholds. No DB reads, no clock — that's deliberate so the
detector can be re-run on any historical session without side effects,
and so tests can synthesize manifests inline.

What's in the manifest today (per session/run.py):
    fill events    — {symbol, side, qty, price, notional, reason}
    decision events — {kind: "entry"|"exit", symbol, content, metadata}

That's a thin substrate. v0 ships eight beat kinds that can be scored
from fills alone (plus the entry/exit pairing in decisions):

    open            — fixed bookend at session start
    big_fill        — single fill above a notional threshold
    divergence      — opposite sides on the same symbol, two agents,
                       inside a tight time window
    streak          — agent with N consecutive winning exit pairs
    top_winner      — agent with highest realized PnL on the day
    top_loser       — agent with worst realized PnL on the day
    closing_burst   — fill density spike in the last 10 minutes
    recap           — fixed bookend at session close

Beat kinds the prototype shows but v0 cannot score (data not in the
manifest today): near_miss (needs LSTM probs as events), chapter_change
(needs market data), promotion (not emitted), llm_bet (decision metadata
is a free-form string), agent_rivalry / leaderboard_shift (need
multi-session history). They land in v1 once the runner emits more.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


# ----- tunables --------------------------------------------------------------


# All thresholds live here so they're easy to discover and override per
# session via the DetectorThresholds dataclass.
@dataclass(frozen=True)
class DetectorThresholds:
    big_fill_notional_full: float = 10_000.0
    big_fill_notional_min: float = 5_000.0
    divergence_window_sec: float = 60.0
    streak_min_length: int = 4
    streak_full_length: int = 8
    top_winner_full_pnl: float = 500.0
    top_loser_full_pnl: float = 200.0
    closing_burst_window_min: float = 10.0
    closing_burst_min_ratio: float = 2.0
    dedup_window_sec: float = 120.0
    target_min_beats: int = 8
    target_max_beats: int = 15


# ----- record types ---------------------------------------------------------


@dataclass(frozen=True)
class Beat:
    """One detected dramatic moment.

    `event_refs` is a list of integer indices into manifest.events so the
    downstream renderer can pull the original payloads back. `agent_ids`
    is denormalized for the scene-template's convenience. `metadata`
    holds kind-specific scoring inputs (notional, pnl, streak length)
    so a debug UI can show why a beat scored what it scored.
    """

    id: str
    t: str
    kind: str
    score: float
    scene_hint: str
    headline: str
    sub: str
    duration_sec: int
    event_refs: list[int] = field(default_factory=list)
    agent_ids: list[int] = field(default_factory=list)
    symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Default scene per kind. Match the studio's BEAT_KIND_META so the
# Beat Picker preview pane picks the right vignette.
SCENE_FOR_KIND: dict[str, str] = {
    "open": "hero",
    "big_fill": "hero",
    "divergence": "brain",
    "streak": "leaderboard",
    "top_winner": "hero",
    "top_loser": "hero",
    "closing_burst": "hero",
    "recap": "recap",
}

# Default duration per kind (seconds). Tuned to keep total reel around
# 8-12 minutes when ~10 beats fire.
DURATION_FOR_KIND: dict[str, int] = {
    "open": 12,
    "big_fill": 30,
    "divergence": 28,
    "streak": 26,
    "top_winner": 32,
    "top_loser": 26,
    "closing_burst": 22,
    "recap": 36,
}

# Tiebreaker when scores are equal: higher = preferred. Mirrors the
# operator's mental priority — disagreement is more interesting than a
# single big number, single-agent stories beat aggregate ones.
KIND_PRIORITY: dict[str, int] = {
    "divergence": 6,
    "top_winner": 5,
    "top_loser": 4,
    "streak": 3,
    "big_fill": 2,
    "closing_burst": 1,
    "open": 99,  # always pinned first
    "recap": 99,  # always pinned last
}


# ----- helpers --------------------------------------------------------------


def _parse_iso(ts: str) -> datetime:
    """Manifest timestamps are ISO-8601 with timezone. Cope with the
    trailing "Z" form too — older runs may have used it."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _format_money(n: float, *, signed: bool = False) -> str:
    sign = "+" if signed and n >= 0 else "-" if signed and n < 0 else ""
    return f"{sign}${abs(n):,.0f}"


@dataclass
class _Fill:
    """Internal view of a fill event with indices and parsed time."""

    idx: int
    t: datetime
    agent_id: int
    agent_name: str
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    price: float
    notional: float


def _fills(manifest: dict[str, Any]) -> list[_Fill]:
    out: list[_Fill] = []
    for idx, ev in enumerate(manifest.get("events", [])):
        if ev.get("kind") != "fill":
            continue
        p = ev.get("payload") or {}
        try:
            t = _parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        agent_id = ev.get("agent_id")
        if agent_id is None:
            continue
        out.append(
            _Fill(
                idx=idx,
                t=t,
                agent_id=int(agent_id),
                agent_name=str(ev.get("agent_name") or f"agent_{agent_id}"),
                symbol=str(p.get("symbol") or ""),
                side=str(p.get("side") or "").lower(),
                qty=float(p.get("qty") or 0.0),
                price=float(p.get("price") or 0.0),
                notional=float(
                    p.get("notional") or abs(float(p.get("qty") or 0) * float(p.get("price") or 0))
                ),
            )
        )
    return out


def _hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


# ----- per-agent realized PnL from fills ------------------------------------


@dataclass
class _AgentPnl:
    realized: float = 0.0
    closed_trades: int = 0
    winning_trades: int = 0
    longest_win_streak: int = 0
    last_close_t: datetime | None = None


def _agent_pnl_from_fills(fills: list[_Fill]) -> dict[int, _AgentPnl]:
    """Reconstruct realized PnL per agent by walking fills in order.

    Average-cost accounting per (agent, symbol). A fill that reduces an
    existing position realizes `(price - avg_cost) * closed_qty` for
    longs and `(avg_cost - price) * closed_qty` for shorts. Increasing
    a position just updates the running average.

    This isn't perfect — partial closes that flip sign count as two
    half-trades for streak purposes — but it's plenty for "who had the
    best day from the fills we observed."
    """

    # state[(agent_id, symbol)] = (signed_qty, avg_cost)
    state: dict[tuple[int, str], tuple[float, float]] = {}
    out: dict[int, _AgentPnl] = {}

    def _bump(agent_id: int) -> _AgentPnl:
        if agent_id not in out:
            out[agent_id] = _AgentPnl()
        return out[agent_id]

    # Track current run-length per agent so we can compute longest streak
    # even though we only mutate on closes.
    cur_streak: dict[int, int] = {}

    fills_sorted = sorted(fills, key=lambda f: f.t)
    for f in fills_sorted:
        key = (f.agent_id, f.symbol)
        cur_qty, cur_avg = state.get(key, (0.0, 0.0))
        signed_fill = f.qty if f.side == "buy" else -f.qty
        if cur_qty == 0 or (cur_qty > 0 and signed_fill > 0) or (cur_qty < 0 and signed_fill < 0):
            # Opening or adding — update average cost only.
            new_qty = cur_qty + signed_fill
            new_avg = (
                ((abs(cur_qty) * cur_avg) + (abs(signed_fill) * f.price)) / abs(new_qty)
                if new_qty != 0
                else 0.0
            )
            state[key] = (new_qty, new_avg)
            continue
        # Reducing or flipping. Compute realized on the closed portion.
        closing_qty = min(abs(signed_fill), abs(cur_qty))
        if cur_qty > 0:
            realized = (f.price - cur_avg) * closing_qty
        else:
            realized = (cur_avg - f.price) * closing_qty
        agg = _bump(f.agent_id)
        agg.realized += realized
        agg.closed_trades += 1
        agg.last_close_t = f.t
        if realized > 0:
            agg.winning_trades += 1
            cur_streak[f.agent_id] = cur_streak.get(f.agent_id, 0) + 1
            agg.longest_win_streak = max(agg.longest_win_streak, cur_streak[f.agent_id])
        else:
            cur_streak[f.agent_id] = 0

        # Update remaining position.
        remaining = abs(signed_fill) - closing_qty
        if remaining == 0:
            new_qty = cur_qty + signed_fill
            if new_qty == 0:
                state.pop(key, None)
            else:
                state[key] = (new_qty, cur_avg)
        else:
            # Fully flipped: residual opens a new position at fill price.
            new_qty = -1.0 * (cur_qty / abs(cur_qty)) * remaining
            state[key] = (new_qty, f.price)

    return out


# ----- scorers --------------------------------------------------------------


def _score_open(manifest: dict[str, Any]) -> Beat | None:
    """Fixed bookend at session start. Always score 0.55 so it survives
    selection but doesn't crowd out the day's actual drama."""

    started = manifest.get("started_at")
    if not started:
        return None
    t = _parse_iso(started)
    agents = manifest.get("agents_active") or 0
    days = manifest.get("trading_days") or [t.date().isoformat()]
    day = days[0]
    return Beat(
        id="b_open",
        t=t.isoformat(),
        kind="open",
        score=0.55,
        scene_hint=SCENE_FOR_KIND["open"],
        headline=f"Market open · {agents} agents back at their desks",
        sub=f"Session {day} · {len(days)} trading day{'s' if len(days) != 1 else ''}",
        duration_sec=DURATION_FOR_KIND["open"],
        event_refs=[],
        agent_ids=[],
        symbol=None,
        metadata={"agents_active": agents, "trading_days": days},
    )


def _score_big_fills(fills: list[_Fill], th: DetectorThresholds) -> list[Beat]:
    """One beat per fill above the min threshold. Score scales linearly
    from 0 at min_notional to 1 at full_notional."""

    out: list[Beat] = []
    span = max(1.0, th.big_fill_notional_full - th.big_fill_notional_min)
    for f in fills:
        if f.notional < th.big_fill_notional_min:
            continue
        score = _clamp((f.notional - th.big_fill_notional_min) / span)
        side_word = "goes long" if f.side == "buy" else "goes short"
        out.append(
            Beat(
                id=f"b_bigfill_{f.idx}",
                t=f.t.isoformat(),
                kind="big_fill",
                score=score,
                scene_hint=SCENE_FOR_KIND["big_fill"],
                headline=f"{f.agent_name} {side_word} {f.symbol} — {_format_money(f.notional)} notional",
                sub=f"{f.qty:g} × ${f.price:,.2f} · {_hhmm(f.t)} ET",
                duration_sec=DURATION_FOR_KIND["big_fill"],
                event_refs=[f.idx],
                agent_ids=[f.agent_id],
                symbol=f.symbol,
                metadata={"notional": f.notional, "side": f.side, "qty": f.qty, "price": f.price},
            )
        )
    return out


def _score_divergence(fills: list[_Fill], th: DetectorThresholds) -> list[Beat]:
    """Two agents take opposite sides on the same symbol inside a tight
    window. Score blends overlap (smaller notional bounds the
    disagreement) and how recent the pairing was."""

    out: list[Beat] = []
    by_symbol: dict[str, list[_Fill]] = {}
    for f in fills:
        if not f.symbol or f.side not in ("buy", "sell"):
            continue
        by_symbol.setdefault(f.symbol, []).append(f)

    window = timedelta(seconds=th.divergence_window_sec)
    seen: set[tuple[int, ...]] = set()
    for sym, group in by_symbol.items():
        group_sorted = sorted(group, key=lambda f: f.t)
        for i, a in enumerate(group_sorted):
            for b in group_sorted[i + 1 :]:
                if b.t - a.t > window:
                    break
                if a.agent_id == b.agent_id or a.side == b.side:
                    continue
                key = tuple(sorted((a.agent_id, b.agent_id)) + sorted((a.idx, b.idx)))
                if key in seen:
                    continue
                seen.add(key)
                overlap = min(a.notional, b.notional)
                score = _clamp(0.45 + (overlap / 10_000.0) * 0.4)
                buyer = a if a.side == "buy" else b
                seller = a if a.side == "sell" else b
                out.append(
                    Beat(
                        id=f"b_div_{a.idx}_{b.idx}",
                        t=a.t.isoformat(),
                        kind="divergence",
                        score=score,
                        scene_hint=SCENE_FOR_KIND["divergence"],
                        headline=f"{buyer.agent_name} buys {sym}, {seller.agent_name} sells — same minute",
                        sub=(
                            f"{_format_money(buyer.notional)} long vs "
                            f"{_format_money(seller.notional)} short · "
                            f"{_hhmm(a.t)} ET"
                        ),
                        duration_sec=DURATION_FOR_KIND["divergence"],
                        event_refs=[a.idx, b.idx],
                        agent_ids=[buyer.agent_id, seller.agent_id],
                        symbol=sym,
                        metadata={
                            "buyer_notional": buyer.notional,
                            "seller_notional": seller.notional,
                            "gap_sec": (b.t - a.t).total_seconds(),
                        },
                    )
                )
    return out


def _score_streaks(
    fills: list[_Fill],
    pnls: dict[int, _AgentPnl],
    th: DetectorThresholds,
) -> list[Beat]:
    out: list[Beat] = []
    last_fill_by_agent: dict[int, _Fill] = {}
    for f in fills:
        last_fill_by_agent[f.agent_id] = f
    for agent_id, agg in pnls.items():
        if agg.longest_win_streak < th.streak_min_length:
            continue
        last = last_fill_by_agent.get(agent_id)
        if last is None:
            continue
        denom = max(1, th.streak_full_length - th.streak_min_length)
        score = _clamp((agg.longest_win_streak - th.streak_min_length) / denom * 0.7 + 0.3)
        out.append(
            Beat(
                id=f"b_streak_{agent_id}",
                t=(agg.last_close_t or last.t).isoformat(),
                kind="streak",
                score=score,
                scene_hint=SCENE_FOR_KIND["streak"],
                headline=f"{last.agent_name}: {agg.longest_win_streak} winners in a row",
                sub=(
                    f"{agg.winning_trades}/{agg.closed_trades} W today · "
                    f"realized {_format_money(agg.realized, signed=True)}"
                ),
                duration_sec=DURATION_FOR_KIND["streak"],
                event_refs=[last.idx],
                agent_ids=[agent_id],
                symbol=last.symbol,
                metadata={
                    "streak_length": agg.longest_win_streak,
                    "closed_trades": agg.closed_trades,
                    "winning_trades": agg.winning_trades,
                    "realized_pnl": agg.realized,
                },
            )
        )
    return out


def _score_top_movers(
    fills: list[_Fill],
    pnls: dict[int, _AgentPnl],
    th: DetectorThresholds,
) -> list[Beat]:
    if not pnls:
        return []
    last_fill_by_agent: dict[int, _Fill] = {}
    for f in fills:
        last_fill_by_agent[f.agent_id] = f
    ranked = sorted(pnls.items(), key=lambda kv: kv[1].realized, reverse=True)
    out: list[Beat] = []
    top_id, top = ranked[0]
    if top.realized > 0 and top.closed_trades > 0:
        last = last_fill_by_agent.get(top_id)
        score = _clamp(top.realized / th.top_winner_full_pnl)
        if score > 0:
            out.append(
                Beat(
                    id=f"b_topwinner_{top_id}",
                    t=(
                        top.last_close_t
                        or (last.t if last else None)
                        or _parse_iso(fills[-1].t.isoformat())
                    ).isoformat(),
                    kind="top_winner",
                    score=score,
                    scene_hint=SCENE_FOR_KIND["top_winner"],
                    headline=(
                        f"{(last.agent_name if last else f'agent_{top_id}')} "
                        f"leads the day {_format_money(top.realized, signed=True)}"
                    ),
                    sub=f"{top.winning_trades}/{top.closed_trades} W · best realized PnL on the day",
                    duration_sec=DURATION_FOR_KIND["top_winner"],
                    event_refs=[last.idx] if last else [],
                    agent_ids=[top_id],
                    symbol=last.symbol if last else None,
                    metadata={
                        "realized_pnl": top.realized,
                        "closed_trades": top.closed_trades,
                        "winning_trades": top.winning_trades,
                    },
                )
            )
    bot_id, bot = ranked[-1]
    if bot_id != top_id and bot.realized < 0 and bot.closed_trades > 0:
        last = last_fill_by_agent.get(bot_id)
        score = _clamp(abs(bot.realized) / th.top_loser_full_pnl)
        if score > 0:
            out.append(
                Beat(
                    id=f"b_toploser_{bot_id}",
                    t=(
                        bot.last_close_t
                        or (last.t if last else None)
                        or _parse_iso(fills[-1].t.isoformat())
                    ).isoformat(),
                    kind="top_loser",
                    score=score,
                    scene_hint=SCENE_FOR_KIND["top_loser"],
                    headline=(
                        f"{(last.agent_name if last else f'agent_{bot_id}')} "
                        f"takes the day's biggest hit {_format_money(bot.realized, signed=True)}"
                    ),
                    sub=f"{bot.winning_trades}/{bot.closed_trades} W · worst realized PnL on the day",
                    duration_sec=DURATION_FOR_KIND["top_loser"],
                    event_refs=[last.idx] if last else [],
                    agent_ids=[bot_id],
                    symbol=last.symbol if last else None,
                    metadata={
                        "realized_pnl": bot.realized,
                        "closed_trades": bot.closed_trades,
                        "winning_trades": bot.winning_trades,
                    },
                )
            )
    return out


def _score_closing_burst(fills: list[_Fill], th: DetectorThresholds) -> Beat | None:
    if not fills:
        return None
    fills_sorted = sorted(fills, key=lambda f: f.t)
    last_t = fills_sorted[-1].t
    first_t = fills_sorted[0].t
    span_sec = max(1.0, (last_t - first_t).total_seconds())
    avg_per_min = len(fills) / (span_sec / 60.0)
    window_start = last_t - timedelta(minutes=th.closing_burst_window_min)
    in_window = [f for f in fills_sorted if f.t >= window_start]
    if len(in_window) < 4 or avg_per_min == 0:
        return None
    burst_per_min = len(in_window) / th.closing_burst_window_min
    ratio = burst_per_min / avg_per_min
    if ratio < th.closing_burst_min_ratio:
        return None
    score = _clamp(0.4 + (ratio - th.closing_burst_min_ratio) * 0.15)
    return Beat(
        id="b_closingburst",
        t=window_start.isoformat(),
        kind="closing_burst",
        score=score,
        scene_hint=SCENE_FOR_KIND["closing_burst"],
        headline=(
            f"Closing rush · {len(in_window)} fills in last "
            f"{int(th.closing_burst_window_min)} minutes"
        ),
        sub=f"{ratio:.1f}× session average fill rate",
        duration_sec=DURATION_FOR_KIND["closing_burst"],
        event_refs=[f.idx for f in in_window],
        agent_ids=sorted({f.agent_id for f in in_window}),
        symbol=None,
        metadata={"fill_count": len(in_window), "burst_ratio": ratio},
    )


def _score_recap(
    manifest: dict[str, Any],
    pnls: dict[int, _AgentPnl],
    fills: list[_Fill],
) -> Beat | None:
    ended = manifest.get("ended_at")
    if not ended:
        return None
    fill_count = manifest.get("fill_count", len(fills))
    # Weekend / no-trades day: no recap (nothing to summarize). The open
    # beat alone is enough to represent the day.
    if fill_count == 0 and not fills:
        return None
    t = _parse_iso(ended)
    total_realized = sum(p.realized for p in pnls.values())
    score = _clamp(0.6 + abs(total_realized) / 5000.0 * 0.4)
    headline = f"Close · {fill_count} fills · realized {_format_money(total_realized, signed=True)}"
    return Beat(
        id="b_recap",
        t=t.isoformat(),
        kind="recap",
        score=score,
        scene_hint=SCENE_FOR_KIND["recap"],
        headline=headline,
        sub=f"{len(pnls)} agents booked trades · {manifest.get('tick_count', 0)} ticks replayed",
        duration_sec=DURATION_FOR_KIND["recap"],
        event_refs=[],
        agent_ids=[],
        symbol=None,
        metadata={"realized_pnl": total_realized, "fill_count": fill_count},
    )


# ----- dedup + selection ----------------------------------------------------


def _dedup(beats: list[Beat], th: DetectorThresholds) -> list[Beat]:
    """Collapse beats that target the same (kind, agent, symbol) inside
    a short window. Keeps the higher-scoring beat.

    Dedup is intentionally *within-kind only*. A streak and a top_winner
    on the same agent in the same minute are different narrative angles
    ("on a run" vs "winning the day") and both should be allowed to
    surface. Two big_fills 30 seconds apart on the same symbol by the
    same agent, however, are clearly the same moment — keep the bigger.

    Anchors (open / recap) bypass dedup entirely.
    """

    window = timedelta(seconds=th.dedup_window_sec)
    sorted_beats = sorted(beats, key=lambda b: (-b.score, b.t))
    kept: list[Beat] = []
    for b in sorted_beats:
        if b.kind in ("open", "recap"):
            kept.append(b)
            continue
        collide = False
        bt = _parse_iso(b.t)
        for prev in kept:
            if prev.kind != b.kind:
                continue
            if prev.symbol != b.symbol:
                continue
            if not (set(prev.agent_ids) & set(b.agent_ids)):
                continue
            if abs((_parse_iso(prev.t) - bt).total_seconds()) <= window.total_seconds():
                collide = True
                break
        if not collide:
            kept.append(b)
    return kept


def _select(beats: list[Beat], th: DetectorThresholds) -> list[Beat]:
    """Pin open + recap, then pick the highest-scoring of the rest until
    we land between target_min and target_max."""

    anchors = [b for b in beats if b.kind in ("open", "recap")]
    body = [b for b in beats if b.kind not in ("open", "recap")]
    body_sorted = sorted(
        body,
        key=lambda b: (
            -b.score,
            -KIND_PRIORITY.get(b.kind, 0),
            b.t,
        ),
    )
    target_max = th.target_max_beats
    body_kept = body_sorted[: max(0, target_max - len(anchors))]

    selected = anchors + body_kept
    # Final order: chronological with open first and recap last.
    open_beats = [b for b in selected if b.kind == "open"]
    recap_beats = [b for b in selected if b.kind == "recap"]
    middle = sorted(
        (b for b in selected if b.kind not in ("open", "recap")),
        key=lambda b: b.t,
    )
    return open_beats + middle + recap_beats


# ----- public API -----------------------------------------------------------


def detect_beats(
    manifest: dict[str, Any],
    *,
    thresholds: DetectorThresholds | None = None,
) -> list[Beat]:
    """Run every scorer over the manifest, dedup, select, return."""

    th = thresholds or DetectorThresholds()
    fills = _fills(manifest)
    pnls = _agent_pnl_from_fills(fills) if fills else {}

    candidates: list[Beat] = []
    open_beat = _score_open(manifest)
    if open_beat is not None:
        candidates.append(open_beat)
    candidates.extend(_score_big_fills(fills, th))
    candidates.extend(_score_divergence(fills, th))
    candidates.extend(_score_streaks(fills, pnls, th))
    candidates.extend(_score_top_movers(fills, pnls, th))
    burst = _score_closing_burst(fills, th)
    if burst is not None:
        candidates.append(burst)
    recap = _score_recap(manifest, pnls, fills)
    if recap is not None:
        candidates.append(recap)

    deduped = _dedup(candidates, th)
    return _select(deduped, th)


def write_beats(beats: Iterable[Beat], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(b) for b in beats]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ----- CLI ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """`python -m tradefarm.session.beats <session_id>` reads
    out/sessions/<id>/manifest.json and writes beats.json next to it."""

    parser = argparse.ArgumentParser(
        prog="tradefarm.session.beats",
        description="Score dramatic moments out of a session manifest.",
    )
    parser.add_argument(
        "session_id",
        help="Session id (matching out/sessions/<session_id>/manifest.json).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--target-min",
        type=int,
        default=DetectorThresholds().target_min_beats,
        help="Minimum beats to emit (default 8).",
    )
    parser.add_argument(
        "--target-max",
        type=int,
        default=DetectorThresholds().target_max_beats,
        help="Maximum beats to emit (default 15).",
    )
    args = parser.parse_args(argv)

    manifest_path = args.out / args.session_id / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = load_manifest(manifest_path)

    th = DetectorThresholds(
        target_min_beats=args.target_min,
        target_max_beats=args.target_max,
    )
    beats = detect_beats(manifest, thresholds=th)

    beats_path = manifest_path.parent / "beats.json"
    write_beats(beats, beats_path)

    print(
        f"session_id={args.session_id}\n"
        f"manifest={manifest_path}\n"
        f"beats={beats_path}\n"
        f"count={len(beats)}"
    )


if __name__ == "__main__":
    main()
