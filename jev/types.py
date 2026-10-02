from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Action(str, Enum):
    TRADE = "TRADE"
    WAIT = "WAIT"
    SKIP = "SKIP"
    STOP_DAY = "STOP_DAY"


@dataclass(frozen=True)
class SignalCandidate:
    candidate_id: str
    model: str
    symbol: str
    timestamp: datetime
    direction: str
    entry: Decimal
    stop: Decimal
    target: Decimal


@dataclass(frozen=True)
class Proposal:
    action: Action
    candidate_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class AccountSnapshot:
    timestamp: datetime
    session_id: str
    equity: Decimal
    day_open_equity: Decimal
    high_water_equity: Decimal
    mll_floor: Decimal
    trades_today: int
    consecutive_losses: int
    open_contracts: int
    pending_contracts: int
    reconciled: bool
    halted: bool = False


@dataclass(frozen=True)
class AuthorizedOrder:
    candidate: SignalCandidate
    contracts: int
    risk_usd: Decimal


@dataclass(frozen=True)
class RiskDecision:
    reason: str
    order: AuthorizedOrder | None = None

    @property
    def allowed(self):
        return self.order is not None
