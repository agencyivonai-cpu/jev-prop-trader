"""Adversarial tests for causal research, filters, costs, and mechanical audit."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import MappingProxyType

import pytest

from jev.research import Bar, ET, ResearchConfig
from jev.types import SignalCandidate
from jev.falsification.audit import audit_trades
from jev.falsification.market import (FeatureStream, HYPOTHESES, Opportunity, candidates_for,
                                     feature_tape, opportunities_from_tape, validate_sessions)
from jev.falsification.simulation import (FilterAction, FilterDecision, RecordedJEV,
                                         opportunity_digest, run_arms)


def day(day=2, month=1):
    ts = datetime(2026, month, day, 9, 30, tzinfo=ET)
    return [Bar(ts+timedelta(minutes=i), D(20000), D(20001), D(19999), D(20000), D(100)) for i in range(390)]


def fixture():
    bars = day()
    ts = bars[16].timestamp
    c = SignalCandidate("test", "ohlcv_orb", "MNQ", ts, "long", D(20000), D(19990), D(20020))
    f = MappingProxyType(dict(observed_through=ts, higher_timeframe_trend=D(1),
                             relative_volume_tod=D(2), body_fraction=D(".8")))
    o = Opportunity(c, f, ts, "2026-01-02")
    bars[16] = replace(bars[16], low=D(19990), high=D(20020))
    return (o,), {"2026-01-02": bars}


def test_three_arms_identical_candidates_and_immutable_input():
    ops, sessions = fixture()
    seen = []
    def approve(o):
        seen.append(o.candidate)
        with pytest.raises(TypeError):
            o.features["future"] = 1
        with pytest.raises(Exception):
            o.candidate.direction = "short"
        return FilterDecision(FilterAction.APPROVE, "fixed")
    r = run_arms(ops, sessions, jev=approve)
    assert seen == [ops[0].candidate]
    digests = {a["ledger"][0]["candidate_digest"] for a in r["arms"].values()}
    assert len(digests) == 1
    assert r["arms"]["RAW"]["trades"][0]["net_pnl"] == r["arms"]["JEV"]["trades"][0]["net_pnl"]


@pytest.mark.parametrize("payload", [{"action":"APPROVE", "direction":"short"},
                                    {"action":"APPROVE", "contracts":100},
                                    {"action":"APPROVE", "risk":1000},
                                    {"action":"APPROVE", "stop":19999}, "APPROVE"])
def test_jev_cannot_flip_resize_or_bypass_gate(payload):
    ops, sessions = fixture()
    r = run_arms(ops, sessions, jev=lambda o: payload)
    assert not r["filter_valid"]
    assert not r["arms"]["JEV"]["trades"]
    assert r["arms"]["JEV"]["ledger"][0]["reason"] == "invalid_jev_payload"


def test_rejected_ev_is_counterfactual_not_zero():
    ops, sessions = fixture()
    r = run_arms(ops, sessions, jev=lambda o: FilterDecision(FilterAction.STAND_ASIDE, "reject"))
    s = r["arms"]["JEV"]["selection"]
    assert s["ev_rejected"] == -22.5 and s["stand_aside_rate"] == 1
    assert s["ev_accepted"] is None
    assert r["arms"]["RAW"]["metrics"]["gross"]["pnl"] == -40
    assert r["arms"]["RAW"]["metrics"]["net"]["pnl"] == -45


def test_auditor_independently_accepts_conservative_ambiguity():
    ops, sessions = fixture()
    r = run_arms(ops, sessions)
    trades = r["arms"]["RAW"]["trades"]
    audit = audit_trades(trades, ops, sessions, ResearchConfig(), fold="validation")
    assert audit["status"] == "PASS"
    assert audit["notices"][0]["issue"] == "stop_first_ambiguity"


@pytest.mark.parametrize("change", [dict(entry="20000"), dict(exit="20020"), dict(net_pnl="-43.5"),
                                   dict(commission="0"), dict(slippage="0"), dict(multiplier="20"),
                                   dict(contracts=50), dict(authorized_risk="999"), dict(fold="test"),
                                   dict(observed_through="2026-01-02T09:47:00-05:00"),
                                   dict(exit_reason="target"), dict(stop_target_ambiguous=False),
                                   dict(entry_time="2026-01-02T09:45:00-05:00")])
def test_auditor_rejects_impossible_fills_costs_risk_and_leakage(change):
    ops, sessions = fixture()
    t = run_arms(ops, sessions)["arms"]["RAW"]["trades"][0]
    assert audit_trades([{**t, **change}], ops, sessions, ResearchConfig(), fold="validation")["status"] == "FAIL"


def test_stop_gap_charged_and_audited():
    ops, sessions = fixture()
    bars = sessions["2026-01-02"]
    bars[16] = replace(bars[16], high=D(20001), low=D(19999))
    bars[17] = replace(bars[17], open=D(19980), high=D(19985), low=D(19979), close=D(19982))
    t = run_arms(ops, sessions)["arms"]["RAW"]["trades"][0]
    assert t["adverse_stop_gap"] is True and D(t["exit_reference"]) == D(19980)
    assert audit_trades([t], ops, sessions, ResearchConfig(), fold="validation")["status"] == "PASS"


def test_same_bar_touch_before_signal_does_not_exit():
    ops, sessions = fixture()
    rows = sessions["2026-01-02"]
    rows[15] = replace(rows[15], high=D(20020), low=D(19990))
    rows[16] = replace(rows[16], high=D(20001), low=D(19999))
    t = run_arms(ops, sessions)["arms"]["RAW"]["trades"][0]
    assert t["exit_reason"] == "timeout_or_session_close"


def test_open_change_no_phantom_fill():
    ops, sessions = fixture()
    sessions["2026-01-02"][16] = replace(sessions["2026-01-02"][16], open=D("20000.25"))
    assert not run_arms(ops, sessions)["arms"]["RAW"]["trades"]


def test_future_feature_access_fails_closed():
    ops, sessions = fixture()
    modified = (replace(ops[0], observed_through=ops[0].observed_through+timedelta(minutes=1)),)
    r = run_arms(modified, sessions)
    assert not r["filter_valid"] and all(not a["trades"] for a in r["arms"].values())


@pytest.mark.parametrize("bad", ["gap", "duplicate", "off_tick", "ohlc", "zero_volume"])
def test_entire_bad_session_quarantined_without_repair(bad):
    bars = day()
    if bad == "gap":
        bars.pop(20)
    elif bad == "duplicate":
        bars[20] = bars[19]
    elif bad == "off_tick":
        bars[20] = replace(bars[20], close=D("20000.01"))
    elif bad == "ohlc":
        bars[20] = replace(bars[20], high=D(19990))
    else:
        bars[20] = replace(bars[20], volume=D(0))
    valid, audit = validate_sessions(bars)
    assert not valid and audit["status"] == "FAIL"
    assert audit["quarantined_sessions"] == ["2026-01-02"]


def test_missing_order_flow_not_inferred_and_ohlcv_still_researchable():
    sessions = {"2026-01-02":day(), "2026-01-03":day(3)}
    rows = sessions["2026-01-03"]
    rows[31] = replace(rows[31], close=D(20003), high=D(20004))
    tape = feature_tape(sessions)
    assert opportunities_from_tape(tape, HYPOTHESES[1], list(sessions))
    for h in HYPOTHESES[3:]:
        assert not opportunities_from_tape(tape, h, list(sessions))


def test_causal_features_unchanged_when_future_prices_and_volume_change():
    sessions = {"2026-01-02":day(), "2026-01-03":day(3)}
    a = feature_tape(sessions)
    changed = {**sessions, "2026-01-03":list(sessions["2026-01-03"])}
    for i in range(200,390):
        changed["2026-01-03"][i] = replace(changed["2026-01-03"][i], volume=D(9999),
                                          open=D(30000), high=D(30001), low=D(29999), close=D(30000))
    b = feature_tape(changed)
    assert a[:590] == b[:590]
    f = a[500][1]
    assert f["relative_volume_tod"] == 1
    assert set(("higher_timeframe_trend", "opening_range_atr", "extension_atr", "relative_volume_tod",
                "body_fraction", "wick_fraction", "prior_level_tests", "overnight_gap_atr",
                "prior_day_proximity_atr", "round_number_proximity_atr", "volatility_regime", "time_of_day")) <= f.keys()


def test_recorded_filter_binds_causal_candidate_digest():
    ops, sessions = fixture()
    o = ops[0]
    row = dict(candidate_digest=opportunity_digest(o), decision_time=o.candidate.timestamp.isoformat(),
               action="APPROVE", reason="frozen", probability_action=.9, confidence=80)
    r = RecordedJEV({o.candidate.candidate_id:row}, "v1")
    assert r(o).probability_win is None
    row["direction"] = "short"
    bad = RecordedJEV({o.candidate.candidate_id:row}, "v1")
    assert not run_arms(ops, sessions, jev=bad)["arms"]["JEV"]["trades"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.1, True])
def test_invalid_probabilities_fail(value):
    with pytest.raises(ValueError):
        FilterDecision(FilterAction.APPROVE, "bad", probability_win=value)


def test_risk_limits_not_reset_by_candidate_filter():
    ops, sessions = fixture()
    o = ops[0]
    bars = sessions[o.session]
    bars[17] = replace(bars[17], low=D(19990))
    more = tuple(replace(o, candidate=replace(o.candidate, candidate_id=f"c{i}", timestamp=bars[i].timestamp),
                         observed_through=bars[i].timestamp) for i in (16,17,18))
    r = run_arms(more, sessions, jev=lambda o: FilterDecision(FilterAction.APPROVE,"all"))
    for arm in r["arms"].values():
        assert len(arm["trades"]) == 2
        assert arm["ledger"][-1]["riskgate_reason"] == "stop_day"


def test_duplicate_candidate_and_corrupt_market_never_execute():
    ops,sessions = fixture()
    assert all(not a["trades"] for a in run_arms(ops+ops,sessions)["arms"].values())
    sessions[ops[0].session][10] = replace(sessions[ops[0].session][10],volume=D(0))
    assert all(not a["trades"] for a in run_arms(ops,sessions)["arms"].values())


def test_unregistered_model_cannot_bypass_gate():
    ops,sessions = fixture()
    fake = (replace(ops[0],candidate=replace(ops[0].candidate,model="unknown")),)
    r = run_arms(fake,sessions,jev=lambda o:FilterDecision(FilterAction.APPROVE,"approve"))
    assert all(not a["trades"] for a in r["arms"].values())
    assert r["arms"]["JEV"]["ledger"][0]["riskgate_reason"] == "unregistered_model"


def test_missing_recorded_model_and_model_exception_fail_closed():
    ops,sessions = fixture()
    r = run_arms(ops,sessions,jev=RecordedJEV({},"model-v1"))
    assert not r["arms"]["JEV"]["available"]
    def unavailable(o):
        raise RuntimeError("offline model unavailable")
    r = run_arms(ops,sessions,jev=unavailable)
    assert not r["filter_valid"] and not r["arms"]["JEV"]["trades"]


def test_fabricated_delta_without_attestation_never_tested(tmp_path,monkeypatch):
    from jev.falsification.study import evaluate
    ops,sessions = fixture()
    monkeypatch.setattr("jev.falsification.study.opportunities_from_tape",lambda *a:ops)
    r = evaluate((),sessions,[ops[0].session]+[f"extra{i}" for i in range(19)],HYPOTHESES[3],
                 ResearchConfig(),None,dict(signed_delta_verified=False),tmp_path,"fake-delta",inferential=False)
    assert all(a["metrics"]["net"]["sample_size"] == 0 for a in r["arms"].values())
