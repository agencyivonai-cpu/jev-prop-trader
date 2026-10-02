import math
import numpy as np
import pytest

from jev.falsification.statistics import (adjust_pvalues, block_bootstrap, calibration,
                                        stability, summarize)


def trades(values):
    return [dict(session=f"day{i:03}", gross_pnl=v+2.5, net_pnl=v, initial_risk=20) for i,v in enumerate(values)]


def test_full_gross_and_net_statistics_against_known_sample():
    result = summarize(trades([10, -5, 5, -2]))
    net = result["net"]
    assert net["sample_size"] == 4 and net["pnl"] == 8 and net["expectancy"] == 2
    assert result["gross"]["pnl"] == 18
    assert net["expectancy_r"] == pytest.approx(.1)
    assert net["win_rate"] == .5 and net["average_win"] == 7.5 and net["average_loss"] == -3.5
    assert net["payoff_ratio"] == pytest.approx(7.5/3.5)
    assert net["profit_factor"] == pytest.approx(15/7)
    assert net["maximum_realized_drawdown"] == 5
    assert net["variance"] == pytest.approx(np.var([10,-5,5,-2], ddof=1))
    assert net["standard_error"] == pytest.approx(net["standard_deviation"]/2)
    assert net["t_statistic"] == pytest.approx(2/net["standard_error"])
    assert net["expectancy_ci95_iid"][0] < 2 < net["expectancy_ci95_iid"][1]


def test_empty_and_constant_samples_not_inferential_support():
    assert summarize([])["net"]["expectancy"] is None
    assert summarize(trades([1]*40))["net"]["t_statistic"] is None
    assert not block_bootstrap(trades([1]*40), [f"day{i:03}" for i in range(40)], replicates=100)["sufficient"]


def test_block_bootstrap_seed_reproducibility_and_serial_dependence():
    values = [10]*10 + [-10]*10 + [10]*10 + [-10]*10
    data = trades(values)
    days = [t["session"] for t in data]
    a = block_bootstrap(data, days, replicates=1000, block_length=5, seed=9)
    assert a == block_bootstrap(data, days, replicates=1000, block_length=5, seed=9)
    assert a["expectancy_ci95"][0] < 0 < a["expectancy_ci95"][1]
    rng = np.random.default_rng(9)
    iid = np.mean(rng.choice(values, (1000,40)), axis=1)
    assert a["expectancy_ci95"][1]-a["expectancy_ci95"][0] > np.ptp(np.quantile(iid,[.025,.975]))
    assert a["net_pnl_ci95"] and a["drawdown_ci95"]


def test_zero_trade_sessions_preserved_and_bad_days_rejected():
    t = trades([2,-1]*20)
    days = [x["session"] for x in t]+[f"empty{i}" for i in range(20)]
    assert block_bootstrap(t,days,replicates=100)["config"]["sessions"] == 60
    with pytest.raises(ValueError):
        block_bootstrap(t,days[:-21],replicates=100)
    with pytest.raises(ValueError):
        block_bootstrap(t,days+[days[0]],replicates=100)


def test_multiple_testing_false_winner_fails_and_missing_trials_counted():
    p = [.03]+[None]*99
    adjusted = adjust_pvalues(p)
    assert adjusted["hypotheses_tested"] == 100
    assert adjusted["adjusted"][0] > .05
    known = adjust_pvalues([.01,.04,.03], "bh")["adjusted"]
    assert known == pytest.approx([.03,.04,.04])
    by = adjust_pvalues([.01,.04,.03], "by")["adjusted"]
    assert all(y>=x for x,y in zip(known,by))


@pytest.mark.parametrize("p", [[float("nan")], [-.1], [1.1]])
def test_invalid_multiple_testing_inputs_fail(p):
    with pytest.raises(ValueError):
        adjust_pvalues(p)


def test_isolated_parameter_spike_fragile_and_low_sample_insufficient():
    sample = lambda ev,n=40: dict(sample_size=n,expectancy=ev)
    r = {"0.65":sample(-1), "0.75":sample(10), "0.85":sample(-1)}
    assert stability(r,"0.75")["status"] == "FRAGILE"
    assert stability({k:sample(1) for k in r},"0.75")["status"] == "STABLE"
    r["0.65"] = sample(1,2)
    assert stability(r,"0.75")["status"] == "INSUFFICIENT_EVIDENCE"


def test_action_confidence_is_never_probability_of_win():
    observations = [dict(won=i%2, probability_action=.9, confidence=99) for i in range(40)]
    result = calibration(observations)
    assert result["brier_score"] is None and result["sample_size"] == 0
    observations = [dict(won=i%2, probability_win=.8, probability_action=.9) for i in range(40)]
    result = calibration(observations)
    assert result["brier_score"] == pytest.approx(.34)
    assert result["calibration_error"] == pytest.approx(.3)
    assert not result["statistically_adequate"]


def test_reliability_curve_and_ranking_diagnostic():
    observations = [dict(won=int(i%10 < int(p*10)), probability_win=p, probability_action=p)
                    for p in (.1,.3,.5,.7,.9) for i in range(100)]
    r = calibration(observations)
    assert r["statistically_adequate"]
    assert r["calibration_error"] == pytest.approx(0)
    assert r["ranking"]["rho"] > 0
    assert r["action_probability_ranking"]["rho"] > 0
