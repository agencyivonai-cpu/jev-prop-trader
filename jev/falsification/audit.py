"""Independent mechanical verifier: recompute fills/costs without simulator calls."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, time
from decimal import Decimal as D

from ..research import ET, valid_bar
from ..risk import RiskGate
from .simulation import initial_account, registry, opportunity_digest


def audit_trades(trades, opportunities, sessions, config, *, fold, family="ohlcv", signed_delta_verified=False):
    errors, notices = [], []
    lookup = {o.candidate.candidate_id: o for o in opportunities}
    account = None
    previous_exit = None
    seen = set()
    for t in trades:
        issues = []
        try:
            o = lookup[t["candidate_id"]]
            c = o.candidate
            if t["candidate_id"] in seen:
                issues.append("duplicate_trade")
            seen.add(t["candidate_id"])
            if t["candidate"] != asdict(c) or t["features_digest"] != opportunity_digest(o):
                issues.append("candidate_or_feature_modified")
            if (o.observed_through > c.timestamp or datetime.fromisoformat(t["observed_through"]) > c.timestamp
                    or o.features["observed_through"] > c.timestamp
                    or any("future" in k or "outcome" in k for k in o.features)):
                issues.append("lookahead_or_future_feature")
            if t["fold"] != fold or t["session"] not in sessions:
                issues.append("forbidden_fold_boundary")
            if family == "order_flow" and not signed_delta_verified:
                issues.append("unverified_signed_volume")
            bars = sessions[t["session"]]
            if any(not valid_bar(b) for b in bars):
                issues.append("invalid_market_data")
            if len(bars) != 390 or any(b.timestamp-a.timestamp != timedelta(minutes=1) for a, b in zip(bars, bars[1:])):
                issues.append("missing_or_duplicate_bars")
            start = next(i for i, b in enumerate(bars) if b.timestamp.isoformat() == t["entry_time"])
            end = next(i for i, b in enumerate(bars) if b.timestamp.isoformat() == t["exit_bar_time"])
            if start <= 0 or end < start or t["signal_time"] != c.timestamp.isoformat():
                issues.append("impossible_or_same_bar_fill")
            if bars[start-1].timestamp+timedelta(minutes=1) != c.timestamp or bars[start].timestamp != c.timestamp:
                issues.append("same_bar_information_fill")
            if bars[start].open != c.entry:
                issues.append("impossible_entry")
            if previous_exit and bars[start].timestamp < previous_exit:
                issues.append("overlapping_exposure")
            if bars[start].timestamp.astimezone(ET).date() != bars[end].timestamp.astimezone(ET).date():
                issues.append("forbidden_session_boundary")
            # Independent first-touch reconstruction, conservative ambiguity and gap handling.
            sign = D(1) if c.direction == "long" else D(-1)
            expected_end, reference, reason = None, None, None
            ambiguity = gap = False
            for j in range(start, min(start+config.max_hold_bars, len(bars))):
                b = bars[j]
                stop = b.low <= c.stop if sign > 0 else b.high >= c.stop
                target = b.high >= c.target if sign > 0 else b.low <= c.target
                if stop:
                    reference = min(b.open, c.stop) if sign > 0 else max(b.open, c.stop)
                    reason, ambiguity, gap = "stop", target, reference != c.stop
                elif target:
                    reference, reason = c.target, "target"
                elif j-start+1 == config.max_hold_bars or b.timestamp.astimezone(ET).time() == time(15, 59):
                    reference, reason = b.close, "timeout_or_session_close"
                if reference is not None:
                    expected_end = j
                    break
            if expected_end != end or reason != t["exit_reason"]:
                issues.append("impossible_exit_or_ambiguity")
            if t["stop_target_ambiguous"] != ambiguity or t["adverse_stop_gap"] != gap:
                issues.append("unreported_ambiguity_or_gap")
            if ambiguity:
                notices.append(dict(candidate_id=c.candidate_id, issue="stop_first_ambiguity"))
            if gap:
                notices.append(dict(candidate_id=c.candidate_id, issue="adverse_stop_gap_charged"))
            if reference is None:
                raise ValueError("Unresolved exit")
            qty = t["contracts"]
            if type(qty) is not int or qty <= 0:
                issues.append("invalid_size")
            if account is None:
                account = initial_account(c.timestamp, t["session"])
            if account.session_id != t["session"]:
                account = replace(account, session_id=t["session"], day_open_equity=account.equity,
                                  trades_today=0, consecutive_losses=0)
            account = replace(account, timestamp=c.timestamp)
            authorized = RiskGate(registry()).authorize(c, account, c.timestamp)
            if not authorized.allowed or authorized.order.contracts != qty:
                issues.append("riskgate_bypass_or_wrong_size")
            elif D(t["authorized_risk"]) != authorized.order.risk_usd:
                issues.append("risk_modified")
            entry = c.entry+sign*D(".25")*config.slippage_ticks
            exit_price = reference-sign*D(".25")*config.slippage_ticks
            gross = (reference-c.entry)*sign*D(2)*qty
            commission = config.commission*qty
            slip = D(1)*config.slippage_ticks*qty  # two sides at $0.50/tick
            checks = {"entry": entry, "exit": exit_price, "entry_reference": c.entry,
                      "exit_reference": reference, "multiplier": D(2), "gross_pnl": gross,
                      "commission": commission, "slippage": slip, "net_pnl": gross-commission-slip,
                      "initial_risk": abs(c.entry-c.stop)*D(2)*qty}
            for key, expected in checks.items():
                if D(t[key]) != expected:
                    issues.append("incorrect_"+key)
            if datetime.fromisoformat(t["exit_time"]) != bars[end].timestamp+timedelta(minutes=1):
                issues.append("wrong_exit_information_time")
            # Reconciliation uses independently recomputed net costs, not claimed P&L.
            equity = account.equity+gross-commission-slip
            account = replace(account, equity=equity, high_water_equity=max(account.high_water_equity, equity),
                              trades_today=account.trades_today+1,
                              consecutive_losses=account.consecutive_losses+1 if gross-commission-slip < 0 else 0)
            previous_exit = bars[end].timestamp+timedelta(minutes=1)
        except (KeyError, ValueError, TypeError, StopIteration, AttributeError):
            issues.append("incomplete_or_invalid_audit_evidence")
        if issues:
            errors.append(dict(candidate_id=t.get("candidate_id"), issues=issues))
    return dict(status="FAIL" if errors else "PASS", checked_trades=len(trades), errors=errors, notices=notices,
                empty_audit_is_not_evidence=not bool(trades))
