"""Persisted preregistration and one-use chronological final holdout discipline."""
import json
from dataclasses import asdict
from pathlib import Path

from .market import HYPOTHESES, NEIGHBORHOOD
from .simulation import digest


def implementation_hash():
    root = Path(__file__).resolve().parent.parent
    files = list((root/"falsification").glob("*.py")) + [root/n for n in (
        "research.py", "risk.py", "registry.py", "profiles.py", "types.py", "challengers.py")]
    return digest({str(p.relative_to(root)): p.read_text(encoding="utf-8").replace("\r\n", "\n") for p in sorted(files)})


def specification(config, jev_fingerprint=None, rule_fingerprint=None):
    import platform
    import numpy
    import scipy
    return dict(hypotheses=[asdict(h) for h in HYPOTHESES], neighborhood=list(NEIGHBORHOOD),
                execution=asdict(config), rule_filter="rvol_tod>=1.2;body>=0.5;aligned_trend>0",
                jev_fingerprint=jev_fingerprint, bootstrap=dict(block_length=5, replicates=20000, seed=731),
                rule_fingerprint=rule_fingerprint,
                correction="Benjamini-Yekutieli", alpha=.05,
                gates=dict(min_total_trades=100, min_trades_per_fold=30, min_folds=3,
                           max_drawdown=800, min_profit_factor=1.2,
                           ci_lower_strictly_positive=True, all_fold_net_positive=True,
                           stability="all_three_neighbors_positive_at_30_trades_each"),
                runtime=dict(python=platform.python_version(), numpy=numpy.__version__, scipy=scipy.__version__),
                implementation_hash=implementation_hash())


def partition(days):
    if days != sorted(set(days)):
        raise ValueError("Chronological unique session labels required")
    n = len(days)
    a, b = int(n*.6), int(n*.8)
    return dict(train=days[:a], validation=days[a:b], test=days[b:])


def register(directory, days, source, spec):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    partitions = partition(days)
    path = root/"plan.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        verify_plan(existing, source, spec)
        if existing["partitions"] != partitions:
            raise ValueError("Changed dataset session partitions")
        return existing
    registry = root.parent/"trial_registry"
    registry.mkdir(exist_ok=True)
    trials_path = registry/(source["sha256"]+".json")
    trials = json.loads(trials_path.read_text(encoding="utf-8")) if trials_path.exists() else []
    plan = dict(version="0.3", source=source, partitions=partitions, specification=spec,
                selection="fixed_0.75_no_optimization", final_outcomes_used=False,
                prior_registered_hypotheses=sum(t["hypotheses"] for t in trials))
    plan["fingerprint"] = digest(plan)
    with path.open("x", encoding="utf-8") as f:
        json.dump(plan, f, default=str, sort_keys=True, indent=2)
    trials.append(dict(plan_fingerprint=plan["fingerprint"], hypotheses=54))
    trials_path.write_text(json.dumps(trials, sort_keys=True, indent=2), encoding="utf-8")
    return json.loads(json.dumps(plan, default=str))


def verify_plan(plan, source, spec):
    unsigned = {k: v for k, v in plan.items() if k != "fingerprint"}
    if (digest(unsigned) != plan["fingerprint"] or plan["source"] != source
            or digest(plan["specification"]) != digest(spec)):
        raise ValueError("Changed source, code, model or parameters: holdout invalidated")
    combined = sum((plan["partitions"][k] for k in ("train", "validation", "test")), [])
    if partition(combined) != plan["partitions"]:
        raise ValueError("Overlapping or nonchronological holdout")


def consume_holdout(directory, plan):
    root = Path(directory)
    # Dataset lock is shared by sibling study directories, not just this plan.
    registry = root.parent/"holdout_registry"
    registry.mkdir(exist_ok=True)
    key = plan["source"]["sha256"]
    path = registry/(key+".json")
    entry = dict(plan_fingerprint=plan["fingerprint"], test_sessions=plan["partitions"]["test"],
                 state="CONSUMED_BEFORE_OUTCOMES", no_retry_on_failure=True)
    try:
        with path.open("x", encoding="utf-8") as f:
            json.dump(entry, f, sort_keys=True, indent=2)
    except FileExistsError as e:
        raise ValueError("Dataset holdout already consumed; further tuning requires genuinely new data") from e
    return str(path)


def assert_development_allowed(directory, source):
    lock = Path(directory).parent/"holdout_registry"/(source["sha256"]+".json")
    if lock.exists():
        raise ValueError("Holdout observed: development on this registered dataset is invalid")
