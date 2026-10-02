from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from jev.research import (Bar, ET, ResearchConfig, load_bars, metrics,
                          practice_gate, replay, valid_bar, walk_forward)
from jev.types import Action, Proposal, SignalCandidate


def session(day=2):
    start = datetime(2026, 1, day, 9, 30, tzinfo=ET)
    return [Bar(start + timedelta(minutes=i), D(20000), D(20001), D(19999),
                D(20000), D(100), D(20)) for i in range(390)]


def test_metrics_costs_and_drawdown():
    m = metrics([dict(net_pnl=x) for x in ("10", "-4", "-8", "6")])
    assert m == dict(sample_size=4, expectancy="1", profit_factor=str(D(16)/12),
                     no_losses=False, drawdown="12", win_rate=.5, net_pnl="4")
    assert metrics([])["expectancy"] is None


@pytest.mark.parametrize("change", [dict(volume=D(0)), dict(close=D("20000.01")),
                                    dict(high=D(19998)), dict(delta=D(101))])
def test_invalid_data_fails_closed(change):
    b = replace(session()[0], **change)
    assert not valid_bar(b)
    r = replay([b])
    assert not r["data_valid"] and not r["trades"]
    assert r["ledger"][0]["reason"] == "invalid_market_data"


def test_gap_and_order():
    bars = session()
    assert not replay([bars[0], bars[2]])["data_valid"]
    assert not replay([bars[1], bars[0]])["data_valid"]


def test_missing_delta_no_fabrication():
    r = replay(session() + [replace(b, delta=None) for b in session(3)])
    assert not r["trades"]
    assert all(x["reason"] == "missing_features_or_entry_window" for x in r["ledger"])


def test_loader_explicit_timezone_and_proxy(tmp_path):
    p = tmp_path / "bars.csv"
    p.write_text("timestamp ET,open,high,low,close,volume\n01/02/2026 09:30,20000,20001,19999,20000,100\n")
    with pytest.raises(ValueError):
        load_bars(p, source_symbol="NQ")
    assert load_bars(p, source_symbol="NQ", timezone="America/New_York")[0].delta is None
    with pytest.raises(ValueError):
        load_bars(p, source_symbol="ES", timezone="America/New_York")


@pytest.mark.parametrize("change", [dict(commission=D(4)), dict(slippage_ticks=-1),
                                    dict(max_hold_bars=0), dict(stop_points=D(9))])
def test_config_cost_reserve(change):
    with pytest.raises(ValueError):
        ResearchConfig(**change)


def forced_candidates(s):
    return [SignalCandidate(str(s.timestamp), "jev_vwap_reclaim", "MNQ", s.timestamp,
                            "long", s.close, s.close-D(10), s.close+D(20))]


def test_next_bar_fill_stop_first_and_costs(monkeypatch):
    monkeypatch.setattr("jev.research.generate_challengers", forced_candidates)
    bars = session() + session(3)
    # First possible signal at 09:45 close; only subsequent 09:46 bar can fill.
    bars[390+16] = replace(bars[390+16], high=D(20020), low=D(19990))
    r = replay(bars)
    t = r["trades"][0]
    assert t["entry_time"].endswith("09:46:00-05:00")
    assert t["exit_reason"] == "stop"
    assert D(t["net_pnl"]) == D("-45.00")  # two contracts: 40 stop + 2 slips + 3 commissions
    assert any(x["action"] == "STOP_DAY" for x in r["ledger"])
    assert r == replay(bars)


def test_changed_open_cancels_without_phantom_trade(monkeypatch):
    monkeypatch.setattr("jev.research.generate_challengers", forced_candidates)
    bars = session() + session(3)
    bars[406] = replace(bars[406], open=D("20000.25"))
    r = replay(bars)
    assert any(x["reason"] == "next_open_price_changed" for x in r["ledger"])
    assert r["trades"][0]["entry_time"] != bars[406].timestamp.isoformat()


def test_stop_proposal_persists(monkeypatch):
    monkeypatch.setattr("jev.research.generate_challengers", forced_candidates)
    r = replay(session() + session(3), proposer=lambda cs: Proposal(Action.STOP_DAY))
    assert not r["trades"]
    assert r["ledger"][-1]["action"] == "STOP_DAY"


@pytest.mark.parametrize("action", [Action.WAIT, Action.SKIP])
def test_nontrade_decisions_preserve_candidates(monkeypatch, action):
    monkeypatch.setattr("jev.research.generate_challengers", forced_candidates)
    r = replay(session() + session(3), proposer=lambda cs: Proposal(action))
    assert not r["trades"]
    events = [x for x in r["ledger"] if x["candidates"]]
    assert events and all(x["reason"] == action.value.lower() for x in events)


@pytest.mark.parametrize("change,reason", [(dict(model="unknown"), "unregistered_model"),
                                         (dict(timestamp=datetime(2020, 1, 1, tzinfo=ET)),
                                          "stale_or_future_input")])
def test_riskgate_denials_in_ledger(monkeypatch, change, reason):
    monkeypatch.setattr("jev.research.generate_challengers",
                        lambda s: [replace(forced_candidates(s)[0], **change)])
    r = replay(session() + session(3))
    assert not r["trades"]
    assert any(x["reason"] == reason for x in r["ledger"])


def test_walk_forward_disjoint_and_future_independence():
    bars = sum((session(d) for d in range(2, 10)), [])
    a = walk_forward(bars, train_days=2, test_days=2)
    b = walk_forward(bars[:-390] + [replace(x, close=D("20000.25")) for x in bars[-390:]],
                     train_days=2, test_days=2)
    assert a["folds"][0] == b["folds"][0]
    assert a["folds"][0]["test_range"][1] < a["folds"][1]["test_range"][0]
    assert a["practice_gate"]["status"] == "INSUFFICIENT_EVIDENCE"


def fold(pnls):
    trades = [dict(net_pnl=str(x)) for x in pnls]
    return dict(data_valid=True, trades=trades, metrics=metrics(trades))


def test_gate_all_states():
    good = [fold([10, -2]*20)]*3
    assert practice_gate(good, real_data=True)["status"] == "PASS"
    assert practice_gate(good, real_data=False)["status"] == "INSUFFICIENT_EVIDENCE"
    assert practice_gate([fold([-10, 2]*20)]*3, real_data=True)["status"] == "FAIL"
    assert practice_gate([fold([10,-2]*15)]*3, real_data=True)["status"] == "INSUFFICIENT_EVIDENCE"
