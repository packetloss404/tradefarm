"""Phase 4 — curriculum loop.

``evaluate_all(orchestrator)`` walks every live agent, recomputes rank stats,
and promotes (always) or demotes (only on a real trigger). Designed to run
*between ticks*: the caller gates on ``orchestrator._tick_in_progress``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from tradefarm.academy import promotions_repo
from tradefarm.academy import ranks as ranks_mod
from tradefarm.academy import repo as academy_repo
from tradefarm.academy.ranks import RANK_ORDER, Rank, RankStats
from tradefarm.api.events import publish_event
from tradefarm.config import settings
from tradefarm.risk.manager import RiskManager
from tradefarm.storage import journal

if TYPE_CHECKING:
    from tradefarm.agents.base import Agent
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()


@dataclass
class PromotionEvent:
    agent_id: int
    agent_name: str
    from_rank: str
    to_rank: str
    reason: str
    stats_snapshot_json: str
    at: str


@dataclass
class CurriculumResult:
    promoted: list[PromotionEvent] = field(default_factory=list)
    demoted: list[PromotionEvent] = field(default_factory=list)
    unchanged: int = 0
    evaluated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "promoted": [e.__dict__ for e in self.promoted],
            "demoted": [e.__dict__ for e in self.demoted],
            "unchanged": self.unchanged,
            "evaluated_at": self.evaluated_at,
        }


async def _consecutive_losses(agent_id: int) -> int:
    """Longest losing run ending at the most recent closed outcome."""
    outcomes = await journal.recent_outcomes(agent_id, n=200)
    run = 0
    for o in outcomes:
        pnl = o.get("outcome_realized_pnl")
        if pnl is None:
            continue
        if pnl >= 0:
            break
        run += 1
    return run


def _drawdown_proxy(stats: RankStats) -> float:
    """Blunt drawdown proxy from stats (no equity history needed)."""
    if stats.sharpe >= 0 and stats.win_rate >= 0.5:
        return 0.0
    loss_rate = max(0.0, 1.0 - stats.win_rate)
    sharpe_pen = max(0.0, -stats.sharpe) / 2.0
    return min(1.0, loss_rate * 0.5 + sharpe_pen)


def _demotion_trigger(stats: RankStats, consec: int) -> tuple[bool, str]:
    """Demote only if n_closed_trades >= min_junior AND (drawdown OR losing streak)."""
    if stats.n_closed_trades < settings.academy_min_trades_junior:
        return False, "below min trades floor"
    dd = _drawdown_proxy(stats)
    if dd >= settings.academy_demote_drawdown_pct:
        return True, f"drawdown {dd:.2%} >= {settings.academy_demote_drawdown_pct:.2%}"
    if consec >= settings.academy_demote_consecutive_losses:
        return True, f"{consec} losses in a row"
    return False, ""


def _severity(stats: RankStats, consec: int) -> float:
    return max(_drawdown_proxy(stats), consec / 10.0)


def _rebuild_risk(agent: "Agent", new_rank: Rank) -> None:
    agent.risk = RiskManager(starting_capital=agent.risk.starting_capital, rank=new_rank)


async def _apply(agent: "Agent", stats: RankStats, frm: Rank, to: Rank, reason: str) -> PromotionEvent:
    await academy_repo.set_rank(agent.state.id, to, reason=reason)
    _rebuild_risk(agent, to)
    ev = PromotionEvent(
        agent_id=agent.state.id,
        agent_name=agent.state.name,
        from_rank=frm,
        to_rank=to,
        reason=reason,
        stats_snapshot_json=promotions_repo.stats_to_json(stats),
        at=datetime.now(timezone.utc).isoformat(),
    )
    await promotions_repo.record(ev)
    return ev


def _payload(ev: PromotionEvent) -> dict:
    return {
        "agent_id": ev.agent_id, "agent_name": ev.agent_name,
        "from_rank": ev.from_rank, "to_rank": ev.to_rank,
        "reason": ev.reason, "at": ev.at,
    }


async def evaluate_all(orchestrator: "Orchestrator") -> CurriculumResult:
    """Evaluate every agent once; emit promotions/demotions per the rules."""
    result = CurriculumResult(evaluated_at=datetime.now(timezone.utc).isoformat())
    agents = list(orchestrator.agents)
    promotions: list[tuple["Agent", RankStats, Rank, Rank]] = []
    demotions: list[tuple["Agent", RankStats, Rank, Rank, str, float]] = []

    for agent in agents:
        stats = await ranks_mod.compute_stats(
            agent.state.id, starting_capital=agent.risk.starting_capital,
        )
        current: Rank = getattr(agent.risk, "rank", "intern")  # type: ignore[assignment]
        if current not in RANK_ORDER:
            current = "intern"
        eligible = ranks_mod.eligible_rank(stats)
        ci = RANK_ORDER.index(current)
        ei = RANK_ORDER.index(eligible)
        if ei > ci:
            promotions.append((agent, stats, current, RANK_ORDER[ci + 1]))
        elif ei < ci:
            consec = await _consecutive_losses(agent.state.id)
            should, reason = _demotion_trigger(stats, consec)
            if not should:
                result.unchanged += 1
                continue
            demotions.append((
                agent, stats, current, RANK_ORDER[ci - 1], reason,
                _severity(stats, consec),
            ))
        else:
            result.unchanged += 1

    cap_n = int(settings.academy_demote_cap_pct * len(agents))
    demotions.sort(key=lambda t: t[5], reverse=True)
    to_demote, skipped = demotions[:cap_n], demotions[cap_n:]
    for s in skipped:
        result.unchanged += 1
        log.info("curriculum_demotion_skipped",
                 agent_id=s[0].state.id, from_rank=s[2], to_rank=s[3],
                 reason=s[4], cap_n=cap_n)

    for agent, stats, frm, to in promotions:
        ev = await _apply(agent, stats, frm, to, f"promoted: eligible for {to}")
        result.promoted.append(ev)
        await publish_event("promotion", _payload(ev))

    for agent, stats, frm, to, reason, _ in to_demote:
        ev = await _apply(agent, stats, frm, to, f"demoted: {reason}")
        result.demoted.append(ev)
        await publish_event("demotion", _payload(ev))

    log.info("curriculum_pass",
             promoted=len(result.promoted), demoted=len(result.demoted),
             skipped=len(skipped), unchanged=result.unchanged)
    return result
