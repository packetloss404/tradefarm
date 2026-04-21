from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pandas as pd
import structlog

from tradefarm.agents.base import Agent, AgentState
from tradefarm.agents.llm_overlay import LlmOverlay
from tradefarm.agents.lstm_agent import LstmAgent
from tradefarm.agents.lstm_llm_agent import LstmLlmAgent
from tradefarm.agents.lstm_model import model_path
from tradefarm.agents.momentum import MomentumAgent
from tradefarm.config import settings
from tradefarm.data.eodhd import EodhdClient
from tradefarm.data.universe import default_universe
from tradefarm.execution.broker import Broker, SimulatedBroker
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.market.hours import is_market_open
from tradefarm.risk.manager import RiskManager
from tradefarm.api.events import publish_event
from tradefarm.execution.order_reconciler import OrderReconciler, ReconciledFill
from tradefarm.storage import journal, repo

log = structlog.get_logger()

RECONCILE_INTERVAL_SEC = 10

# In-memory counters for the dashboard. Reset at the start of each tick so
# the UI can display "notes this tick" alongside the existing LLM_SKIPS.
JOURNAL_COUNTERS: dict[str, int] = {"notes_this_tick": 0, "outcomes_this_tick": 0}


def _note_for_signal(agent: Agent, sig, px: float) -> tuple[str, dict]:
    """Build a short (1-2 line) thesis string + metadata dict for a journal
    note, tailored to the agent's strategy.
    """
    meta: dict = {
        "strategy": agent.state.strategy,
        "side": sig.side,
        "qty": sig.qty,
        "mark": px,
        "signal_reason": sig.reason,
    }
    # LSTM snapshot (both lstm_v1 and lstm_llm_v1 expose this shape).
    last_lstm = getattr(agent, "last_lstm", None) or getattr(agent, "last_prediction", None)
    if last_lstm:
        meta["lstm_probs"] = list(last_lstm.get("probs", []))
        meta["lstm_confidence"] = last_lstm.get("confidence")
        meta["lstm_direction"] = last_lstm.get("direction")
    # LLM overlay decision (lstm_llm_v1 only).
    last_decision = getattr(agent, "last_decision", None)
    if last_decision is not None:
        meta["llm_reason"] = getattr(last_decision, "reason", None)
        meta["llm_bias"] = getattr(last_decision, "bias", None)
        meta["llm_stance"] = getattr(last_decision, "stance", None)
        meta["llm_size_pct"] = getattr(last_decision, "size_pct", None)

    verb = "bought" if sig.side == "buy" else "sold"
    content = f"{verb} {sig.qty:g} {sig.symbol} @ ${px:.2f} — {sig.reason}"
    return content, meta


def _safe_build_overlay() -> LlmOverlay | None:
    """Return an overlay if the active provider has credentials; otherwise None.

    We swallow init errors so a bad key doesn't abort boot — the admin panel
    can still be used to fix the config.
    """
    try:
        return LlmOverlay.from_settings()
    except Exception as e:
        log.warning("llm_overlay_init_failed", error=str(e), provider=settings.llm_provider)
        return None


def _build_broker() -> Broker:
    if settings.execution_mode == "alpaca_paper":
        from tradefarm.execution.alpaca_broker import AlpacaBroker
        return AlpacaBroker()
    return SimulatedBroker()


class Orchestrator:
    def __init__(self, agents: list[Agent], broker: Broker | None = None) -> None:
        self.agents = agents
        self.data = EodhdClient()
        self.broker: Broker = broker or _build_broker()
        self.last_marks: dict[str, float] = {}
        self.last_tick_at: pd.Timestamp | None = None
        self._task: asyncio.Task | None = None
        # Reconciler state (alpaca_paper mode only).
        self._optimistic_marks: dict[str, float] = {}
        self._reconciler: OrderReconciler | None = None
        self._recon_task: asyncio.Task | None = None
        self._agents_by_id = {a.state.id: a for a in agents}
        # Phase 4 — curriculum loop gates on this to avoid mid-tick rank flips.
        self._tick_in_progress: bool = False
        self._curriculum_task: asyncio.Task | None = None

    @classmethod
    def build_default(cls, rank_map: dict[int, str] | None = None) -> "Orchestrator":
        """Build the default orchestrator.

        ``rank_map`` (optional): agent_id → rank from a previous boot. When
        provided, each ``RiskManager`` picks up that rank at construction so
        the first tick respects the persisted multiplier. Missing entries
        default to ``"intern"`` (the DB default for freshly-inserted rows).
        Phase 4's curriculum is responsible for in-flight updates between
        ticks; mid-tick rank changes are explicitly out of scope for Phase 2.
        """
        universe = default_universe()
        # Lazy-construct one shared LLM overlay if the active provider has credentials.
        overlay = _safe_build_overlay()
        rank_map = rank_map or {}

        agents: list[Agent] = []
        for i in range(settings.agent_count):
            symbol = universe[i % len(universe)]
            book = VirtualBook(agent_id=i, cash=settings.agent_starting_capital)
            agent_rank = rank_map.get(i, "intern")
            risk = RiskManager(
                starting_capital=settings.agent_starting_capital,
                rank=agent_rank,
            )
            has_model = model_path(symbol).exists()

            slot = i % 3  # 0=momentum, 1=lstm, 2=lstm+llm
            if slot == 2 and has_model and overlay is not None:
                strategy = LstmLlmAgent.strategy_name
                state = AgentState(id=i, name=f"agent-{i:03d}", strategy=strategy, book=book)
                agents.append(LstmLlmAgent(state, risk, symbol=symbol, overlay=overlay))
            elif slot == 1 and has_model:
                strategy = LstmAgent.strategy_name
                state = AgentState(id=i, name=f"agent-{i:03d}", strategy=strategy, book=book)
                agents.append(LstmAgent(state, risk, symbol=symbol))
            else:
                strategy = MomentumAgent.strategy_name
                state = AgentState(id=i, name=f"agent-{i:03d}", strategy=strategy, book=book)
                agents.append(MomentumAgent(state, risk, symbol=symbol))
        return cls(agents)

    async def persist_initial_state(self) -> None:
        for a in self.agents:
            await repo.upsert_agent(
                a.state.id, a.state.name, a.state.strategy, settings.agent_starting_capital,
            )

    async def _load_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        end = date.today()
        start = end - timedelta(days=180)
        out: dict[str, pd.DataFrame] = {}
        for s in symbols:
            try:
                out[s] = await self.data.get_eod(s, start=start, end=end)
            except Exception as e:
                log.warning("bars_load_failed", symbol=s, error=str(e))
        return out

    async def tick_once(self) -> dict:
        self._tick_in_progress = True
        try:
            return await self._tick_once_inner()
        finally:
            self._tick_in_progress = False

    async def _tick_once_inner(self) -> dict:
        symbols = sorted({getattr(a, "symbol", None) for a in self.agents if hasattr(a, "symbol")})
        symbols = [s for s in symbols if s]
        bars = await self._load_bars(symbols)
        marks: dict[str, float] = {
            s: float(df["adjusted_close"].iloc[-1])
            for s, df in bars.items() if not df.empty
        }
        self.last_marks = marks
        self.last_tick_at = pd.Timestamp.now(tz="UTC")

        # Collect signals from all agents in parallel (LLM calls dominate).
        sem = asyncio.Semaphore(20)
        disabled = settings.disabled_strategies_set

        async def gather(a):
            if a.state.strategy in disabled:
                return a, []  # frozen strategy — no new signals
            async with sem:
                try:
                    return a, await a.decide(bars, marks)
                except Exception as e:
                    log.warning("decide_failed", agent=a.state.name, error=str(e))
                    return a, []

        results = await asyncio.gather(*(gather(a) for a in self.agents))

        # Reset per-tick journal counters.
        JOURNAL_COUNTERS["notes_this_tick"] = 0
        JOURNAL_COUNTERS["outcomes_this_tick"] = 0

        fills = 0
        blocked = 0
        for agent, signals in results:
            for sig in signals:
                px = marks.get(sig.symbol)
                if px is None:
                    continue
                if sig.side == "buy":
                    decision = agent.risk.check_entry(agent.state.book, sig.symbol, sig.qty, px)
                    if not decision.allow:
                        blocked += 1
                        log.info("risk_blocked", agent=agent.state.name, sym=sig.symbol, reason=decision.reason)
                        continue
                # Write the journal note *before* submitting, so it's durable
                # even if the broker round-trip fails mid-flight.
                note_content, note_meta = _note_for_signal(agent, sig, px)
                note_kind = "entry" if sig.side == "buy" else "exit"
                note_id = await journal.write_note(
                    agent.state.id, note_kind, sig.symbol, note_content, note_meta,
                )
                if note_id is not None:
                    agent.journal_note_id = note_id
                    JOURNAL_COUNTERS["notes_this_tick"] += 1

                client_tag = uuid.uuid4().hex[:8]
                if settings.execution_mode == "alpaca_paper":
                    # Key: the exact client_order_id the broker will send to Alpaca.
                    self._optimistic_marks[f"agent{agent.state.id}-{client_tag}"] = px
                fill = self.broker.submit_market(
                    symbol=sig.symbol,
                    side=sig.side,
                    qty=sig.qty,
                    agent_id=agent.state.id,
                    client_tag=client_tag,
                    mark=px,
                )
                if fill is None:
                    # Pop the optimistic mark — the order was not submitted
                    # (e.g. off-hours gate rejected it).
                    self._optimistic_marks.pop(f"agent{agent.state.id}-{client_tag}", None)
                    continue
                realized = agent.on_fill(fill.symbol, fill.side, fill.qty, fill.price)
                await repo.record_trade(
                    agent.state.id, fill.symbol, fill.side, fill.qty, fill.price, sig.reason,
                )
                await repo.sync_positions(agent.state.id, agent.state.book)
                # If the fill produced non-zero realized PnL, stamp the
                # matching entry note. Idempotent: one stamp per flat-out.
                if realized != 0.0:
                    stamped = await journal.close_outcome(
                        agent.state.id, fill.symbol, float(realized), trade_id=None,
                    )
                    if stamped is not None:
                        JOURNAL_COUNTERS["outcomes_this_tick"] += 1
                fills += 1
                log.info(
                    "fill", agent=agent.state.name, sym=sig.symbol, side=sig.side,
                    qty=sig.qty, px=px, reason=sig.reason,
                )
                await publish_event("fill", {
                    "agent_id": agent.state.id,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "qty": fill.qty,
                    "price": fill.price,
                    "reason": sig.reason,
                })

        # Snapshot + status update happens after all agents have processed signals.
        for agent in self.agents:
            await repo.snapshot_pnl(agent.state.id, agent.state.book, marks)
            equity = agent.state.book.equity(marks)
            start = settings.agent_starting_capital
            agent.state.status = (
                "profit" if equity > start * 1.001
                else "loss" if equity < start * 0.999
                else "waiting"
            )

        profit = sum(1 for a in self.agents if a.state.status == "profit")
        loss = sum(1 for a in self.agents if a.state.status == "loss")
        waiting = sum(1 for a in self.agents if a.state.status == "waiting")
        total_equity = sum(a.state.book.equity(marks) for a in self.agents)
        realized = sum(a.state.book.realized_pnl for a in self.agents)
        unrealized = sum(a.state.book.unrealized_pnl(marks) for a in self.agents)
        last_tick_iso = self.last_tick_at.isoformat()
        await publish_event("account", {
            "profit_ai": profit, "loss_ai": loss, "waiting_ai": waiting,
            "total_equity": total_equity,
            "realized_pnl": realized, "unrealized_pnl": unrealized,
            "last_tick_at": last_tick_iso,
            "notes_this_tick": JOURNAL_COUNTERS["notes_this_tick"],
            "outcomes_this_tick": JOURNAL_COUNTERS["outcomes_this_tick"],
        })
        await publish_event("tick", {
            "fills": fills, "blocked": blocked, "symbols": len(marks),
            "last_tick_at": last_tick_iso,
        })

        return {"fills": fills, "blocked": blocked, "symbols": len(marks)}

    async def run_scheduled(self) -> None:
        """Background loop. Sleeps outside RTH (unless tick_outside_rth=True).

        Skips the tick entirely when settings.ai_enabled is False — the master
        kill switch controlled from the admin panel.
        """
        interval = settings.auto_tick_interval_sec
        if interval <= 0:
            log.info("scheduler_disabled")
            return
        log.info("scheduler_started", interval_sec=interval, allow_off_hours=settings.tick_outside_rth)
        while True:
            try:
                if not settings.ai_enabled:
                    log.debug("scheduler_ai_disabled")
                elif settings.tick_outside_rth or is_market_open():
                    result = await self.tick_once()
                    log.info("scheduled_tick", **result)
                else:
                    log.debug("scheduler_skip_off_hours")
            except Exception as e:
                log.exception("scheduled_tick_failed", error=str(e))
            await asyncio.sleep(interval)

    def reload_llm_overlay(self) -> dict[str, str | None]:
        """Rebuild the shared LLM overlay (e.g. after the admin panel flips
        provider / key / model) and re-point every LSTM+LLM agent at it.

        Returns the new overlay's {provider, model}, or {provider: None} if
        the new settings don't have credentials.
        """
        new = _safe_build_overlay()
        for a in self.agents:
            if isinstance(a, LstmLlmAgent):
                a._overlay = new  # type: ignore[attr-defined]
        if new is None:
            return {"provider": None, "model": None}
        return dict(new.info)

    def start_background(self) -> None:
        if settings.auto_tick_interval_sec > 0 and self._task is None:
            self._task = asyncio.create_task(self.run_scheduled(), name="orch_scheduler")

        if settings.execution_mode == "alpaca_paper" and self._recon_task is None:
            # Lazy import to avoid pulling alpaca-py in simulated mode.
            from tradefarm.execution.alpaca_broker import AlpacaBroker
            if isinstance(self.broker, AlpacaBroker):
                self._reconciler = OrderReconciler(self.broker, self._optimistic_marks)
                self._recon_task = asyncio.create_task(
                    self._reconcile_loop(), name="orch_reconciler",
                )

        # Phase 4 — opt-in curriculum loop (0 disables).
        self.start_curriculum()

    def start_curriculum(self) -> None:
        """Start the between-ticks curriculum loop if the interval is > 0."""
        if settings.academy_eval_interval_sec > 0 and self._curriculum_task is None:
            self._curriculum_task = asyncio.create_task(
                self.run_curriculum_loop(), name="orch_curriculum",
            )

    async def stop_curriculum(self) -> None:
        t = self._curriculum_task
        if t is None:
            return
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        self._curriculum_task = None

    async def run_curriculum_loop(self) -> None:
        """Background loop: run the curriculum every N seconds, but never during
        a tick. We poll the ``_tick_in_progress`` flag before calling
        ``evaluate_all`` so rank changes never race with a running tick.
        """
        interval = settings.academy_eval_interval_sec
        if interval <= 0:
            return
        # Lazy-import so test fixtures can patch `curriculum` before loop runs.
        from tradefarm.academy import curriculum
        log.info("curriculum_loop_started", interval_sec=interval)
        while True:
            try:
                # Wait for any in-progress tick to finish — brief polling.
                while self._tick_in_progress:
                    await asyncio.sleep(0.05)
                await curriculum.evaluate_all(self)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("curriculum_loop_failed", error=str(e))
            await asyncio.sleep(interval)

    async def _reconcile_loop(self) -> None:
        """Poll Alpaca for filled orders and apply actual-vs-mark deltas to agent books."""
        assert self._reconciler is not None
        log.info("reconcile_loop_started", interval_sec=RECONCILE_INTERVAL_SEC)
        while True:
            try:
                fills = self._reconciler.poll_once()
                if fills:
                    applied = await self._apply_reconciled(fills)
                    log.info("reconciled", n=len(fills), applied=applied)
            except Exception as e:
                log.exception("reconcile_loop_failed", error=str(e))
            await asyncio.sleep(RECONCILE_INTERVAL_SEC)

    async def _apply_reconciled(self, fills: list[ReconciledFill]) -> int:
        applied = 0
        for rf in fills:
            agent = self._agents_by_id.get(rf.agent_id)
            if agent is None:
                log.warning("reconciled_unknown_agent", agent_id=rf.agent_id, broker_oid=rf.broker_order_id)
                continue
            ok = agent.state.book.apply_fill_delta(
                rf.symbol, rf.side, rf.qty, rf.delta, rf.broker_order_id,
            )
            if ok:
                applied += 1
                await publish_event("reconcile", {
                    "agent_id": rf.agent_id,
                    "symbol": rf.symbol,
                    "side": rf.side,
                    "qty": rf.qty,
                    "delta": rf.delta,
                    "actual_price": rf.actual_price,
                })
        return applied

    async def stop_background(self) -> None:
        for t in (self._task, self._recon_task):
            if t is None:
                continue
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._recon_task = None
        await self.stop_curriculum()
