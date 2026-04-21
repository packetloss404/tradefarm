from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.risk.manager import RiskManager

Side = Literal["buy", "sell"]


@dataclass
class Signal:
    symbol: str
    side: Side
    qty: float
    reason: str = ""


@dataclass
class AgentState:
    id: int
    name: str
    strategy: str
    status: str = "waiting"  # waiting | trading | profit | loss
    book: VirtualBook = field(default=None)  # type: ignore[assignment]


class Agent(ABC):
    """Base class. Subclass and implement `decide()`."""

    strategy_name: str = "base"

    def __init__(self, state: AgentState, risk: RiskManager) -> None:
        self.state = state
        self.risk = risk
        # Scratchpad for the journal: the last entry note id written by
        # `decide()`. Phase 1 doesn't consume it yet (close stamping matches
        # on (agent, symbol) + oldest-unstamped-entry), but later phases may.
        self.journal_note_id: int | None = None

    @abstractmethod
    async def decide(self, bars: dict[str, pd.DataFrame], marks: dict[str, float]) -> list[Signal]:
        ...

    def on_fill(self, symbol: str, side: Side, qty: float, price: float) -> float:
        """Apply the fill to the agent's virtual book. Returns the realized
        PnL from this fill (zero for openings, non-zero when the fill closes
        or flips part/all of the position).
        """
        return self.state.book.record_fill(symbol, side, qty, price)
