from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd
import structlog

from tradefarm.agents.base import Agent, AgentState, Signal
from tradefarm.agents.llm_overlay import LlmOverlay
from tradefarm.agents.lstm_agent import LstmAgent
from tradefarm.agents.lstm_llm_agent import LstmLlmAgent
from tradefarm.agents.lstm_model import model_path
from tradefarm.agents.momentum import MomentumAgent
from tradefarm.agents.names import agent_display_name
from tradefarm.config import settings
from tradefarm.runtime.clock import now_utc as _runtime_clock_now_utc
from tradefarm.data.eodhd import EodhdClient
from tradefarm.data.universe import default_universe
from tradefarm.execution.broker import Broker, SimulatedBroker
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.market.hours import is_market_open
from tradefarm.risk.manager import RiskManager
from tradefarm.runtime.money import D, quantize_qty
from tradefarm.api.events import publish_event
from tradefarm.execution.order_reconciler import OrderReconciler, ReconciledFill
from tradefarm.orchestrator.broadcast_os import BroadcastMoment, publish_broadcast_moment
from tradefarm.orchestrator.broadcast_suite import BroadcastSuite, attach_crash_logger
from tradefarm.orchestrator.decision_feed import build_decisions_batch
from tradefarm.storage import journal, repo

log = structlog.get_logger()

RECONCILE_INTERVAL_SEC = 10
# How long a pending risk-exit blocks a re-queue of the same
# (agent, symbol). Beyond this the scheduler assumes the broker dropped
# the order and lets the next risk check re-queue. 60s is generous for
# Alpaca paper (usually <1s) but accommodates the 10s reconciler poll
# plus broker-side queueing.
PENDING_EXIT_TTL_SEC: float = 60.0

# In-memory counters for the dashboard. Reset at the start of each tick so
# the UI can display "notes this tick" alongside the existing LLM_SKIPS.
JOURNAL_COUNTERS: dict[str, int] = {"notes_this_tick": 0, "outcomes_this_tick": 0}
FILL_OF_TICK_MIN_NOTIONAL: float = 50.0


@dataclass(frozen=True)
class _FillMomentCandidate:
    agent_id: int
    agent_name: str
    symbol: str
    side: str
    qty: float
    price: float
    reason: str

    @property
    def notional(self) -> float:
        return abs(self.qty * self.price)


def _note_for_signal(agent: Agent, sig, px: float) -> tuple[str, dict]:
    """Build a short (1-2 line) thesis string + metadata dict for a journal
    note, tailored to the agent's strategy.
    """
    meta: dict = {
        "strategy": agent.state.strategy,
        "side": sig.side,
        "qty": float(sig.qty),  # JSON boundary (note_metadata is serialized)
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
        # Audit fix (C9): replace polling-on-flag with a real lock so the
        # curriculum can't run concurrently with tick_once, and two
        # concurrent /tick calls can't interleave.
        self._tick_lock: asyncio.Lock = asyncio.Lock()
        # Audit fix (H17 / scheduler double-submit): track risk exits
        # queued this tick by (agent_id, symbol) so a second tick that
        # arrives before Alpaca fills the first exit doesn't queue a
        # duplicate sell of the (still-open) full position. The set is
        # pruned when the reconciler reports the exit as filled OR after
        # PENDING_EXIT_TTL_SEC.
        self._pending_exits: dict[tuple[int, str], float] = {}
        # Round-6 audit fix (recent_fills ring): bounded ring buffer of the
        # most recent fills, appended to in BOTH the in-tick fill site
        # (simulated broker + optimistic Alpaca submit) AND the reconciler
        # (actual-vs-mark correction for alpaca_paper). The cost-gate in
        # ``CommentaryLoop`` reads this ring — surfaces "any fill in the
        # last 50" rather than "any open position" so quiet stretches with
        # stale positions no longer trip the LLM every 45s. Newest entry
        # is at the end of the deque. ``.recent_fills`` returns a copy
        # so readers don't observe a half-appended entry under the GIL.
        self._recent_fills: deque[dict[str, Any]] = deque(maxlen=50)
        self._curriculum_task: asyncio.Task | None = None
        # Issue #6: the presentation/interactivity layer (auto-director,
        # streak watcher, commentary, youtube chat, predictions, audience)
        # plus the broadcast ledger/scheduler arbiter is owned by a single
        # BroadcastSuite. The orchestrator delegates to it as a unit. The
        # suite constructs the ledger/scheduler here but only INSTALLS them
        # as module globals on start() (audit fix C15 — installing at
        # construction polluted test globals).
        self._broadcast_suite = BroadcastSuite(self)

    # ------------------------------------------------------------------
    # Public read-only views.
    # ------------------------------------------------------------------

    @property
    def recent_fills(self) -> list[dict[str, Any]]:
        """Snapshot of the bounded in-memory fill ring buffer.

        Newest fills are at the END of the list. Each entry is a dict
        shaped ``{agent_id, agent_name, symbol, side, qty, price, at}``
        where ``price`` is the executed (or optimistic) fill price as
        a float, ``qty`` is shares, and ``at`` is a tz-aware datetime
        stamped via :func:`tradefarm.runtime.clock.now_utc` so replay
        sessions use the replayed clock. The buffer is bounded at 50
        entries; the oldest entry is silently dropped on overflow.
        Returns a copy so readers cannot observe a half-appended entry
        under the GIL during a concurrent reconciler append.
        """
        return list(self._recent_fills)

    # ------------------------------------------------------------------
    # Backward-compatible delegators. External consumers (api/audience.py,
    # api/recap.py, youtube_chat.py, audit-regression tests) still read
    # these attrs off the orchestrator directly; ownership now lives in the
    # BroadcastSuite, so expose them as read-only views into the suite.
    # ------------------------------------------------------------------
    @property
    def _broadcast_ledger(self):  # noqa: ANN202 — opaque suite-owned object
        return self._broadcast_suite.ledger

    @property
    def _broadcast_scheduler(self):  # noqa: ANN202 — opaque suite-owned object
        return self._broadcast_suite.scheduler

    @property
    def _audience(self):  # noqa: ANN202 — opaque suite-owned object
        return self._broadcast_suite.audience

    @property
    def _predictions(self):  # noqa: ANN202 — opaque suite-owned object
        return self._broadcast_suite.predictions

    @property
    def _commentary_loop(self):  # noqa: ANN202 — opaque suite-owned object
        return self._broadcast_suite.commentary_loop

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
            book = VirtualBook(agent_id=i, cash=D(settings.agent_starting_capital))
            agent_rank = rank_map.get(i, "intern")
            risk = RiskManager(
                starting_capital=settings.agent_starting_capital,
                rank=agent_rank,
            )
            has_model = model_path(symbol).exists()

            slot = i % 3  # 0=momentum, 1=lstm, 2=lstm+llm
            name = agent_display_name(i)
            if slot == 2 and has_model and overlay is not None:
                strategy = LstmLlmAgent.strategy_name
                state = AgentState(id=i, name=name, strategy=strategy, book=book)
                agents.append(LstmLlmAgent(state, risk, symbol=symbol, overlay=overlay))
            elif slot == 1 and has_model:
                strategy = LstmAgent.strategy_name
                state = AgentState(id=i, name=name, strategy=strategy, book=book)
                agents.append(LstmAgent(state, risk, symbol=symbol))
            else:
                strategy = MomentumAgent.strategy_name
                state = AgentState(id=i, name=name, strategy=strategy, book=book)
                agents.append(MomentumAgent(state, risk, symbol=symbol))
        return cls(agents)

    async def persist_initial_state(self) -> None:
        for a in self.agents:
            await repo.upsert_agent(
                a.state.id,
                a.state.name,
                a.state.strategy,
                settings.agent_starting_capital,
            )

    async def _load_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        from tradefarm.runtime.clock import today_utc

        end = today_utc()
        start = end - timedelta(days=180)
        out: dict[str, pd.DataFrame] = {}
        for s in symbols:
            try:
                out[s] = await self.data.get_eod(s, start=start, end=end)
            except Exception as e:
                log.warning("bars_load_failed", symbol=s, error=str(e))
        return out

    async def tick_once(self) -> dict:
        # Audit fix (C9): real asyncio.Lock instead of poll-on-flag, so
        # the curriculum loop can't swap agent.risk mid-tick AND so two
        # concurrent /tick calls (e.g. dashboard click while
        # run_scheduled is mid-tick) serialize rather than interleave.
        async with self._tick_lock:
            self._tick_in_progress = True
            try:
                return await self._tick_once_inner()
            finally:
                self._tick_in_progress = False

    async def _tick_once_inner(self) -> dict:
        tick_id = uuid.uuid4().hex[:12]
        symbols = sorted(
            {
                sym
                for a in self.agents
                if (sym := getattr(a, "symbol", None)) is not None and isinstance(sym, str)
            }
        )
        bars = await self._load_bars(symbols)
        marks: dict[str, float] = {
            s: float(df["adjusted_close"].iloc[-1]) for s, df in bars.items() if not df.empty
        }
        self.last_marks = marks
        # Use the injectable clock so replay sessions stamp last_tick_at
        # with the replayed timestamp, not wall-clock today. Otherwise
        # any consumer that diffs (now - last_tick_at) sees a delta of
        # however-long-ago the replayed day was.
        self.last_tick_at = pd.Timestamp(_runtime_clock_now_utc())

        # Collect signals from all agents in parallel (LLM calls dominate).
        sem = asyncio.Semaphore(20)
        disabled = settings.disabled_strategies_set
        # Per-agent disable set: read once per tick (the agents table is
        # small, ~100 rows). Disabled agents are fully frozen — no new
        # entries AND no risk-driven exits — so the operator can park a
        # misbehaving agent without it being force-closed on the next SL.
        # The risk-exit loop below intentionally uses this same set so a
        # disabled agent's open position is not touched until re-enabled.
        disabled_agent_ids = await repo.get_disabled_agent_ids()

        async def gather(a):
            if a.state.strategy in disabled:
                return a, []  # frozen strategy — no new signals
            if a.state.id in disabled_agent_ids:
                # Disabled agents are fully frozen: no new entries AND no
                # risk-driven exits. The operator must re-enable to exit
                # a position. This is intentionally conservative — a
                # "disable" is "leave the position alone", not "force
                # close on the next tick" (which on a wrong tick could
                # crystallize a loss the operator didn't authorize).
                return a, []
            async with sem:
                try:
                    return a, await a.decide(bars, marks)
                except Exception as e:
                    log.warning("decide_failed", agent=a.state.name, error=str(e))
                    return a, []

        results = await asyncio.gather(*(gather(a) for a in self.agents))

        # Decision Lab — publish every agent's per-tick reasoning (including
        # WAIT verdicts) as a single batch event so the broadcast app can
        # render the system "thinking out loud" on flat days. Done *before*
        # risk-driven exits because risk exits aren't part of the agent's
        # own thinking — they're forced overrides we apply on top.
        try:
            batch = build_decisions_batch(results, marks, tick_id=tick_id)
            await publish_event("agent_decisions_batch", batch)
        except Exception as e:  # pragma: no cover — never let surfacing break a tick
            log.warning("agent_decisions_batch_failed", error=str(e))

        # Reset per-tick journal counters.
        JOURNAL_COUNTERS["notes_this_tick"] = 0
        JOURNAL_COUNTERS["outcomes_this_tick"] = 0

        # --- Risk-driven exits (Phase 2.5) -----------------------------------
        # For each open long position, check the RiskManager's SL/TP/time/trail
        # rules. If any fires, synthesize a Sell signal that bypasses the
        # agent's brain entirely. If the brain also emitted a sell for the
        # same symbol, the risk reason replaces it (so the journal records the
        # true exit trigger).
        # Use the injectable clock so replay sessions see the replayed
        # close as "now". Wall-clock here would make every position look
        # held for however-long-ago the replayed day was, instantly
        # triggering time-stop exits.
        now_utc = _runtime_clock_now_utc()
        risk_exits_added = 0
        results_by_id = {a.state.id: (a, sigs) for a, sigs in results}
        # Audit fix (scheduler double-submit): prune pending exits older
        # than PENDING_EXIT_TTL_SEC — Alpaca paper fills are usually
        # near-instant; if an exit is still pending after this window
        # something went wrong upstream and we let the next risk check
        # re-queue it rather than blocking forever.
        now_ts = now_utc.timestamp()
        stale = [k for k, ts in self._pending_exits.items() if now_ts - ts > PENDING_EXIT_TTL_SEC]
        for k in stale:
            self._pending_exits.pop(k, None)

        for agent in self.agents:
            # Per-agent disable: a disabled agent is fully frozen — no new
            # entries AND no risk-driven exits. See the gather() comment
            # above for the rationale ("leave the position alone", not
            # "force-close on the next tick"). Operator must re-enable
            # to exit a trade.
            if agent.state.id in disabled_agent_ids:
                continue
            for sym, pos in list(agent.state.book.positions.items()):
                if pos.qty <= 0:
                    continue
                # Audit fix (H17 / scheduler double-submit): if a risk
                # exit for this (agent, symbol) is still pending from a
                # prior tick (broker hasn't filled yet), don't queue
                # another full-qty sell — that's how a position flips
                # short under alpaca_paper while the original exit is
                # in flight.
                if (agent.state.id, sym) in self._pending_exits:
                    continue
                mark = float(marks.get(sym, pos.avg_price))
                trig = agent.risk.should_exit(sym, pos, mark, now_utc)
                if trig is None:
                    continue
                entry = results_by_id.get(agent.state.id)
                if entry is None:
                    continue
                a_ref, sigs = entry
                # Drop any brain-emitted sell for the same symbol (risk wins).
                sigs = [s for s in sigs if not (s.symbol == sym and s.side == "sell")]
                sigs.append(
                    Signal(sym, "sell", quantize_qty(pos.qty), reason=f"risk-exit: {trig.reason}")
                )
                results_by_id[agent.state.id] = (a_ref, sigs)
                self._pending_exits[(agent.state.id, sym)] = now_ts
                risk_exits_added += 1
        if risk_exits_added:
            log.info("risk_exits_queued", count=risk_exits_added)
            results = list(results_by_id.values())
        # ---------------------------------------------------------------------

        fills = 0
        blocked = 0
        fill_moment_candidates: list[_FillMomentCandidate] = []
        for agent, signals in results:
            for sig in signals:
                px = marks.get(sig.symbol)
                if px is None:
                    continue
                if sig.side == "buy":
                    decision = agent.risk.check_entry(agent.state.book, sig.symbol, sig.qty, px)
                    if not decision.allow:
                        blocked += 1
                        log.info(
                            "risk_blocked",
                            agent=agent.state.name,
                            sym=sig.symbol,
                            reason=decision.reason,
                        )
                        continue
                # Write the journal note *before* submitting, so it's durable
                # even if the broker round-trip fails mid-flight.
                note_content, note_meta = _note_for_signal(agent, sig, px)
                note_kind = "entry" if sig.side == "buy" else "exit"
                note_id = await journal.write_note(
                    agent.state.id,
                    note_kind,
                    sig.symbol,
                    note_content,
                    note_meta,
                )
                if note_id is not None:
                    agent.journal_note_id = note_id
                    JOURNAL_COUNTERS["notes_this_tick"] += 1

                client_tag = uuid.uuid4().hex[:8]
                if settings.execution_mode == "alpaca_paper":
                    # Key: the exact client_order_id the broker will send to Alpaca.
                    self._optimistic_marks[f"agent{agent.state.id}-{client_tag}"] = px
                fill = await self.broker.submit_market(
                    symbol=sig.symbol,
                    side=sig.side,
                    qty=float(sig.qty),  # broker/market boundary is float
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
                # Audit fix (O): clear the pending-exit guard on every
                # in-tick sell fill — in simulated mode the reconciler
                # never runs, so without this clear the guard would
                # block re-entries on the same symbol for the full
                # PENDING_EXIT_TTL_SEC window. Also clear the trailing
                # peak if the fill flattened the position.
                if sig.side == "sell":
                    self._pending_exits.pop((agent.state.id, fill.symbol), None)
                    pos = agent.state.book.positions.get(fill.symbol)
                    if pos is None or abs(pos.qty) < 1e-9:
                        # Audit fix (round 3): defensive getattr so a
                        # stub agent in tests (with a risk stub lacking
                        # clear_peak) can't AttributeError mid-tick and
                        # take down the loop.
                        clear = getattr(agent.risk, "clear_peak", None)
                        if callable(clear):
                            clear(fill.symbol)
                # Issue #8c: persist the trade row + the position sync in a
                # single transaction so a crash between them can't leave the
                # DB inconsistent. Dedupe on broker_order_id is preserved
                # inside record_fill_atomic.
                await repo.record_fill_atomic(
                    agent.state.id,
                    agent.state.book,
                    fill.symbol,
                    fill.side,
                    fill.qty,
                    fill.price,
                    sig.reason,
                    broker_order_id=fill.broker_order_id or None,
                )
                # If the fill produced non-zero realized PnL, stamp the
                # matching entry note. Idempotent: one stamp per flat-out.
                if realized != 0.0:
                    stamped = await journal.close_outcome(
                        agent.state.id,
                        fill.symbol,
                        float(realized),
                        trade_id=None,
                    )
                    if stamped is not None:
                        JOURNAL_COUNTERS["outcomes_this_tick"] += 1
                fills += 1
                log.info(
                    "fill",
                    agent=agent.state.name,
                    sym=sig.symbol,
                    side=sig.side,
                    qty=float(sig.qty),
                    px=px,
                    reason=sig.reason,
                )
                await publish_event(
                    "fill",
                    {
                        "agent_id": agent.state.id,
                        "symbol": fill.symbol,
                        "side": fill.side,
                        "qty": fill.qty,
                        "price": fill.price,
                        "reason": sig.reason,
                    },
                )
                fill_moment_candidates.append(
                    _FillMomentCandidate(
                        agent_id=agent.state.id,
                        agent_name=agent.state.name,
                        symbol=fill.symbol,
                        side=fill.side,
                        qty=float(fill.qty),
                        price=float(fill.price),
                        reason=sig.reason,
                    )
                )
                # Record the fill in the bounded ring buffer so the
                # commentary cost-gate can read real fill activity
                # instead of inferring it from open positions. ``at``
                # goes through the replay-aware clock so backtested
                # sessions stamp the replayed timestamp, matching the
                # convention used elsewhere in this tick path.
                self._recent_fills.append(
                    {
                        "agent_id": agent.state.id,
                        "agent_name": agent.state.name,
                        "symbol": fill.symbol,
                        "side": fill.side,
                        "qty": float(fill.qty),
                        "price": float(fill.price),
                        "at": _runtime_clock_now_utc(),
                    }
                )

        await self._publish_fill_of_tick(tick_id, fill_moment_candidates)

        # Snapshot + status update happens after all agents have processed signals.
        for agent in self.agents:
            await repo.snapshot_pnl(agent.state.id, agent.state.book, marks)
            equity = float(agent.state.book.equity(marks))
            start = settings.agent_starting_capital
            agent.state.status = (
                "profit"
                if equity > start * 1.001
                else "loss"
                if equity < start * 0.999
                else "waiting"
            )

        profit = sum(1 for a in self.agents if a.state.status == "profit")
        loss = sum(1 for a in self.agents if a.state.status == "loss")
        waiting = sum(1 for a in self.agents if a.state.status == "waiting")
        # Book money is Decimal; convert each book's value to float at this
        # WS-output boundary before summing so the payload is a JSON number.
        total_equity = sum(float(a.state.book.equity(marks)) for a in self.agents)
        realized = sum(float(a.state.book.realized_pnl) for a in self.agents)
        unrealized = sum(float(a.state.book.unrealized_pnl(marks)) for a in self.agents)
        last_tick_iso = self.last_tick_at.isoformat()
        await publish_event(
            "account",
            {
                "profit_ai": profit,
                "loss_ai": loss,
                "waiting_ai": waiting,
                "total_equity": total_equity,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "last_tick_at": last_tick_iso,
                "notes_this_tick": JOURNAL_COUNTERS["notes_this_tick"],
                "outcomes_this_tick": JOURNAL_COUNTERS["outcomes_this_tick"],
            },
        )
        await publish_event(
            "tick",
            {
                "fills": fills,
                "blocked": blocked,
                "symbols": len(marks),
                "last_tick_at": last_tick_iso,
            },
        )

        return {"fills": fills, "blocked": blocked, "symbols": len(marks)}

    async def _publish_fill_of_tick(
        self,
        tick_id: str,
        candidates: list[_FillMomentCandidate],
    ) -> None:
        """Emit a text-first broadcast moment for the largest meaningful fill."""
        if not candidates:
            return
        fill = max(candidates, key=lambda c: c.notional)
        if fill.notional < FILL_OF_TICK_MIN_NOTIONAL:
            return
        verb = "bought" if fill.side == "buy" else "sold"
        subtitle = (
            f"{fill.agent_name} {verb} {fill.qty:g} {fill.symbol} @ "
            f"${fill.price:.2f} (${fill.notional:,.0f})"
        )
        moment = BroadcastMoment(
            id=f"fill-of-tick-{tick_id}",
            kind="activity",
            title="Fill of the tick",
            subtitle=subtitle,
            priority=62,
            color="neutral",
            agent_id=fill.agent_id,
            trigger="fill_of_tick",
            outputs=("lower_third", "ticker", "recap_log"),
            ttl_sec=7,
            metadata={
                "symbol": fill.symbol,
                "side": fill.side,
                "qty": fill.qty,
                "price": fill.price,
                "notional": fill.notional,
                "reason": fill.reason,
            },
        )
        await publish_broadcast_moment(moment, publish=publish_event)

    async def run_scheduled(self) -> None:
        """Background loop. Sleeps outside RTH (unless tick_outside_rth=True).

        Skips the tick entirely when settings.ai_enabled is False — the master
        kill switch controlled from the admin panel.
        """
        interval = settings.auto_tick_interval_sec
        if interval <= 0:
            log.info("scheduler_disabled")
            return
        log.info(
            "scheduler_started", interval_sec=interval, allow_off_hours=settings.tick_outside_rth
        )
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
        # Audit fix: also invalidate the CommentaryLoop's cached overlay
        # so the next 45s tick rebuilds it against the new provider/key.
        # Without this, the audit's H6 fix (overlay caching) ironically
        # made the admin's reload promise less effective for commentary.
        if self._commentary_loop is not None:
            self._commentary_loop.invalidate_overlay()
        if new is None:
            return {"provider": None, "model": None}
        return dict(new.info)

    @staticmethod
    def _spawn_loop(coro: Awaitable[None], *, name: str) -> asyncio.Task:
        """Spawn a long-running loop task with an exception-logging callback.

        Issue #6: the returned task is stored by the caller, but its
        completion is also observed via a done-callback so a crash (rather
        than a clean cancel) is logged instead of surfacing as a bare
        "Task exception was never retrieved" warning.
        """
        task = asyncio.ensure_future(coro)
        task.set_name(name)
        # Issue #6: route through the shared crash-logger so scheduler /
        # reconciler core loops are supervised identically to the suite's
        # sidecar loops.
        attach_crash_logger(task, name=name)
        return task

    async def start_background(self) -> None:
        if settings.auto_tick_interval_sec > 0 and self._task is None:
            self._task = self._spawn_loop(self.run_scheduled(), name="orch_scheduler")

        if settings.execution_mode == "alpaca_paper" and self._recon_task is None:
            # Lazy import to avoid pulling alpaca-py in simulated mode.
            from tradefarm.execution.alpaca_broker import AlpacaBroker

            if isinstance(self.broker, AlpacaBroker):
                self._reconciler = OrderReconciler(self.broker, self._optimistic_marks)
                self._recon_task = self._spawn_loop(
                    self._reconcile_loop(),
                    name="orch_reconciler",
                )

        # Phase 4 — opt-in curriculum loop (0 disables).
        self.start_curriculum()

        # Issue #6: the broadcast presentation layer (sidecars + arbiter)
        # starts as a single unit. The suite installs the arbiter, then
        # constructs + awaits each sidecar's start() in dependency order
        # (predictions before audience). Awaiting (not fire-and-forget) so a
        # boot-time start() failure surfaces here instead of being swallowed.
        await self._broadcast_suite.start()

    def start_curriculum(self) -> None:
        """Start the between-ticks curriculum loop if the interval is > 0."""
        if settings.academy_eval_interval_sec > 0 and self._curriculum_task is None:
            self._curriculum_task = asyncio.create_task(
                self.run_curriculum_loop(),
                name="orch_curriculum",
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
        a tick.

        Audit fix (C9): acquires the same ``_tick_lock`` ``tick_once``
        uses. Replaces the prior poll-on-flag pattern, which had a TOCTOU
        race where a new tick could start between the flag check and the
        ``await curriculum.evaluate_all`` call — letting curriculum swap
        ``agent.risk`` mid-tick.
        """
        interval = settings.academy_eval_interval_sec
        if interval <= 0:
            return
        # Lazy-import so test fixtures can patch `curriculum` before loop runs.
        from tradefarm.academy import curriculum

        log.info("curriculum_loop_started", interval_sec=interval)
        while True:
            try:
                async with self._tick_lock:
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
                fills = await self._reconciler.poll_once()
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
                log.warning(
                    "reconciled_unknown_agent", agent_id=rf.agent_id, broker_oid=rf.broker_order_id
                )
                continue
            # Derive mark from actual+delta (delta = actual - mark) and
            # use apply_reconciled_fill so the correction is correct for
            # short opens, longs→short flips, and partial closes.
            mark_price = rf.actual_price - rf.delta
            ok = agent.state.book.apply_reconciled_fill(
                rf.symbol,
                rf.side,
                rf.qty,
                mark_price=mark_price,
                actual_price=rf.actual_price,
                broker_order_id=rf.broker_order_id,
            )
            if ok:
                applied += 1
                # Persist the reconciled fill keyed on broker_order_id. The
                # UNIQUE constraint dedupes this against the optimistic write
                # the scheduler made at submit time — so a normal run inserts
                # nothing here, but after a process restart (when the
                # in-memory optimistic row never happened) this is the row
                # that records the fill. Either way broker_order_id ends up
                # persisted exactly once: the documented restart-safe guard
                # (CLAUDE.md gotcha #7) is now live.
                await repo.record_trade(
                    rf.agent_id,
                    rf.symbol,
                    rf.side,
                    rf.qty,
                    rf.actual_price,
                    "reconciled_fill",
                    broker_order_id=rf.broker_order_id or None,
                )
                await repo.sync_positions(rf.agent_id, agent.state.book)
                # If this fill was a sell, clear the pending-exit guard
                # so the next tick can issue a fresh exit if the agent
                # opens a new position.
                if rf.side == "sell":
                    self._pending_exits.pop((rf.agent_id, rf.symbol), None)
                    # Audit fix (H19): also clear the RiskManager's
                    # trailing peak when the position has been fully
                    # closed, so a re-entry starts fresh rather than
                    # inheriting the prior cycle's peak.
                    agent_ref = self._agents_by_id.get(rf.agent_id)
                    if agent_ref is not None:
                        existing_pos = agent_ref.state.book.positions.get(rf.symbol)
                        if existing_pos is None or abs(existing_pos.qty) < 1e-9:
                            # Defensive: stub agents may lack clear_peak.
                            clear = getattr(agent_ref.risk, "clear_peak", None)
                            if callable(clear):
                                clear(rf.symbol)
                await publish_event(
                    "reconcile",
                    {
                        "agent_id": rf.agent_id,
                        "symbol": rf.symbol,
                        "side": rf.side,
                        "qty": rf.qty,
                        "delta": rf.delta,
                        "actual_price": rf.actual_price,
                    },
                )
                # Record the actual fill in the same ring buffer the
                # in-tick site writes to. In alpaca_paper mode the
                # same trade appears twice (optimistic mark at submit
                # time, actual price here) — acceptable: the cost-gate
                # keys on ``len() == 0``, not on distinct ids, and
                # the prompt lists fills newest-first regardless.
                self._recent_fills.append(
                    {
                        "agent_id": rf.agent_id,
                        "agent_name": agent.state.name,
                        "symbol": rf.symbol,
                        "side": rf.side,
                        "qty": float(rf.qty),
                        "price": float(rf.actual_price),
                        "at": _runtime_clock_now_utc(),
                    }
                )
        return applied

    async def stop_background(self) -> None:
        # Cancel the main scheduler + reconciler loops first.
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
        # Issue #6: drain the broadcast presentation layer as a unit. The
        # suite stops every sidecar first (they may still emit broadcast
        # moments during stop(), so the arbiter must still be installed),
        # then uninstalls the arbiter last — symmetric to start_background.
        await self._broadcast_suite.stop()

        # Round-5 audit fix (AA): close the shared httpx client so the
        # event-loop doesn't carry an unclosed-connection warning into
        # the next process. Idempotent + best-effort.
        from tradefarm.runtime.http import aclose_shared_client

        await aclose_shared_client()
