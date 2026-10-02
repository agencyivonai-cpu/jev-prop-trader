"""Shared candidates, immutable filters, deterministic risk and simulated execution."""
import hashlib
import json
import math
from types import MappingProxyType
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, time
from decimal import Decimal as D
from enum import Enum

from ..profiles import TOPSTEP_50K
from ..registry import Registry, ModelSpec
from ..research import ET, ResearchConfig
from ..risk import RiskGate
from ..types import AccountSnapshot
from .market import HYPOTHESES, validate_sessions
from .statistics import summarize, calibration


class FilterAction(str, Enum):
    APPROVE = "APPROVE"
    STAND_ASIDE = "STAND_ASIDE"


@dataclass(frozen=True)
class FilterDecision:
    action: FilterAction
    reason: str
    probability_action: float | None = None
    probability_win: float | None = None
    confidence: float | None = None

    def __post_init__(self):
        if type(self.action) is not FilterAction or not isinstance(self.reason, str):
            raise ValueError("Only APPROVE/STAND_ASIDE are permitted")
        for p in (self.probability_action, self.probability_win):
            if p is not None and (isinstance(p, bool) or not math.isfinite(p) or not 0 <= p <= 1):
                raise ValueError("Invalid explicit probability")
        if self.confidence is not None and not math.isfinite(self.confidence):
            raise ValueError("Invalid confidence")


def digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def opportunity_digest(o):
    return digest(dict(candidate=asdict(o.candidate), features=dict(o.features)))


@dataclass(frozen=True)
class RecordedJEV:
    """Replay frozen model decisions bound to exact candidate+causal feature hashes.

    A plain ID alone cannot authorize anything. Logs must declare model version,
    action probability separately from P(win), and decision time before next open.
    """
    records: object
    model_version: str
    fingerprint: str

    def __init__(self, records, model_version):
        if not model_version:
            raise ValueError("Model version required")
        copied = {k: dict(v) for k,v in records.items()}
        object.__setattr__(self, "model_version", model_version)
        object.__setattr__(self, "records", MappingProxyType({k:MappingProxyType(v) for k,v in copied.items()}))
        object.__setattr__(self, "fingerprint", digest(dict(records=copied, model_version=model_version)))

    def __call__(self, o):
        row = self.records.get(o.candidate.candidate_id)
        if row is None:
            return FilterDecision(FilterAction.STAND_ASIDE, "missing_jev_decision")
        permitted = {"candidate_digest", "decision_time", "action", "reason",
                     "probability_action", "probability_win", "confidence"}
        if set(row) - permitted or row.get("candidate_digest") != opportunity_digest(o):
            raise ValueError("Modified trade or mismatched evidence")
        from datetime import datetime
        ts = datetime.fromisoformat(row["decision_time"])
        if ts.utcoffset() is None or ts != o.candidate.timestamp:
            raise ValueError("Decision not available at scheduled next open")
        return FilterDecision(FilterAction(row["action"]), row["reason"], row.get("probability_action"),
                              row.get("probability_win"), row.get("confidence"))


def rule_filter(o):
    f = o.features
    c = o.candidate
    sign = D(1) if c.direction == "long" else D(-1)
    # Frozen, interpretable control. No fitted threshold search.
    allowed = (f["relative_volume_tod"] is not None and f["relative_volume_tod"] >= D("1.2")
               and f["body_fraction"] >= D("0.5")
               and sign*f["higher_timeframe_trend"] > 0)
    return FilterDecision(FilterAction.APPROVE if allowed else FilterAction.STAND_ASIDE, "frozen_rule_control")


@dataclass(frozen=True)
class FeatureRule:
    feature: str
    operator: str
    value: object


class FeatureRuleFilter:
    """Preregisterable ORB feature ablations; each rule is an explicit falsifiable filter."""
    allowed_features = {"higher_timeframe_trend", "opening_range_atr", "extension_atr", "relative_volume_tod",
                        "body_fraction", "wick_fraction", "prior_level_tests", "overnight_gap_atr",
                        "prior_day_proximity_atr", "round_number_proximity_atr", "volatility_regime", "time_of_day"}

    def __init__(self, rules):
        self.rules = tuple(rules)
        if any(type(r) is not FeatureRule or r.feature not in self.allowed_features
               or r.operator not in (">=", "<=", "==") for r in self.rules):
            raise ValueError("Unregistered feature or operator")
        self.fingerprint = digest([asdict(r) for r in self.rules])

    def __call__(self, o):
        import operator
        compare = {">=":operator.ge, "<=":operator.le, "==":operator.eq}
        passed = True
        for r in self.rules:
            observed = o.features.get(r.feature)
            if observed is None:
                return FilterDecision(FilterAction.STAND_ASIDE, "missing_rule_feature")
            try:
                value = D(str(r.value)) if isinstance(observed, (D,int)) else r.value
                passed &= bool(compare[r.operator](observed, value))
            except (ValueError, TypeError, ArithmeticError):
                return FilterDecision(FilterAction.STAND_ASIDE, "invalid_rule_feature")
        return FilterDecision(FilterAction.APPROVE if passed else FilterAction.STAND_ASIDE, "preregistered_feature_rules")


def registry():
    return Registry(ModelSpec(h.name, D(60)) for h in HYPOTHESES)


def initial_account(ts, day):
    return AccountSnapshot(ts, day, D(50000), D(50000), D(50000), D(48000), 0, 0, 0, 0, True)


def simulate_order(order, rows, config, *, fold):
    """Reference next-open entry only. Complete valid sessions are required upstream."""
    c = order.candidate
    start = next((i for i, b in enumerate(rows) if b.timestamp == c.timestamp), None)
    if start is None:
        return None, "missing_entry_bar"
    b = rows[start]
    if b.open != c.entry:
        return None, "next_open_price_changed"
    sign = D(1) if c.direction == "long" else D(-1)
    entry = b.open+sign*config.slippage_ticks*D(".25")
    exit_reference = None
    reason, ambiguous, gap = None, False, False
    for index, b in enumerate(rows[start:start+config.max_hold_bars], start):
        stop = b.low <= c.stop if sign > 0 else b.high >= c.stop
        target = b.high >= c.target if sign > 0 else b.low <= c.target
        if stop:
            exit_reference = min(c.stop, b.open) if sign > 0 else max(c.stop, b.open)
            reason, ambiguous, gap = "stop", target, exit_reference != c.stop
        elif target:
            exit_reference, reason = c.target, "target"
        elif index-start+1 == config.max_hold_bars or b.timestamp.astimezone(ET).time() == time(15, 59):
            exit_reference, reason = b.close, "timeout_or_session_close"
        if exit_reference is not None:
            break
    if exit_reference is None:
        return None, "incomplete_horizon"
    exit_price = exit_reference-sign*config.slippage_ticks*D(".25")
    multiplier = D(2)
    qty = order.contracts
    gross = (exit_reference-c.entry)*sign*multiplier*qty
    slippage = D(2)*config.slippage_ticks*D(".5")*qty
    commission = config.commission*qty
    return dict(candidate=asdict(c), candidate_id=c.candidate_id, session=rows[start].timestamp.astimezone(ET).date().isoformat(),
                fold=fold, signal_time=c.timestamp.isoformat(), entry_time=rows[start].timestamp.isoformat(),
                exit_bar_time=b.timestamp.isoformat(), exit_time=(b.timestamp+timedelta(minutes=1)).isoformat(),
                entry=str(entry), exit=str(exit_price), entry_reference=str(c.entry), exit_reference=str(exit_reference),
                contracts=qty, initial_risk=str(abs(c.entry-c.stop)*multiplier*qty),
                authorized_risk=str(order.risk_usd), multiplier=str(multiplier),
                gross_pnl=str(gross), commission=str(commission), slippage=str(slippage),
                net_pnl=str(gross-slippage-commission), exit_reason=reason,
                stop_target_ambiguous=ambiguous, adverse_stop_gap=gap), "filled"


def run_arms(opportunities, sessions, *, config=ResearchConfig(), jev=None, rule=None, fold="validation"):
    """Same opportunities; independent account paths. No outcome ever passed to filters."""
    arms = {name: dict(ledger=[], trades=[], accepted=[], rejected=[], available=name != "JEV" or jev is not None)
            for name in ("RAW", "RULE", "JEV")}
    gate = RiskGate(registry())
    accounts, busy = {}, {}
    shadow = {}
    filter_invalid = False
    validated, market_audit = validate_sessions([b for rows in sessions.values() for b in rows])
    market_valid = market_audit["status"] == "PASS" and set(validated) == set(sessions)
    unique_candidates = len({o.candidate.candidate_id for o in opportunities}) == len(opportunities)
    for o in opportunities:
        c = o.candidate
        if (not market_valid or not unique_candidates or o.session not in sessions or o.observed_through > c.timestamp
                or o.features.get("observed_through", c.timestamp) > c.timestamp
                or any("future" in k or "outcome" in k for k in o.features)):
            filter_invalid = True
            for arm in arms.values():
                arm["ledger"].append(dict(candidate_id=c.candidate_id, action="SKIP",
                                          reason="invalid_market_data" if not market_valid else
                                                 "duplicate_candidate" if not unique_candidates else "future_feature_access"))
            continue
        # Decisions are collected before any counterfactual outcome is evaluated.
        decisions = {"RAW": FilterDecision(FilterAction.APPROVE, "raw_mechanical"), "RULE": (rule or rule_filter)(o)}
        try:
            result = jev(o) if jev else FilterDecision(FilterAction.STAND_ASIDE, "missing_jev_filter")
            if type(result) is not FilterDecision:
                raise ValueError("JEV must return the immutable filter schema only")
            decisions["JEV"] = result
        except Exception:
            decisions["JEV"] = FilterDecision(FilterAction.STAND_ASIDE, "invalid_jev_payload")
            filter_invalid = True
        # One-contract potential outcome shared by every arm. No account path selection.
        base = initial_account(c.timestamp, o.session)
        authorization = gate.authorize(c, base, c.timestamp)
        if authorization.allowed:
            fixed = replace(authorization.order, contracts=1,
                            risk_usd=abs(c.entry-c.stop)*D(2)+TOPSTEP_50K.cost_reserve_per_contract)
            potential, why = simulate_order(fixed, sessions[o.session], config, fold=fold)
        else:
            potential, why = None, authorization.reason
        shadow[c.candidate_id] = potential
        for name, arm in arms.items():
            decision = decisions[name]
            if name == "JEV" and decision.reason in ("missing_jev_decision", "missing_jev_filter", "invalid_jev_payload"):
                arm["available"] = False
            accepted = decision.action == FilterAction.APPROVE
            arm["accepted" if accepted else "rejected"].append(c.candidate_id)
            row = dict(candidate_id=c.candidate_id, candidate_digest=opportunity_digest(o),
                       candidate=asdict(c), features=dict(o.features), observed_through=o.observed_through.isoformat(),
                       filter=asdict(decision), action="SKIP", reason=decision.reason, session=o.session,
                       counterfactual_resolved=potential is not None)
            arm["ledger"].append(row)
            if not accepted:
                continue
            if name not in accounts:
                accounts[name] = initial_account(c.timestamp, o.session)
            a = accounts[name]
            if a.session_id != o.session:
                a = replace(a, session_id=o.session, day_open_equity=a.equity,
                            trades_today=0, consecutive_losses=0)
            a = replace(a, timestamp=c.timestamp)
            accounts[name] = a
            if name in busy and c.timestamp < busy[name]:
                row["reason"] = "exposure_exists"
                continue
            check = gate.authorize(c, a, c.timestamp)
            row["riskgate_reason"] = check.reason
            if not check.allowed:
                row["reason"] = check.reason
                row["action"] = "STOP_DAY" if check.reason in ("stop_day", "risk_budget_exhausted") else "SKIP"
                continue
            trade, why = simulate_order(check.order, sessions[o.session], config, fold=fold)
            row["reason"] = why
            if trade is None:
                continue
            row["action"] = "TRADE"
            trade["observed_through"] = o.observed_through.isoformat()
            trade["features_digest"] = opportunity_digest(o)
            trade["arm"] = name
            arm["trades"].append(trade)
            # Future result updates are inaccessible until busy horizon has ended.
            busy[name] = rows_end = datetime.fromisoformat(trade["exit_time"])
            equity = a.equity+D(trade["net_pnl"])
            accounts[name] = replace(a, timestamp=rows_end, equity=equity,
                                     high_water_equity=max(a.high_water_equity, equity),
                                     trades_today=a.trades_today+1,
                                     consecutive_losses=a.consecutive_losses+1 if D(trade["net_pnl"]) < 0 else 0)
    raw_potentials = [t for t in shadow.values() if t is not None]
    raw_ev = summarize(raw_potentials)["net"]["expectancy"]
    for name, arm in arms.items():
        accepted = [shadow[i] for i in arm["accepted"] if shadow.get(i) is not None]
        rejected = [shadow[i] for i in arm["rejected"] if shadow.get(i) is not None]
        ea, er = summarize(accepted)["net"]["expectancy"], summarize(rejected)["net"]["expectancy"]
        observations = []
        for row in arm["ledger"]:
            t = shadow.get(row["candidate_id"])
            if t is not None:
                observations.append(dict(won=int(D(t["net_pnl"])>0), action=row["filter"]["action"].value, **{k: row["filter"][k]
                                         for k in ("probability_win", "probability_action", "confidence")}))
        arm.update(metrics=summarize(arm["trades"]), selection=dict(
            number_candidates=len(opportunities), number_executed=len(arm["trades"]),
            acceptance_rate=len(arm["accepted"])/len(opportunities) if opportunities else None,
            stand_aside_rate=len(arm["rejected"])/len(opportunities) if opportunities else None,
            accepted_resolved=len(accepted), rejected_resolved=len(rejected),
            unresolved=len(opportunities)-len(raw_potentials), ev_accepted=ea, ev_rejected=er, ev_raw=raw_ev,
            selection_uplift=ea-raw_ev if ea is not None and raw_ev is not None else None,
            accepted_minus_rejected=ea-er if ea is not None and er is not None else None,
            unit="one_contract_net_counterfactual", overlapping_shadow_trades=True),
            calibration=calibration(observations))
    return dict(arms=arms, filter_valid=not filter_invalid, market_audit=market_audit,
                candidate_set_digest=digest([opportunity_digest(o) for o in opportunities]),
                candidate_ids=[o.candidate.candidate_id for o in opportunities],
                shadow=shadow, session_ids=list(sessions))
