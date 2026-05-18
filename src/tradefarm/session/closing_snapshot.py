"""End-of-session snapshot writer.

After the last trading day, persist each agent's closing state
(equity, realized PnL, unrealized PnL, current positions) tagged with
the active session_id. This is the data Phase 2's --continue-from
flag will read to rehydrate books at the start of a follow-up session.

Skeleton — implementation lives in this file; see TODOs.
"""
from __future__ import annotations

import structlog

from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.storage import repo

log = structlog.get_logger()


async def write_closing_snapshot(orch: Orchestrator, marks: dict[str, float]) -> None:
    """For each agent in `orch.agents`, write a final PnlSnapshot row
    using `marks` to value any open positions, and sync positions to the
    DB. Both writes inherit the session_id from the ContextVar
    (runtime.session_context).

    `marks` should be the latest known close prices for each symbol the
    orchestrator's agents care about — typically `orch.last_marks` after
    the final tick.

    Implementation notes for the agent:
    - Use the existing storage helpers (don't duplicate them):
        from tradefarm.storage import repo
        await repo.snapshot_pnl(agent_id, book, marks)
        await repo.sync_positions(agent_id, book)
      `snapshot_pnl` already reads the session_id ContextVar.
      `sync_positions` does NOT yet read it — positions represent
      *current* state and there's only one row per agent_id+symbol.
      For v0, just call sync_positions as-is; the session_id story for
      Position state can wait until Phase 2 needs --continue-from.
    - Each agent's VirtualBook is `agent.state.book` per
      AgentState(name=..., strategy=..., book=...). See
      orchestrator.scheduler.Orchestrator.build_default for the shape.
    - Wrap in try/except per-agent so one bad write doesn't lose the
      session — log and continue.
    """
    for agent in orch.agents:
        try:
            book = agent.state.book
            await repo.snapshot_pnl(agent.state.id, book, marks)
            await repo.sync_positions(agent.state.id, book)
        except Exception as e:
            log.warning(
                "closing_snapshot_failed",
                agent_id=agent.state.id,
                error=str(e),
            )
