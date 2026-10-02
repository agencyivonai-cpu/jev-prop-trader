"""Offline, causal MNQ research. No execution or network dependencies."""
import csv
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, time
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

from .challengers import MarketState, generate_challengers
from .governor import Governor
from .profiles import TOPSTEP_50K
from .registry import challenger_registry
from .risk import RiskGate
from .types import AccountSnapshot, Action, Proposal

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime  # bar OPEN time; information becomes available one minute later
    open: D
    high: D
    low: D
    close: D
    volume: D
    delta: D | None = None  # real signed volume only; never inferred from candle colour


def load_bars(path, *, source_symbol, timezone=None):
    """Explicit NQ proxy opt-in; preserve invalid rows for fail-closed replay."""
    if source_symbol not in ("MNQ", "NQ"):
        raise ValueError("Only MNQ or explicitly declared NQ price proxy supported")
    bars = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            row = {k.strip().lower().replace(" ", "_"): v for k, v in raw.items()}
            value = row.get("datetime", row.get("timestamp_et", row.get("timestamp")))
            if value is None:
                raise ValueError("Missing timestamp")
            try:
                ts = datetime.fromisoformat(value)
            except ValueError:
                ts = datetime.strptime(value, "%m/%d/%Y %H:%M")
            if ts.utcoffset() is None:
                if timezone is None:
                    raise ValueError("Naive timestamps require explicit timezone")
                zone = ZoneInfo(timezone)
                ts = ts.replace(tzinfo=zone)
                if ts.utcoffset() != ts.replace(fold=1).utcoffset():
                    raise ValueError("Ambiguous DST timestamp")
                from datetime import timezone as utc
                if ts.astimezone(utc.utc).astimezone(zone).replace(tzinfo=None) != ts.replace(tzinfo=None):
                    raise ValueError("Nonexistent DST timestamp")
            bars.append(Bar(ts, *(D(row[k]) for k in ("open", "high", "low", "close", "volume")),
                            D(row["delta"]) if row.get("delta") else None))
    return bars


def valid_bar(b):
    prices = (b.open, b.high, b.low, b.close)
    return (b.timestamp.utcoffset() is not None
            and all(v.is_finite() and v > 0 and v % D(".25") == 0 for v in prices)
            and b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
            and b.volume.is_finite() and b.volume > 0
            and (b.delta is None or (b.delta.is_finite() and abs(b.delta) <= b.volume)))


@dataclass(frozen=True)
class ResearchConfig:
    commission: D = D("1.50")  # round trip per contract
    slippage_ticks: int = 1  # each side
    stop_points: D = D("10")
    max_hold_bars: int = 30

    def __post_init__(self):
        if (not self.commission.is_finite() or self.commission < 0
                or type(self.slippage_ticks) is not int or self.slippage_ticks < 0
                or type(self.max_hold_bars) is not int or self.max_hold_bars < 1
                or not self.stop_points.is_finite() or self.stop_points % D(".25")
                or not D("10") <= self.stop_points <= D("20")
                or self.commission + D(2) * self.slippage_ticks * D(".5") > D("3")):
            raise ValueError("Invalid configuration or costs exceed RiskGate reserve")


def metrics(trades):
    pnls = [D(str(t["net_pnl"])) for t in trades]
    equity = peak = dd = D(0)
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    gains = sum((v for v in pnls if v > 0), D(0))
    losses = -sum((v for v in pnls if v < 0), D(0))
    return dict(sample_size=len(pnls), expectancy=str(equity / len(pnls)) if pnls else None,
                profit_factor=str(gains / losses) if losses else None,
                no_losses=bool(pnls) and losses == 0,
                drawdown=str(dd), win_rate=sum(v > 0 for v in pnls) / len(pnls) if pnls else None,
                net_pnl=str(equity))


def attribution(trades):
    result = {}
    for dimension in ("challenger", "regime", "time_of_day"):
        result[dimension] = {key: metrics([t for t in trades if t[dimension] == key])
                             for key in sorted({t[dimension] for t in trades})}
    return result


def replay(bars, config=ResearchConfig(), proposer=None):
    """One position; closed-bar signals, next-open fills, stop first on ambiguity."""
    bars = list(bars)
    gate = RiskGate(challenger_registry())
    governor = Governor(gate)
    stopped = set()
    account = AccountSnapshot(bars[0].timestamp if bars else datetime.now(ET), "initial",
                              D(50000), D(50000), D(50000), D(48000), 0, 0, 0, 0, True)
    ledger, trades, history = [], [], []
    previous_session = None
    session = None
    position = pending = None
    contaminated = False

    def record(ts, action, reason, candidates=(), **extra):
        ledger.append(dict(timestamp=ts.isoformat(), action=action, reason=reason,
                           candidates=[asdict(c) for c in candidates], **extra))

    def close_position(b, price, reason):
        nonlocal account, position
        order, entry, opened, labels, held = position
        sign = D(1) if order.candidate.direction == "long" else D(-1)
        exit_price = price - sign * config.slippage_ticks * D(".25")
        gross = (exit_price - entry) * sign * D(2) * order.contracts
        net = gross - config.commission * order.contracts
        trades.append(dict(candidate_id=order.candidate.candidate_id, entry_time=opened.isoformat(),
                           exit_time=b.timestamp.isoformat(), entry=str(entry), exit=str(exit_price),
                           contracts=order.contracts, gross_pnl=str(gross), net_pnl=str(net),
                           exit_reason=reason, **labels))
        equity = account.equity + net
        account = replace(account, equity=equity, high_water_equity=max(account.high_water_equity, equity),
                          consecutive_losses=account.consecutive_losses + 1 if net < 0 else 0,
                          open_contracts=0)
        position = None

    for b in bars:
        local = b.timestamp.astimezone(ET)
        day = local.date().isoformat()
        if not valid_bar(b) or (history and b.timestamp <= history[-1].timestamp):
            record(b.timestamp, "SKIP", "invalid_market_data")
            contaminated = True
            pending = None
            governor = Governor(gate)
            if position:
                record(b.timestamp, "STOP_DAY", "unresolved_position_invalid_data")
                break
            history = []
            continue
        if not time(9, 30) <= local.time() < time(16):
            continue
        if day != session:
            if position:
                record(b.timestamp, "STOP_DAY", "missing_session_close")
                contaminated = True
                break
            previous_session = (history if history and len(history) == 390
                                and b.timestamp - history[-1].timestamp <= timedelta(days=4) else None)
            history = []
            session = day
            pending = None
            governor = Governor(gate)
            account = replace(account, session_id=day, day_open_equity=account.equity,
                              trades_today=0, consecutive_losses=0)
        if history and b.timestamp - history[-1].timestamp != timedelta(minutes=1):
            record(b.timestamp, "SKIP", "stale_market_data")
            contaminated = True
            pending = None
            governor = Governor(gate)
            if position:
                record(b.timestamp, "STOP_DAY", "unresolved_position_data_gap")
                break
            history = []
        if pending:
            order, labels = pending
            pending = None
            c = order.candidate
            if b.open != c.entry:
                record(b.timestamp, "SKIP", "next_open_price_changed", (c,))
                governor = Governor(gate)
            else:
                # Reauthorize against actual execution time and current account.
                check = gate.authorize(c, replace(account, timestamp=b.timestamp), b.timestamp)
                if not check.allowed:
                    record(b.timestamp, "SKIP", check.reason, (c,))
                    governor = Governor(gate)
                else:
                    order = check.order
                    sign = D(1) if c.direction == "long" else D(-1)
                    entry = b.open + sign * config.slippage_ticks * D(".25")
                    position = (order, entry, b.timestamp, labels, 0)
                    entered = replace(account, timestamp=b.timestamp + timedelta(microseconds=1),
                                      trades_today=account.trades_today + 1, open_contracts=order.contracts)
                    governor.acknowledge(c.candidate_id, reconciled_snapshot=entered)
                    account = entered
                    record(b.timestamp, "TRADE", "simulated_fill", (c,), contracts=order.contracts)
        if position:
            order, entry, opened, labels, held = position
            c = order.candidate
            stop_hit = b.low <= c.stop if c.direction == "long" else b.high >= c.stop
            target_hit = b.high >= c.target if c.direction == "long" else b.low <= c.target
            if stop_hit:
                price = min(b.open, c.stop) if c.direction == "long" else max(b.open, c.stop)
                close_position(b, price, "stop")
            elif target_hit:
                close_position(b, c.target, "target")
            elif held + 1 >= config.max_hold_bars or local.time() == time(15, 59):
                close_position(b, b.close, "timeout_or_session_close")
            else:
                position = (order, entry, opened, labels, held + 1)
        history.append(b)
        now = b.timestamp + timedelta(minutes=1)
        account = replace(account, timestamp=now)
        if (day in stopped or account.trades_today >= 3 or account.consecutive_losses >= 2
                or account.day_open_equity - account.equity >= D(200)
                or account.high_water_equity - account.equity >= D(800)):
            governor.evaluate(Proposal(Action.STOP_DAY), [], account, now)
            stopped.add(day)
            record(now, "STOP_DAY", "account_limits")
            continue
        if position:
            record(now, "WAIT", "exposure_exists")
            continue
        if (not previous_session or len(history) < 16 or history[0].timestamp.astimezone(ET).time() != time(9, 30)
                or b.delta is None or local.time() >= time(15, 58)):
            record(now, "SKIP", "missing_features_or_entry_window")
            continue
        opening = history[:15]
        volume = sum(x.volume for x in history)
        vwap = sum(x.close * x.volume for x in history) / volume
        # Feature VWAP is not an order price; candidate prices stay on tick grid.
        state = MarketState(now, b.close, history[-2].close, vwap,
                            max(x.high for x in opening), min(x.low for x in opening),
                            max(x.high for x in previous_session), min(x.low for x in previous_session),
                            b.high, b.low, b.volume / (sum(x.volume for x in history[:-1]) / (len(history)-1)),
                            b.delta, config.stop_points)
        candidates = generate_challengers(state)
        proposal = proposer(tuple(candidates)) if proposer else Proposal(
            Action.TRADE if candidates else Action.WAIT, candidates[0].candidate_id if candidates else None)
        decision = governor.evaluate(proposal, candidates, account, now)
        if proposal.action == Action.STOP_DAY:
            stopped.add(day)
        action = proposal.action.value if proposal.action != Action.TRADE or decision.allowed else "SKIP"
        record(now, action, decision.reason, candidates, proposed_action=proposal.action.value,
               selected=proposal.candidate_id, authorized=decision.allowed)
        if decision.allowed:
            labels = dict(challenger=decision.order.candidate.model,
                          regime="above_vwap" if b.close > vwap else "below_vwap",
                          time_of_day="morning" if local.hour < 12 else "afternoon")
            pending = (decision.order, labels)
    if position or pending:
        contaminated = True
        record(bars[-1].timestamp, "SKIP", "incomplete_execution_horizon")
    return dict(ledger=ledger, trades=trades, metrics=metrics(trades), attribution=attribution(trades),
                data_valid=not contaminated, config=asdict(config))


def practice_gate(folds, *, real_data):
    """Frozen internal research criteria, not a firm qualification guarantee."""
    if not real_data or len(folds) < 3 or any(not f["data_valid"] for f in folds):
        return dict(status="INSUFFICIENT_EVIDENCE", reason="provenance_folds_or_data_quality")
    if any(f["metrics"]["sample_size"] < 30 for f in folds):
        return dict(status="INSUFFICIENT_EVIDENCE", reason="at_least_30_trades_per_fold_required")
    combined = metrics([t for f in folds for t in f["trades"]])
    passed = (combined["sample_size"] >= 100 and D(combined["expectancy"]) > 0
              and combined["profit_factor"] is not None and D(combined["profit_factor"]) >= D("1.2")
              and D(combined["drawdown"]) <= D(800)
              and all(D(f["metrics"]["net_pnl"]) > 0 and D(f["metrics"]["drawdown"]) <= D(800) for f in folds))
    if combined["sample_size"] < 100:
        return dict(status="INSUFFICIENT_EVIDENCE", reason="at_least_100_oos_trades_required")
    return dict(status="PASS" if passed else "FAIL", reason="frozen_oos_criteria", metrics=combined)


def walk_forward(bars, *, train_days=20, test_days=10, config=ResearchConfig(), real_data=False):
    if type(train_days) is not int or type(test_days) is not int or min(train_days, test_days) < 1:
        raise ValueError("Positive whole session windows required")
    sessions = {}
    for b in bars:
        if time(9, 30) <= b.timestamp.astimezone(ET).time() < time(16):
            sessions.setdefault(b.timestamp.astimezone(ET).date(), []).append(b)
    days = sorted(sessions)
    folds = []
    for start in range(train_days, len(days) - test_days + 1, test_days):
        # Training observations are deliberately not used to tune anything.
        # First test day is feature warmup; no training trades cross the boundary.
        subset = [b for day in days[start:start + test_days] for b in sessions[day]]
        fold = replay(subset, config)
        fold["train_range"] = [str(days[start-train_days]), str(days[start-1])]
        fold["test_range"] = [str(days[start]), str(days[start+test_days-1])]
        folds.append(fold)
    trades = [t for f in folds for t in f["trades"]]
    return dict(folds=folds, practice_gate=practice_gate(folds, real_data=real_data),
                metrics=metrics(trades), attribution=attribution(trades),
                dropped_tail_sessions=max(0, len(days)-train_days) % test_days,
                parameters_frozen=True)


def write_report(report, path):
    Path(path).write_text(json.dumps(report, default=str, sort_keys=True, indent=2), encoding="utf-8")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("--source-symbol", choices=("MNQ", "NQ"), required=True)
    parser.add_argument("--timezone")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    bars = load_bars(args.csv, source_symbol=args.source_symbol, timezone=args.timezone)
    report = walk_forward(bars)  # CLI never auto-attests independent provenance.
    report["source"] = dict(symbol=args.source_symbol, sha256=hashlib.sha256(Path(args.csv).read_bytes()).hexdigest(),
                            path=str(args.csv), provenance_verified=False)
    write_report(report, args.output)


if __name__ == "__main__":
    main()
