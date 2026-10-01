from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Topstep50K:
    """Combine reference limits plus deliberately stricter research limits."""
    initial_balance: D = D("50000")
    profit_target: D = D("3000")
    maximum_loss_limit: D = D("2000")
    firm_max_micro_contracts: int = 50
    symbol: str = "MNQ"
    tick_size: D = D("0.25")
    tick_value: D = D("0.50")
    trade_risk: D = D("60")
    daily_loss: D = D("200")
    internal_drawdown: D = D("800")
    max_contracts: int = 3
    max_trades: int = 3
    max_consecutive_losses: int = 2
    min_rr: D = D("2")
    min_stop_ticks: D = D("40")
    max_stop_ticks: D = D("80")
    cost_reserve_per_contract: D = D("3")
    max_age_seconds: int = 60


TOPSTEP_50K = Topstep50K()
