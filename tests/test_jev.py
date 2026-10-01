from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jev.adapter import adapt_signal
from jev.challengers import MarketState, generate_challengers
from jev.governor import Governor
from jev.registry import Registry, ModelSpec, challenger_registry
from jev.risk import RiskGate
from jev.types import AccountSnapshot, Action, Proposal, SignalCandidate

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def candidate():
    return SignalCandidate("c1", "jev_vwap_reclaim", "MNQ", NOW, "long",
                           D("20000"), D("19990"), D("20020"))


@pytest.fixture
def account():
    return AccountSnapshot(NOW, "2026-10-01", D("50000"), D("50000"),
                           D("50000"), D("48000"), 0, 0, 0, 0, True)


@pytest.fixture
def gate():
    return RiskGate(challenger_registry())


def test_authorization_recomputes_risk_and_costs(gate, candidate, account):
    decision = gate.authorize(candidate, account, NOW)
    assert decision.allowed
    assert decision.order.contracts == 2
    assert decision.order.risk_usd == D("46")
    assert decision == gate.authorize(candidate, account, NOW)


@pytest.mark.parametrize("changes", [
    {"model": "unknown"}, {"symbol": "NQ"}, {"direction": "invalid"},
    {"stop": D("20001")}, {"target": D("19980")}, {"stop": D("20000")},
    {"entry": D("NaN")}, {"stop": D("Infinity")}, {"entry": D("20000.01")},
    {"target": D("20010")}, {"entry": 20000.0}, {"candidate_id": ""},
    {"timestamp": NOW - timedelta(seconds=61)},
    {"timestamp": NOW + timedelta(seconds=1)}, {"timestamp": NOW.replace(tzinfo=None)},
])
def test_invalid_candidate_denies(gate, candidate, account, changes):
    assert not gate.authorize(replace(candidate, **changes), account, NOW).allowed


@pytest.mark.parametrize("changes", [
    {"reconciled": False}, {"halted": True}, {"session_id": ""},
    {"open_contracts": 1}, {"pending_contracts": 1}, {"trades_today": 3},
    {"consecutive_losses": 2}, {"trades_today": -1}, {"trades_today": True},
    {"equity": D("NaN")}, {"day_open_equity": D("0")},
    {"timestamp": NOW - timedelta(seconds=61)},
    {"timestamp": NOW + timedelta(seconds=1)},
    {"equity": D("49800")}, {"high_water_equity": D("50800")},
    {"mll_floor": D("49990")}, {"high_water_equity": D("49999")},
])
def test_invalid_or_exhausted_account_denies(gate, candidate, account, changes):
    assert not gate.authorize(candidate, replace(account, **changes), NOW).allowed


def test_remaining_budget_and_short_geometry(gate, candidate, account):
    a = replace(account, equity=D("49830"))
    result = gate.authorize(candidate, a, NOW)
    assert result.order.contracts == 1
    short = replace(candidate, direction="short", stop=D("20010"), target=D("19980"))
    assert gate.authorize(short, account, NOW).allowed
    assert not gate.authorize(None, account, NOW).allowed


def test_stop_distance_and_profit_never_increase_budget(gate, candidate, account):
    assert not gate.authorize(replace(candidate, stop=D("19999.75")), account, NOW).allowed
    assert not gate.authorize(replace(candidate, stop=D("19970"), target=D("20060")),
                              account, NOW).allowed
    profitable = replace(account, equity=D("51000"), high_water_equity=D("51000"))
    assert gate.authorize(candidate, profitable, NOW).order.risk_usd <= D("60")


def test_registry_has_no_fallback(candidate, account):
    assert not RiskGate(Registry([])).authorize(candidate, account, NOW).allowed
    with pytest.raises(ValueError):
        Registry([ModelSpec("x", D("60")), ModelSpec("x", D("60"))])
    with pytest.raises(ValueError):
        Registry([ModelSpec("x", D("NaN"))])


def test_invalid_profile_is_closed(candidate, account):
    from jev.profiles import TOPSTEP_50K
    gate = RiskGate(challenger_registry(), replace(TOPSTEP_50K, tick_value=D("-1")))
    assert gate.authorize(candidate, account, NOW).reason == "invalid_profile"


def test_governor_proposals_reservations_and_replay(gate, candidate, account):
    g = Governor(gate)
    for action in (Action.WAIT, Action.SKIP):
        assert not g.evaluate(Proposal(action), [candidate], account, NOW).allowed
    assert not g.evaluate({"action": "TRADE", "size": 100}, [candidate], account, NOW).allowed
    assert not g.evaluate(Proposal(Action.TRADE, "invented"), [candidate], account, NOW).allowed
    assert not g.evaluate(Proposal(Action.TRADE, "c1"), [candidate, candidate], account, NOW).allowed
    proposal = Proposal(Action.TRADE, "c1")
    assert g.evaluate(proposal, [candidate], account, NOW).allowed
    assert g.evaluate(proposal, [candidate], account, NOW).reason == "reservation_pending"
    with pytest.raises(ValueError):
        g.acknowledge("c1", reconciled_snapshot=account)
    updated = replace(account, timestamp=NOW + timedelta(seconds=1), trades_today=1)
    g.acknowledge("c1", reconciled_snapshot=updated)
    assert g.evaluate(proposal, [candidate], updated, updated.timestamp).reason == "duplicate_candidate"
    assert g.evaluate(Proposal(Action.STOP_DAY), [], updated, NOW).reason == "stop_day"
    assert not g.evaluate(Proposal(Action.TRADE, "c2"), [replace(candidate, candidate_id="c2")],
                          updated, updated.timestamp).allowed


def test_stop_day_does_not_leak_to_new_session(gate, candidate, account):
    g = Governor(gate)
    g.evaluate(Proposal(Action.STOP_DAY), [], account, NOW)
    assert g.evaluate(Proposal(Action.TRADE, "c1"), [candidate],
                      replace(account, session_id="next"), NOW).allowed


def test_adapter_does_not_mutate_or_trust_derived_risk(candidate):
    signal = SimpleNamespace(ts=NOW.replace(tzinfo=None), model=candidate.model,
                             idx=10, direction="long", entry=20000,
                             stop=19990, target=20020, risk_ticks=1, rr=999)
    adapted = adapt_signal(signal, symbol="MNQ", source_timezone=timezone.utc)
    assert adapted.entry == D("20000") and adapted.timestamp == NOW
    assert signal.ts.tzinfo is None and signal.risk_ticks == 1
    with pytest.raises(ValueError):
        adapt_signal(signal, symbol="MNQ", source_timezone=None)


@pytest.mark.parametrize("direction", ["long", "short"])
def test_three_independent_challengers(direction):
    s = MarketState(NOW, D("20000"), D("19999"), D("19999.5"),
                    D("19999.75"), D("19980"), D("20030"), D("19995"),
                    D("20005"), D("19990"), D("1.5"), D("100"), D("10"))
    if direction == "short":
        s = replace(s, previous_close=D("20001"), vwap=D("20000.5"),
                    opening_high=D("20020"), opening_low=D("20000.25"),
                    previous_day_high=D("20003"), delta=D("-100"))
    candidates = generate_challengers(s)
    assert len(candidates) == 3
    assert {c.model for c in candidates} == set(challenger_registry().models)
    assert all(c.direction == direction for c in candidates)
    assert generate_challengers(replace(s, relative_volume=D("0.9"))) == []
    assert generate_challengers(replace(s, delta=D("NaN"))) == []


@pytest.mark.parametrize("risk", [None, 0, -1, float("nan"), float("inf"), True])
def test_legacy_entry_blocks_invalid_fallback(cfg, risk, tmp_path, monkeypatch):
    import live.executor_multi as em
    from tests.conftest import make_signal
    monkeypatch.setattr(em, "STATE_DIR", str(tmp_path))
    broker = MagicMock()
    executor = em.LiveExecutor(cfg, broker)
    executor._log_decision = MagicMock()
    if risk is not None:
        cfg.funded.model_risk_dollars["unknown"] = risk
    executor._enter_trade(make_signal(model="unknown"))
    assert not broker.mock_calls
    assert executor._log_decision.call_args.args[0]["reason"] == "missing_or_invalid_model_risk"
