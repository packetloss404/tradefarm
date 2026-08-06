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
from tradefarm.agents.bollinger_bands import BollingerBandsAgent
from tradefarm.agents.donchian_breakout import DonchianBreakoutAgent
from tradefarm.agents.llm_overlay import LlmOverlay
from tradefarm.agents.lstm_agent import LstmAgent
from tradefarm.agents.lstm_llm_agent import LstmLlmAgent
from tradefarm.agents.lstm_model import model_path
from tradefarm.agents.momentum import MomentumAgent
from tradefarm.agents.names import agent_display_name
from tradefarm.agents.pairs_zscore import PairsZScoreAgent
from tradefarm.agents.rsi2 import Rsi2Agent
from tradefarm.config import settings
from tradefarm.data.pairs import pair_for_slot
from tradefarm.runtime.clock import now_utc as _runtime_clock_now_utc
from tradefarm.data.eodhd import EodhdClient
from tradefarm.data.universe import default_universe
from tradefarm.execution.broker import Broker, SimulatedBroker
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.market.hours import is_market_open
from tradefarm.market_clock import is_market_closed_for_n_minutes
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
        # 0.16.0 — Rivalry Week weekly podcast scheduler task. Same
        # shape as ``_vod_task`` (a long-lived background loop that
        # parks on an asyncio.Event() when its master switch is off).
        self._podcast_task: asyncio.Task | None = None
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
        # VOD autonomy: the daily scheduler loop runs as a sibling of
        # the main tick loop. It's a separate ``asyncio.Task`` so a
        # long render doesn't block the tick and vice versa. Gated on
        # ``settings.vod_pipeline_enabled`` (env var, default off) —
        # the operator flips the switch without a code change.
        self._vod_task: asyncio.Task | None = None
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
        # Pairs agents need a per-cohort counter so consecutive pairs slots
        # get different pairs from the hardcoded list (modulo cycling).
        pairs_slot_idx = 0

        def add_momentum(i: int, name: str, risk: RiskManager, symbol: str) -> None:
            state = AgentState(
                id=i, name=name, strategy=MomentumAgent.strategy_name, book=VirtualBook(agent_id=i, cash=D(settings.agent_starting_capital))
            )
            agents.append(MomentumAgent(state, risk, symbol=symbol))

        for i in range(settings.agent_count):
            symbol = universe[i % len(universe)]
            book = VirtualBook(agent_id=i, cash=D(settings.agent_starting_capital))
            agent_rank = rank_map.get(i, "intern")
            risk = RiskManager(
                starting_capital=settings.agent_starting_capital,
                rank=agent_rank,
            )
            has_model = model_path(symbol).exists()

            # 100-agent rotation, spread across 7 strategy slots.
            # LSTM/LSTM+LLM fall back to momentum if no trained model
            # exists on disk for the assigned symbol (or no LLM overlay
            # for the LSTM+LLM slot) — the original pre-0.7.0 behavior.
            # Keeps the sandbox runnable before any model is trained.
            slot = i % 7
            name = agent_display_name(i)
            if slot == 0:
                add_momentum(i, name, risk, symbol)
            elif slot == 1:
                if has_model:
                    state = AgentState(id=i, name=name, strategy=LstmAgent.strategy_name, book=book)
                    agents.append(LstmAgent(state, risk, symbol=symbol))
                else:
                    add_momentum(i, name, risk, symbol)
            elif slot == 2:
                if has_model and overlay is not None:
                    state = AgentState(id=i, name=name, strategy=LstmLlmAgent.strategy_name, book=book)
                    agents.append(LstmLlmAgent(state, risk, symbol=symbol, overlay=overlay))
                else:
                    add_momentum(i, name, risk, symbol)
            elif slot == 3:
                state = AgentState(id=i, name=name, strategy=BollingerBandsAgent.strategy_name, book=book)
                agents.append(BollingerBandsAgent(state, risk, symbol=symbol))
            elif slot == 4:
                state = AgentState(id=i, name=name, strategy=Rsi2Agent.strategy_name, book=book)
                agents.append(Rsi2Agent(state, risk, symbol=symbol))
            elif slot == 5:
                state = AgentState(id=i, name=name, strategy=DonchianBreakoutAgent.strategy_name, book=book)
                agents.append(DonchianBreakoutAgent(state, risk, symbol=symbol))
            else:  # slot == 6
                pair = pair_for_slot(pairs_slot_idx)
                pairs_slot_idx += 1
                state = AgentState(id=i, name=name, strategy=PairsZScoreAgent.strategy_name, book=book)
                agents.append(PairsZScoreAgent(state, risk, symbol_a=pair[0], symbol_b=pair[1]))
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

    async def _refresh_intraday_marks(
        self, symbols: list[str], marks: dict[str, float]
    ) -> None:
        """0.24.0 — replace each symbol's daily mark with the most
        recent intraday bar's close (typically <5min stale during
        RTH). Mutates ``marks`` in place. Symbols whose intraday
        fetch returns an empty frame (no subscription, weekend
        data, delisted) keep their daily mark.

        Implemented as a per-symbol coroutine that runs the fetches
        serially rather than concurrently: EODHD's /intraday endpoint
        is rate-limited per-key, and 100 parallel calls at the start
        of a tick would burn the rate budget in one go. Serial
        fetches at ~150ms each keep the tick under 20s while leaving
        headroom.
        """
        from tradefarm.runtime.clock import now_utc as _runtime_clock_now_utc

        period = settings.intraday_period
        # Look back the duration of one bar plus a small buffer; the
        # 5m period wants a 30-min window so we have ~5 bars in
        # flight. The 1h period wants a 4h window.
        if period.endswith("m"):
            minutes = int(period[:-1])
            window_min = max(30, minutes * 6)
        elif period.endswith("h"):
            hours = int(period[:-1])
            window_min = max(120, hours * 4 * 60)
        else:
            window_min = 30
        end_dt = _runtime_clock_now_utc()
        start_dt = end_dt - timedelta(minutes=window_min)
        refreshed = 0
        for sym in symbols:
            try:
                df = await self.data.get_intraday(
                    sym, start=start_dt, end=end_dt, period=period
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "intraday_fetch_failed",
                    symbol=sym,
                    error=str(exc),
                )
                continue
            if df.empty:
                continue
            last_close = float(df["close"].iloc[-1])
            if last_close > 0:
                marks[sym] = last_close
                refreshed += 1
        if refreshed:
            log.debug(
                "intraday_marks_refreshed",
                refreshed=refreshed,
                total=len(symbols),
                period=period,
            )

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
        # 0.24.0 — intraday mark path. During RTH (or when the master
        # switch ``intraday_enabled`` is on), refresh marks from the
        # most recent 5m bar instead of yesterday's daily close. The
        # 24h-stale mark was a known limitation of the daily-only path:
        # at 10:00 ET the orchestrator was reasoning on yesterday's
        # 16:00 settle, ~18h stale. A 5m intraday mark is <5min stale.
        #
        # Disabled by default (EODHD's intraday endpoint is paid-tier
        # on the free plan; the operator opts in via the env var when
        # the subscription is in place). The fall-through to the daily
        # mark keeps every existing tick's behavior unchanged when off.
        if settings.intraday_enabled:
            from tradefarm.market.hours import is_market_open as _is_market_open

            if _is_market_open():
                try:
                    await self._refresh_intraday_marks(symbols, marks)
                except Exception as exc:  # noqa: BLE001
                    # The daily mark is the source of truth; a
                    # transient intraday failure should never kill
                    # the tick. Log + continue on the daily mark.
                    log.warning("intraday_marks_refresh_failed", error=str(exc))
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

    async def _boot_vod_scheduler(self) -> None:
        """0.9.0 boot hygiene: clear ``live_today`` on stale past-date rows.

        Called once from ``start_background`` BEFORE the VOD scheduler
        task is spawned. A previous process that died mid-run
        (power loss, OOM kill, ``kill -9``) left a
        ``status='running'`` row with ``live_today=True`` for some
        past date; the new process can't inherit another process's
        "live" state — those rows are dead, and the new process's
        idempotency check (``live_pipeline_run_for_date``) must
        see them as not-live so today's run still gets a chance
        to fire.

        Today's rows are intentionally left untouched: a still-live
        row for today is genuinely from "this process" (we just
        flipped all the others to dead) and the scheduler should
        skip. If the operator wants to refire today's run, they
        call ``set_pipeline_run_live_today(run_id, False)`` from
        the admin panel.

        Returns nothing; the row count is logged on the way out
        for observability. Idempotent — a second call with the
        same ``today_iso`` is a no-op (every other row is already
        ``live_today=False``).
        """
        from tradefarm.market.hours import ET as _ET

        today = _runtime_clock_now_utc().astimezone(_ET).date().isoformat()
        flipped = await repo.mark_runs_live_today_false_for_past_dates(today_iso=today)
        if flipped:
            log.info("vod_scheduler_boot_marked_stale", flipped=flipped, today=today)
        else:
            log.debug("vod_scheduler_boot_no_stale_rows", today=today)

    async def run_vod_scheduler(self) -> None:
        """Daily VOD pipeline scheduler. Fires once per NYSE trading day,
        after the post-close cool-off (``settings.vod_market_close_offset_min``,
        default 5). Gated on ``settings.vod_pipeline_enabled`` (env var,
        default off — opt-in).

        The loop polls every minute, and each tick:

        1. Checks the master switch — if off, sleep forever (the task
           is essentially idle). The operator can flip the env var
           and bounce the process to enable.
        2. Asks ``is_market_closed_for_n_minutes(N)`` — True only on
           a real trading day, after the close, after the cool-off.
           False on weekends / holidays / pre-open / mid-session.
        3. Idempotency: looks for an existing ``pipeline_runs`` row
           for today's ISO date with ``live_today=True`` (the
           0.9.0 marker set on every new run; the boot sweep in
           ``_boot_vod_scheduler`` flipped every previous-process
           row to ``False``). If found, skip — a previous run from
           this process already covered this date. The ``status``
           column still records the terminal state, but the
           ``live_today`` flag is what gates "should I refire".
        4. Generates a fresh ``session_id`` for today's date and
           invokes the render pipeline in-process (no HTTP). The
           pipeline is fire-and-forget from the scheduler's POV —
           we kick it off on a thread and let the WS layer
           republish progress.
        5. Sleeps until tomorrow's window opens. We don't try to
           re-fire the same day on a transient failure — the
           failed row already exists for today, and the operator
           can manually re-trigger from the dashboard.

        The published ``pipeline_progress`` events are the same
        shape the HTTP endpoint emits, so the existing dashboard
        live data hook picks them up without change.
        """
        if not settings.vod_pipeline_enabled:
            log.info("vod_scheduler_disabled")
            # Block forever; the task is parked. Cancellation is
            # the only way out (from stop_background). Sleeping
            # here (rather than returning) keeps the task handle
            # valid for clean cancellation.
            await asyncio.Event().wait()
            return

        offset = settings.vod_market_close_offset_min
        log.info("vod_scheduler_started", offset_min=offset)

        # Re-check each minute. The check is cheap (a calendar lookup
        # + a tz comparison), so 60s polling is fine; the
        # alternative (sleep until the next "interesting moment")
        # is fiddly across day boundaries and DST.
        poll_sec = 60

        while True:
            try:
                fired_today = await self._maybe_fire_vod_run(offset)
                if fired_today:
                    # The run was kicked off on its own thread; we
                    # just need to wait until tomorrow's window opens
                    # so we don't re-fire the same date.
                    await self._sleep_until_next_window(offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # A transient calendar/DB error shouldn't kill the
                # loop. Log + continue; the next tick (60s later)
                # gets another shot.
                log.exception("vod_scheduler_loop_failed", error=str(exc))
            await asyncio.sleep(poll_sec)

    async def _maybe_fire_vod_run(self, offset_min: int) -> bool:
        """Return True if a run was fired today; False if not yet time
        or already done.

        Extracted from the loop body so tests can drive the
        "should I fire?" predicate without spinning the event loop.
        """
        if not is_market_closed_for_n_minutes(offset_min):
            return False

        # Use the ET date for the per-day key, not UTC. A 16:30 ET
        # close on Friday should fire under Friday's date, not
        # Saturday's UTC date.
        from tradefarm.market.hours import ET as _ET

        today = _runtime_clock_now_utc().astimezone(_ET).date().isoformat()

        # 0.9.0 idempotency check: filter on ``live_today=True`` for
        # today's date. The boot-time sweep in ``_boot_vod_scheduler``
        # has already flipped every past-date row from a previous
        # process to ``live_today=False`` (a dead process can't
        # inherit "live" state), so a row with ``live_today=True``
        # for today MUST be from the current process — no need to
        # separately check status in ('done','failed') or
        # status='running' like the v0.8 path did. Cleaner, and
        # closes the power-loss-mid-run race that v0.8 documented
        # as a known gap.
        existing = await repo.live_pipeline_run_for_date(today)
        if existing is not None:
            log.info(
                "vod_scheduler_skip_already_ran",
                date=today,
                run_id=existing.id,
                status=existing.status,
            )
            return False

        return await self._kick_vod_run(today)

    async def _kick_vod_run(self, today: str) -> bool:
        """Generate a fresh session_id for today, write a pipeline_runs
        row, and invoke the render pipeline in-process on a worker
        thread. Returns True on successful kickoff (the row was
        written); False if the row write failed (logged + dropped).
        """
        import uuid as _uuid

        from tradefarm.api.pipeline import PipelineRun as _PipelineRun
        from tradefarm.api.pipeline import (
            _fire_webhook as _fire_webhook,
        )
        from tradefarm.api.pipeline import (
            _persist_run_state as _persist,
        )
        from tradefarm.render import pipeline as _pipeline_mod

        session_id = f"s_{today}_{_uuid.uuid4().hex[:6]}"
        # Default enabled set: same shape as the HTTP wrapper's
        # "no flags" run. TTS + upload are explicit opt-in even
        # from the scheduler — the operator flips those by
        # editing the config / hitting the dashboard button.
        enabled = sorted(
            {step.key for step in _pipeline_mod.STEPS if step.enabled_by_default}
        )

        run = _PipelineRun(
            run_id=_uuid.uuid4().hex[:12],
            session_id=session_id,
            date=today,
            enabled=enabled,
            force=False,
            dry_run=False,
        )
        # Build the row for the repo (the dataclass is the in-memory
        # mirror; the repo needs the SQLAlchemy model).
        from tradefarm.storage.models import PipelineRun as _Row

        row = _Row(
            id=run.run_id,
            session_id=run.session_id,
            date=run.date,
            enabled=run.enabled,
            force=run.force,
            dry_run=run.dry_run,
            status="pending",
            created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            last_lines_json="[]",
        )
        try:
            await repo.create_pipeline_run(row)
        except Exception as exc:  # noqa: BLE001
            log.error("vod_scheduler_create_run_failed", error=str(exc), date=today)
            return False

        log.info("vod_scheduler_fired", run_id=run.run_id, session_id=session_id, date=today)
        # Publish the same start event the HTTP wrapper would emit, so
        # the dashboard's live data hook picks up the run without
        # needing to know it was started by the scheduler.
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run.run_id,
                "kind": "start",
                "session_id": run.session_id,
                "enabled": run.enabled,
                "at": run.created_at,
            },
        )

        # Invoke the pipeline on a worker thread (matches the HTTP
        # wrapper's contract — pipeline.run_pipeline is synchronous
        # and can run for minutes). The thread updates the in-memory
        # ``run`` object's status + last_lines; we mirror those back
        # to the DB at step boundaries via ``_persist_run_state``.
        async def _runner() -> None:
            # Inline mini-loop mirroring ``_run_pipeline_task`` from
            # the HTTP wrapper. We re-implement here (rather than
            # importing the helper) so the scheduler's failure path
            # can be tuned independently — and so a future move to a
            # separate worker process doesn't drag the FastAPI app's
            # HTTP layer with it.
            from datetime import datetime as _dt
            from datetime import timezone as _tz

            run.status = "running"
            run.started_at = _dt.now(_tz.utc).isoformat()
            await _persist(run)
            from pathlib import Path as _Path

            opts = _pipeline_mod.PipelineOpts(
                sessions_dir=_Path("out/sessions"),
                music=None,
                tts_provider="auto",
                tts_voice="alloy",
                upload_dry_run=True,
                stitch_xfade=0.4,
                force=False,
            )
            sink_msgs: list[str] = []
            from tradefarm.api.pipeline import _make_sink as _make_sink

            def sink(msg: str) -> None:
                sink_msgs.append(msg)
                run.last_lines.append(msg)
                if len(run.last_lines) > 200:
                    run.last_lines = run.last_lines[-200:]

            try:
                step_timings = await asyncio.to_thread(
                    _pipeline_mod.run_pipeline,
                    session_id=run.session_id,
                    opts=opts,
                    enabled=set(run.enabled),
                    force=run.force,
                    dry_run=run.dry_run,
                    sink=sink,
                    return_timings=True,
                )
                run.status = "done"
                run.finished_at = _dt.now(_tz.utc).isoformat()
                # Stash per-step timings on the dataclass; the model
                # has a matching ``step_timings_json`` column (added in
                # 0.9.0) which ``_persist`` serializes on terminal
                # state.
                run.step_timings = list(step_timings or [])
                await _persist(run)
                await publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run.run_id,
                        "kind": "done",
                        "at": run.finished_at,
                    },
                )
                _fire_webhook(run)
                # 0.10.0 — best-effort asset archival on terminal done
                # (same pattern as the HTTP wrapper's _run_pipeline_task).
                # The archive function is no-op when ``vod_archive_path``
                # is unset, so the default config never pays the cost.
                from tradefarm.render import archive as _archive_mod
                from pathlib import Path as _ArchivePath
                _archive_root = settings.vod_archive_path or None
                if _archive_root:
                    try:
                        await _archive_mod.archive_session(
                            run.session_id,
                            archive_root=_ArchivePath(_archive_root),
                            run_status=run.status,
                            also_on_failure=settings.vod_archive_on_failure,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "vod_scheduler_archive_failed",
                            run_id=run.run_id,
                            error=f"{type(exc).__name__}: {exc}",
                        )
            except SystemExit as exc:
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = _dt.now(_tz.utc).isoformat()
                await _persist(run)
                await publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run.run_id,
                        "kind": "fail",
                        "error": str(exc),
                        "at": run.finished_at,
                    },
                )
                _fire_webhook(run)
            except Exception as exc:  # noqa: BLE001
                run.status = "failed"
                run.error = f"{type(exc).__name__}: {exc}"
                run.finished_at = _dt.now(_tz.utc).isoformat()
                await _persist(run)
                await publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run.run_id,
                        "kind": "fail",
                        "error": run.error,
                        "at": run.finished_at,
                    },
                )
                _fire_webhook(run)

        # Schedule the runner on the loop. We don't await it (it runs
        # for minutes); the scheduler loop just needs to know the
        # kickoff succeeded (which it did, by the time we got here).
        asyncio.create_task(_runner())
        return True

    async def _sleep_until_next_window(self, offset_min: int) -> None:
        """Sleep until the next "market closed for N minutes" window.

        Called after a successful kickoff so the loop doesn't keep
        firing every 60s. We compute the next 04:00 ET (premarket
        start) on the following trading day and sleep until then —
        rough but correct. The 60s poll on the next iteration will
        see the cool-off has lapsed and re-evaluate.

        On weekends / holidays this just sleeps ~24h to the next
        weekday's premarket — close enough for the per-day cadence.
        """
        from datetime import timedelta as _td

        from tradefarm.market.hours import ET as _ET
        from tradefarm.runtime.clock import now_utc as _now

        now = _now().astimezone(_ET)
        # Sleep until 04:00 ET tomorrow. If it's already past 04:00
        # today (we shouldn't get here in that case, but defensive),
        # sleep until 04:00 ET tomorrow.
        next_open = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if next_open <= now:
            next_open = next_open + _td(days=1)
        delta = (next_open - now).total_seconds()
        # Cap the sleep at 24h+ a few minutes so a clock skew can't
        # put us in a long stall.
        await asyncio.sleep(min(delta, 24 * 3600 + 600))

    # ------------------------------------------------------------------
    # 0.16.0 — Rivalry Week weekly podcast scheduler. Mirrors the VOD
    # scheduler's poll-on-the-minute pattern but fires once per
    # trading week (Saturday 09:00 ET, default) instead of once per
    # day. Gated on `settings.podcast_enabled`; when False, the task
    # parks on an `asyncio.Event()` so the orchestrator can keep the
    # task handle valid for clean cancellation. Idempotency is via
    # the existing `pipeline_runs` table — the podcast stage writes
    # a row with `kind="podcast"` and the boot-time live_today
    # sweep (see `_boot_vod_scheduler`) keeps the same per-week
    # dedup contract the daily chain uses.
    # ------------------------------------------------------------------

    async def run_podcast_scheduler(self) -> None:
        """Weekly Rivalry Week podcast scheduler. Fires once per
        trading week on ``settings.podcast_fire_hour_et`` (default
        Saturday 09:00 ET) once the week's 5 daily sessions are
        settled.

        Idempotency: the per-row ``live_today`` flag is repurposed
        here — we still key on a "today" date but stamp it with the
        ISO week_id instead, so a previous process's row gets swept
        on the next boot. The composer itself is also idempotent
        (it re-uses ``episode_<week_id>.mp4`` when present), so a
        partial run on a prior process doesn't lose its work.

        Parked forever when ``settings.podcast_enabled`` is False —
        mirrors the VOD scheduler's contract. Operator flips the
        env var and bounces the process to enable.
        """
        if not settings.podcast_enabled:
            log.info("podcast_scheduler_disabled")
            # Block forever; the task is parked. Cancellation is
            # the only way out (from stop_background). Sleeping
            # here (rather than returning) keeps the task handle
            # valid for clean cancellation.
            await asyncio.Event().wait()
            return

        fire_hour = int(settings.podcast_fire_hour_et)
        log.info("podcast_scheduler_started", fire_hour_et=fire_hour)

        # Re-check each minute; cheap (a single tz comparison +
        # iso-week math). 60s polling matches the VOD scheduler.
        poll_sec = 60

        while True:
            try:
                fired = await self._maybe_fire_podcast_run(fire_hour)
                if fired:
                    # Composer runs synchronously on a worker thread
                    # (it can take 3-5 min for the LLM + TTS + ffmpeg
                    # stages). Sleep until the next 04:00 ET so we
                    # don't re-fire the same week.
                    await self._sleep_until_next_podcast_window()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("podcast_scheduler_loop_failed", error=str(exc))
            await asyncio.sleep(poll_sec)

    async def _maybe_fire_podcast_run(self, fire_hour_et: int) -> bool:
        """Return True if the weekly composer should fire right now.

        Fires when the current ET clock has reached ``fire_hour_et``
        on a Saturday (the trading week's last day, per the
        scheduler's earlier convention). The "already fired this
        week" check uses the ``pipeline_runs`` table with a
        ``kind="podcast"`` filter, matching the daily VOD
        scheduler's live_today contract.
        """

        from tradefarm.market.hours import ET as _ET
        from tradefarm.session.weekly_rollup import week_id_for

        now_et = _runtime_clock_now_utc().astimezone(_ET)
        if now_et.weekday() != 5:  # 5 = Saturday
            return False
        if now_et.hour < fire_hour_et:
            return False

        week_id = week_id_for(now_et.date())
        existing = await repo.live_podcast_run_for_week(week_id)
        if existing is not None:
            log.info(
                "podcast_scheduler_skip_already_ran",
                week_id=week_id,
                run_id=existing.id,
                status=existing.status,
            )
            return False
        return await self._kick_podcast_run(week_id, now_et)

    async def _kick_podcast_run(self, week_id: str, now_et: Any) -> bool:
        """Spawn the weekly composer on a worker thread. Mirrors
        ``_kick_vod_run``'s shape (row write + thread kickoff) but
        the underlying composer is the new ``render.podcast``
        module, not the 9-step daily chain."""
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        import uuid as _uuid

        from tradefarm.storage.models import PipelineRun as _Row

        run_id = _uuid.uuid4().hex[:12]
        try:
            row = _Row(
                id=run_id,
                # The synthetic session_id is the discriminator
                # the new ``live_podcast_run_for_week`` repo helper
                # uses; mirrors the ``s_<date>_<hex>`` pattern the
                # daily VOD scheduler writes.
                session_id=f"podcast_{week_id}",
                date=now_et.date().isoformat(),
                enabled=["podcast"],
                force=False,
                dry_run=False,
                status="pending",
                created_at=_dt.now(_tz.utc),
                last_lines_json="[]",
            )
            await repo.create_pipeline_run(row)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "podcast_scheduler_create_run_failed",
                error=str(exc),
                week_id=week_id,
            )
            return False

        log.info(
            "podcast_scheduler_fired",
            run_id=run_id,
            week_id=week_id,
            fire_hour_et=int(settings.podcast_fire_hour_et),
        )
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run_id,
                "kind": "start",
                "session_id": f"podcast_{week_id}",
                "week_id": week_id,
                "at": now_et.isoformat(),
            },
        )

        async def _runner() -> None:
            # The composer is sync; we run it on a worker thread so
            # the scheduler's poll loop isn't blocked. Mirrors
            # `_kick_vod_run`'s thread pattern.
            from datetime import datetime as _dt2
            from datetime import timezone as _tz2

            from tradefarm.api.pipeline import (
                PipelineRun as _PipelineRun,
            )
            from tradefarm.api.pipeline import (
                _fire_webhook as _fire_webhook,
            )
            from tradefarm.api.pipeline import (
                _persist_run_state as _persist,
            )
            from tradefarm.render import podcast as _podcast_mod

            run = _PipelineRun(
                run_id=run_id,
                session_id=f"podcast_{week_id}",
                date=now_et.date().isoformat(),
                enabled=["podcast"],
                force=False,
                dry_run=False,
            )
            run.status = "running"
            run.started_at = _dt2.now(_tz2.utc).isoformat()
            await _persist(run)
            sink_msgs: list[str] = []
            run.last_lines = []

            def sink(msg: str) -> None:
                sink_msgs.append(msg)
                run.last_lines.append(msg)
                if len(run.last_lines) > 200:
                    run.last_lines = run.last_lines[-200:]

            try:
                ep_path = await asyncio.to_thread(
                    _podcast_mod.compose_weekly_episode,
                    week_id,
                    voice=settings.podcast_voice,
                    provider=settings.podcast_tts_provider,
                )
                sink(f"compose_weekly_episode: {ep_path}")
                run.status = "done"
                run.finished_at = _dt2.now(_tz2.utc).isoformat()
                run.step_timings = [
                    {
                        "step": "podcast",
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                        "duration_sec": 0.0,
                        "status": "done",
                    }
                ]
                await _persist(run)
                await publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run_id,
                        "kind": "done",
                        "week_id": week_id,
                        "at": run.finished_at,
                    },
                )
                _fire_webhook(run)
            except SystemExit as exc:
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = _dt2.now(_tz2.utc).isoformat()
                await _persist(run)
                await publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run_id,
                        "kind": "fail",
                        "error": str(exc),
                        "week_id": week_id,
                        "at": run.finished_at,
                    },
                )
                _fire_webhook(run)
            except Exception as exc:  # noqa: BLE001
                run.status = "failed"
                run.error = f"{type(exc).__name__}: {exc}"
                run.finished_at = _dt2.now(_tz2.utc).isoformat()
                await _persist(run)
                await publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run_id,
                        "kind": "fail",
                        "error": run.error,
                        "week_id": week_id,
                        "at": run.finished_at,
                    },
                )
                _fire_webhook(run)

        asyncio.create_task(_runner())
        return True

    async def _sleep_until_next_podcast_window(self) -> None:
        """Sleep until the next Saturday 04:00 ET after a successful
        composer run so the loop doesn't re-fire the same week.

        04:00 ET is the premarket-start sentinel; the next Saturday
        is the +1-week window. If the operator wants a same-week
        retry they can manually re-trigger from the dashboard
        (the composer's idempotency handles the on-disk re-run).
        """
        from datetime import timedelta as _td

        from tradefarm.market.hours import ET as _ET

        now = _runtime_clock_now_utc().astimezone(_ET)
        days_ahead = (5 - now.weekday()) % 7  # 5 = Saturday
        if days_ahead == 0:
            days_ahead = 7
        next_open = (now + _td(days=days_ahead)).replace(
            hour=4, minute=0, second=0, microsecond=0
        )
        delta = (next_open - now).total_seconds()
        # Cap at 8d so a clock skew can't put us in a long stall.
        await asyncio.sleep(min(delta, 8 * 24 * 3600))

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

        # 0.9.0 — VOD scheduler boot hygiene. Run BEFORE the
        # scheduler task is spawned: flip every ``live_today=True``
        # row whose ``date`` is not today to False so a previous
        # process that died mid-run can't fool this process's
        # idempotency check. The check is cheap (a single
        # ``UPDATE pipeline_runs SET live_today = 0 WHERE date !=
        # today AND live_today = 1``) and the new boot is
        # asynchronous with respect to the scheduler task, so a
        # long boot doesn't block the tick loop.
        await self._boot_vod_scheduler()

        # VOD autonomy: spawn the daily scheduler loop regardless of
        # whether the operator has enabled it — the loop itself
        # parks on an asyncio.Event() when the master switch is off.
        # Doing it this way means the operator can flip the env var
        # and bounce the process to enable, without the orchestrator
        # having to be re-instantiated.
        if self._vod_task is None:
            self._vod_task = self._spawn_loop(self.run_vod_scheduler(), name="orch_vod")

        # 0.16.0 — Rivalry Week weekly podcast scheduler. Same
        # gating contract as the VOD scheduler: spawn unconditionally
        # and let the loop park itself when settings.podcast_enabled
        # is False. The operator flips the env var + bounces the
        # process to enable.
        if self._podcast_task is None:
            self._podcast_task = self._spawn_loop(
                self.run_podcast_scheduler(), name="orch_podcast"
            )

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

        # 0.16.0 — spawn the 4pm ET live recap scheduler. Lives on the
        # suite (not the orchestrator's VOD/tick loops) because it
        # publishes into the same broadcast arbiter the sidecars use.
        # The loop itself is a sibling of the existing _task / _vod_task
        # / _recon_task, with its own done-callback crash logger.
        await self._broadcast_suite.start_daily_recap_scheduler()

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
        # Cancel the main scheduler + reconciler + VOD + podcast loops.
        for t in (self._task, self._recon_task, self._vod_task, self._podcast_task):
            if t is None:
                continue
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._recon_task = None
        self._vod_task = None
        self._podcast_task = None
        await self.stop_curriculum()
        # Issue #6: drain the broadcast presentation layer as a unit. The
        # suite stops every sidecar first (they may still emit broadcast
        # moments during stop(), so the arbiter must still be installed),
        # then uninstalls the arbiter last — symmetric to start_background.
        await self._broadcast_suite.stop()
        # 0.16.0 — cancel the 4pm ET live recap poll loop. Symmetric to
        # the spawn in start_background; safe to call when the loop was
        # never started (the helper is idempotent).
        await self._broadcast_suite.stop_daily_recap_scheduler()

        # Round-5 audit fix (AA): close the shared httpx client so the
        # event-loop doesn't carry an unclosed-connection warning into
        # the next process. Idempotent + best-effort.
        from tradefarm.runtime.http import aclose_shared_client

        await aclose_shared_client()
