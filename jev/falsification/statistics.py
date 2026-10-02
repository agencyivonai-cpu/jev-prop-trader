"""Descriptive IID statistics plus session-block uncertainty for inference."""
import math
import numpy as np
from scipy import stats


def drawdown(values):
    equity = np.r_[0., np.cumsum(values)]
    return float(np.max(np.maximum.accumulate(equity) - equity))


def summarize(trades):
    def side(key):
        x = np.asarray([float(t[key]) for t in trades], dtype=float)
        if not np.all(np.isfinite(x)):
            raise ValueError("Nonfinite outcomes invalidate evidence")
        n = len(x)
        wins, losses = x[x > 0], x[x < 0]
        mean = float(x.mean()) if n else None
        variance = float(x.var(ddof=1)) if n > 1 else None
        se = math.sqrt(variance / n) if n > 1 else None
        # Constant outcomes are insufficient for inferential promotion.
        t = mean / se if se and se > 0 else None
        ci = list(map(float, stats.t.interval(.95, n-1, loc=mean, scale=se))) if t is not None else None
        return dict(sample_size=n, pnl=float(x.sum()), expectancy=mean,
                    expectancy_r=float(np.mean([float(v[key]) / float(v["initial_risk"]) for v in trades])) if n else None,
                    win_rate=float(len(wins)/n) if n else None,
                    average_win=float(wins.mean()) if len(wins) else None,
                    average_loss=float(losses.mean()) if len(losses) else None,
                    payoff_ratio=float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
                    profit_factor=float(wins.sum() / -losses.sum()) if len(losses) else None,
                    maximum_realized_drawdown=drawdown(x), variance=variance,
                    standard_deviation=math.sqrt(variance) if variance is not None else None,
                    standard_error=se, t_statistic=t, expectancy_ci95_iid=ci,
                    one_sided_p_iid=float(stats.t.sf(t, n-1)) if t is not None else None)
    return {"gross": side("gross_pnl"), "net": side("net_pnl"),
            "iid_statistics_are_descriptive": True}


def block_bootstrap(trades, sessions, *, block_length=5, replicates=20000, seed=731):
    """Moving blocks of adjacent sessions; retain intraday ordering and zero-trade days.

    Fold boundaries must be handled by separate calls. One-sided centered null
    test of net mean <=0; finite-replicate plus-one p-value. No IID resampling.
    """
    if (type(block_length) is not int or block_length < 2 or type(replicates) is not int
            or replicates < 100 or type(seed) is not int or len(set(sessions)) != len(sessions)):
        raise ValueError("Invalid block bootstrap configuration")
    groups = {day: [] for day in sessions}
    for trade in trades:
        if trade["session"] not in groups:
            raise ValueError("Outcome outside declared sessions")
        value = float(trade["net_pnl"])
        if not math.isfinite(value):
            raise ValueError("Nonfinite bootstrap input")
        groups[trade["session"]].append(value)
    ordered = [groups[d] for d in sessions]
    n, count = len(ordered), len(trades)
    config = dict(method="moving_session_blocks", block_length=block_length,
                  replicates=replicates, seed=seed, sessions=n)
    if n < 4 * block_length or count < 2 or np.var([sum(v) for v in ordered]) == 0:
        return dict(config=config, sufficient=False, expectancy_ci95=None,
                    net_pnl_ci95=None, drawdown_ci95=None, p_positive=None)
    rng = np.random.default_rng(seed)
    observed = sum(float(t["net_pnl"]) for t in trades) / count
    means, totals, dds, null_means = [], [], [], []
    for _ in range(replicates):
        starts = rng.integers(0, n - block_length + 1, size=math.ceil(n / block_length))
        indices = [i for start in starts for i in range(start, start + block_length)][:n]
        values = [v for i in indices for v in ordered[i]]
        if not values:
            continue
        means.append(float(np.mean(values)))
        totals.append(float(sum(values)))
        dds.append(drawdown(values))
        null_means.append(float(np.mean(np.asarray(values) - observed)))
    if len(means) < .95 * replicates:
        return dict(config=config, sufficient=False, expectancy_ci95=None,
                    net_pnl_ci95=None, drawdown_ci95=None, p_positive=None)
    interval = lambda x: list(map(float, np.quantile(x, [.025, .975])))
    return dict(config=config, sufficient=True, expectancy_ci95=interval(means),
                net_pnl_ci95=interval(totals), drawdown_ci95=interval(dds),
                p_positive=(1 + sum(x >= observed for x in null_means)) / (len(null_means)+1))


def adjust_pvalues(values, method="by"):
    """Count even unavailable/failed hypotheses as p=1; BY permits dependent arms."""
    if method not in ("bh", "by"):
        raise ValueError("Unsupported correction")
    x = [1. if v is None else float(v) for v in values]
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in x):
        raise ValueError("Invalid p-value")
    return dict(method="Benjamini-Yekutieli" if method == "by" else "Benjamini-Hochberg",
                hypotheses_tested=len(x), raw=list(values),
                adjusted=list(map(float, stats.false_discovery_control(x, method=method))) if x else [])


def calibration(observations, buckets=5):
    """Explicit P(win) only; confidence/P(action) is a different diagnostic."""
    valid = [o for o in observations if o.get("probability_win") is not None]
    if any(not 0 <= o["probability_win"] <= 1 or o["won"] not in (0, 1) for o in valid):
        raise ValueError("Invalid probability evidence")
    curve = []
    for i in range(buckets):
        group = [o for o in valid if min(int(o["probability_win"] * buckets), buckets-1) == i]
        curve.append(dict(lower=i/buckets, upper=(i+1)/buckets, count=len(group),
                          predicted=float(np.mean([o["probability_win"] for o in group])) if group else None,
                          actual=float(np.mean([o["won"] for o in group])) if group else None))
    n = len(valid)
    brier = float(np.mean([(o["probability_win"]-o["won"])**2 for o in valid])) if n else None
    error = sum(c["count"] * abs(c["predicted"]-c["actual"]) for c in curve if c["count"]) / n if n else None
    nonconstant = n >= 30 and len({o["probability_win"] for o in valid}) > 1 and len({o["won"] for o in valid}) > 1
    ranking = stats.spearmanr([o["probability_win"] for o in valid], [o["won"] for o in valid]) if nonconstant else None
    action_values = [o for o in observations if o.get("probability_action") is not None]
    action_ranking = None
    if (len(action_values) >= 30 and len({o["probability_action"] for o in action_values}) > 1
            and len({o["won"] for o in action_values}) > 1):
        r = stats.spearmanr([o["probability_action"] for o in action_values], [o["won"] for o in action_values])
        action_ranking = dict(rho=float(r.statistic), p_value_descriptive=float(r.pvalue))
    by_action = {}
    for action in sorted({o.get("action", "unspecified") for o in action_values}):
        group = [o for o in action_values if o.get("action", "unspecified") == action]
        rank = None
        if len(group)>=30 and len({o["probability_action"] for o in group})>1 and len({o["won"] for o in group})>1:
            r = stats.spearmanr([o["probability_action"] for o in group], [o["won"] for o in group])
            rank = dict(rho=float(r.statistic), p_value_descriptive=float(r.pvalue))
        by_action[action] = dict(count=len(group), raw_candidate_win_ranking=rank)
    return dict(sample_size=n, buckets=curve, brier_score=brier, calibration_error=error,
                ranking=dict(rho=float(ranking.statistic), p_value_descriptive=float(ranking.pvalue)) if ranking else None,
                statistically_adequate=n >= 100 and all(c["count"] >= 10 for c in curve),
                action_probability_ranking=action_ranking,
                action_probability_ranking_by_action=by_action,
                action_probability_is_not_win_probability=True)


def stability(results, selected):
    """Fixed neighborhoods on development data only, never maximize holdout."""
    ordered = sorted(results)
    adequate = len(ordered) >= 3 and selected in results and all(results[k]["sample_size"] >= 30 for k in ordered)
    positive = [k for k in ordered if results[k]["expectancy"] is not None and results[k]["expectancy"] > 0]
    stable = adequate and len(positive) == len(ordered)
    return dict(status="STABLE" if stable else "FRAGILE" if adequate else "INSUFFICIENT_EVIDENCE",
                selected=selected, neighborhood=results, optimized=False)
