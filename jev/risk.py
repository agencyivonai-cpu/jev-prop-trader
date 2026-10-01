from datetime import datetime
from decimal import Decimal, InvalidOperation
from .profiles import TOPSTEP_50K
from .types import AuthorizedOrder, RiskDecision


class RiskGate:
    def __init__(self, registry, profile=TOPSTEP_50K):
        self.registry = registry
        self.profile = profile

    def authorize(self, candidate, account, now):
        """Pure deterministic check. Invalid/missing evidence always denies."""
        try:
            return self._authorize(candidate, account, now)
        except (AttributeError, TypeError, ValueError, InvalidOperation, OverflowError):
            return RiskDecision("invalid_input")

    def _authorize(self, c, a, now):
        p = self.profile
        deny = lambda reason: RiskDecision(reason)
        spec = self.registry.get(c.model)
        limits = (p.tick_size, p.tick_value, p.trade_risk, p.daily_loss,
                  p.internal_drawdown, p.min_rr, p.cost_reserve_per_contract,
                  p.min_stop_ticks, p.max_stop_ticks)
        if (any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in limits)
                or any(type(v) is not int or v <= 0 for v in
                       (p.max_contracts, p.firm_max_micro_contracts, p.max_trades,
                        p.max_consecutive_losses, p.max_age_seconds))):
            return deny("invalid_profile")
        if p.min_stop_ticks > p.max_stop_ticks:
            return deny("invalid_profile")
        if spec is None:
            return deny("unregistered_model")
        if c.symbol != p.symbol or not c.candidate_id:
            return deny("invalid_instrument_or_id")
        for ts in (now, c.timestamp, a.timestamp):
            if not isinstance(ts, datetime) or ts.utcoffset() is None:
                return deny("timezone_required")
        if any(not 0 <= (now - ts).total_seconds() <= p.max_age_seconds
               for ts in (c.timestamp, a.timestamp)):
            return deny("stale_or_future_input")
        values = (c.entry, c.stop, c.target, a.equity, a.day_open_equity,
                  a.high_water_equity, a.mll_floor)
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
            return deny("non_finite_input")
        counts = (a.trades_today, a.consecutive_losses, a.open_contracts, a.pending_contracts)
        if any(type(n) is not int or n < 0 for n in counts):
            return deny("invalid_account_state")
        if a.reconciled is not True or a.halted is not False or not a.session_id:
            return deny("unreconciled_or_halted")
        if a.high_water_equity < a.equity or a.day_open_equity <= 0:
            return deny("invalid_account_state")
        if a.open_contracts or a.pending_contracts:
            return deny("exposure_exists")
        if a.trades_today >= p.max_trades or a.consecutive_losses >= p.max_consecutive_losses:
            return deny("stop_day")
        if any(v <= 0 or v % p.tick_size != 0 for v in (c.entry, c.stop, c.target)):
            return deny("invalid_tick_price")
        geometry = ((c.direction == "long" and c.stop < c.entry < c.target) or
                    (c.direction == "short" and c.target < c.entry < c.stop))
        if not geometry:
            return deny("invalid_geometry")
        risk = abs(c.entry - c.stop)
        if not p.min_stop_ticks <= risk / p.tick_size <= p.max_stop_ticks:
            return deny("invalid_stop_distance")
        if abs(c.target - c.entry) / risk < p.min_rr:
            return deny("insufficient_rr")
        # Floor is explicit reconciled account evidence, never inferred from intraday peak.
        # Strictly retain room above the firm's breach boundary after worst-case cost reserve.
        budget = min(spec.risk_usd, p.trade_risk,
                     p.daily_loss - max(Decimal(0), a.day_open_equity - a.equity),
                     p.internal_drawdown - (a.high_water_equity - a.equity),
                     a.equity - a.mll_floor - p.tick_value)
        per_contract = risk / p.tick_size * p.tick_value + p.cost_reserve_per_contract
        qty = min(p.max_contracts, p.firm_max_micro_contracts, int(budget / per_contract))
        if qty <= 0:
            return deny("risk_budget_exhausted")
        return RiskDecision("authorized", AuthorizedOrder(c, qty, per_contract * qty))
