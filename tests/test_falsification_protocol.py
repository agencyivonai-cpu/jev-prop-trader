import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from jev.research import Bar, ET, ResearchConfig, practice_gate as legacy_gate
from jev.falsification.gates import evidence_state, practice_gate
from jev.falsification.protocol import (assert_development_allowed, consume_holdout,
                                       partition, register, specification, verify_plan)
from jev.falsification.simulation import FeatureRule, FeatureRuleFilter, FilterAction
from jev.falsification.study import run_study


def source():
    return dict(sha256="example", source_symbol="MNQ", independent_real_data=True,
                unseen_holdout=True, signed_delta_verified=False)


def test_chronological_disjoint_train_validation_test():
    days = [f"2026-01-{i:02}" for i in range(1,31)]
    p = partition(days)
    assert p["train"][-1] < p["validation"][0] < p["test"][0]
    assert not (set(p["train"]) & set(p["test"]))
    with pytest.raises(ValueError):
        partition(days[::-1])


def test_plan_change_after_registration_invalidates_holdout(tmp_path):
    spec = specification(ResearchConfig())
    days = [f"2026-01-{i:02}" for i in range(1,31)]
    plan = register(tmp_path/"study",days,source(),spec)
    verify_plan(plan,source(),spec)
    changed = specification(ResearchConfig(commission=D(2)))
    with pytest.raises(ValueError):
        register(tmp_path/"study",days,source(),changed)
    with pytest.raises(ValueError):
        verify_plan(plan,source(),changed)
    tampered = copy.deepcopy(plan)
    tampered["partitions"]["test"][0] = days[0]
    with pytest.raises(ValueError):
        verify_plan(tampered,source(),spec)


def test_holdout_single_use_across_studies_and_no_refinement(tmp_path):
    p = register(tmp_path/"study",[str(i).zfill(3) for i in range(100)],source(),specification(ResearchConfig()))
    consume_holdout(tmp_path/"study",p)
    with pytest.raises(ValueError):
        consume_holdout(tmp_path/"different_study",p)
    with pytest.raises(ValueError):
        assert_development_allowed(tmp_path/"different_study",source())


def test_prior_registered_trials_not_hidden_by_new_directory(tmp_path):
    spec = specification(ResearchConfig())
    days = [str(i).zfill(3) for i in range(100)]
    first = register(tmp_path/"first",days,source(),spec)
    second = register(tmp_path/"second",days,source(),spec)
    assert first["prior_registered_hypotheses"] == 0
    assert second["prior_registered_hypotheses"] == 54
    assert register(tmp_path/"second",days,source(),spec) == second


def eligible():
    fold = dict(metrics={"net":dict(sample_size=40,pnl=200,maximum_realized_drawdown=20)},
                bootstrap=dict(sufficient=True,expectancy_ci95=[1,8]),
                audit=dict(status="PASS"))
    return dict(folds=[copy.deepcopy(fold) for _ in range(3)], data_valid=True,
                audit_valid=True,filter_valid=True,available=True,
                metrics={"net":dict(sample_size=120,expectancy=5,profit_factor=1.5,maximum_realized_drawdown=100)})


def test_evidence_all_three_states_and_incremental_requirement():
    r = eligible()
    kwargs = dict(family="ohlcv",stability_report=dict(status="STABLE"),adjusted_p=.01)
    assert evidence_state(r,source(),**kwargs)["state"] == "SURVIVES"
    assert evidence_state(r,source(),incremental=dict(supported=False),**kwargs)["state"] == "FAILS"
    assert evidence_state(r,{**source(),"unseen_holdout":False},**kwargs)["state"] == "INSUFFICIENT_EVIDENCE"
    assert evidence_state(r,source(),**{**kwargs,"adjusted_p":.8})["state"] == "FAILS"
    assert evidence_state(r,source(),**{**kwargs,"stability_report":dict(status="FRAGILE")})["state"] == "FAILS"
    assert evidence_state(r,source(),**{**kwargs,"family":"order_flow"})["state"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("field", ["data_valid", "audit_valid", "filter_valid", "available"])
def test_missing_quality_blocks_positive_pnl(field):
    r = eligible()
    r[field] = False
    assert evidence_state(r,source(),family="ohlcv",stability_report=dict(status="STABLE"),
                          adjusted_p=.001)["state"] == "INSUFFICIENT_EVIDENCE"


def test_legacy_pass_and_forged_summary_cannot_bypass_falsification():
    assert legacy_gate([],real_data=True)["status"] == "INSUFFICIENT_EVIDENCE"
    forged = dict(phase="test",protocol_verified=True,holdout_consumed=True,
                  results={"fake":dict(arms={"RAW":dict(evidence=dict(state="SURVIVES"))})})
    assert practice_gate(forged)["status"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("failure", ["ci", "drawdown", "fold", "profit_factor", "neighborhood"])
def test_sufficient_but_failing_criteria_are_fails(failure):
    r = eligible()
    stability = dict(status="STABLE")
    if failure == "ci":
        r["folds"][0]["bootstrap"]["expectancy_ci95"] = [-1,8]
    elif failure == "drawdown":
        r["metrics"]["net"]["maximum_realized_drawdown"] = 801
    elif failure == "fold":
        r["folds"][0]["metrics"]["net"]["pnl"] = -1
    elif failure == "profit_factor":
        r["metrics"]["net"]["profit_factor"] = 1.19
    else:
        stability["status"] = "FRAGILE"
    assert evidence_state(r,source(),family="ohlcv",stability_report=stability,adjusted_p=.01)["state"] == "FAILS"


def test_development_never_reads_test_prices_and_rejects_source_changes(tmp_path):
    bars = []
    for day in range(2,12):
        start = datetime(2026,1,day,9,30,tzinfo=ET)
        bars += [Bar(start+timedelta(minutes=i),D(20000),D(20001),D(19999),D(20000),D(100)) for i in range(390)]
    a = run_study(bars,source(),tmp_path/"a")
    # No outcome access: final 20% prices/volumes can change without changing development results.
    changed = bars[:-780]+[replace(b,open=D(30000),close=D(30000),high=D(30001),low=D(29999),volume=D(0)) for b in bars[-780:]]
    b = run_study(changed,source(),tmp_path/"a")
    assert a == b
    with pytest.raises(ValueError):
        run_study(bars,{**source(),"sha256":"changed"},tmp_path/"a",phase="test")
    r = run_study(bars,source(),tmp_path/"a",phase="test")
    assert r["practice_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    with pytest.raises(ValueError):
        run_study(bars,source(),tmp_path/"a",phase="test")
    with pytest.raises(ValueError):
        run_study(bars,source(),tmp_path/"a",phase="development")


def test_development_artifact_tampering_rejected(tmp_path):
    bars = []
    run_study(bars,source(),tmp_path/"s")
    path = tmp_path/"s"/"development.json"
    report = json.loads(path.read_text())
    report["neighborhoods"]["ohlcv_orb"]["RAW"]["status"] = "STABLE"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        run_study(bars,source(),tmp_path/"s",phase="test")


def test_each_orb_feature_can_be_preregistered_and_falsified():
    from types import SimpleNamespace, MappingProxyType
    f = FeatureRuleFilter([FeatureRule("extension_atr", ">=", ".75")])
    low = SimpleNamespace(features=MappingProxyType(dict(extension_atr=D(".7"))))
    high = SimpleNamespace(features=MappingProxyType(dict(extension_atr=D(".8"))))
    assert f(low).action == FilterAction.STAND_ASIDE
    assert f(high).action == FilterAction.APPROVE
    assert f(SimpleNamespace(features={})).action == FilterAction.STAND_ASIDE
    with pytest.raises(ValueError):
        FeatureRuleFilter([FeatureRule("future_close", ">=", 0)])
