"""CLI: register/develop, then consume final holdout once. No execution integrations."""
import argparse
import hashlib
import json
from datetime import time
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from ..research import ET, ResearchConfig, load_bars
from .audit import audit_trades
from .gates import evidence_state, practice_gate
from .market import (HYPOTHESES, NEIGHBORHOOD, feature_tape,
                     opportunities_from_tape, validate_sessions)
from .protocol import (assert_development_allowed, consume_holdout, register,
                       specification, verify_plan)
from .simulation import FeatureRule, FeatureRuleFilter, RecordedJEV, run_arms, digest
from .statistics import adjust_pvalues, block_bootstrap, stability, summarize


def dump(value, path):
    Path(path).write_text(json.dumps(value, default=str, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")


def fold_days(days, width=20):
    return [days[i:i+width] for i in range(0, len(days)-width+1, width)]


def evaluate(tape, sessions, days, hypothesis, config, jev, source, directory, label, *, inferential=True, rule=None):
    combined = {arm: dict(trades=[], folds=[], available=arm != "JEV" or jev is not None,
                          filter_valid=True, audit_valid=True) for arm in ("RAW", "RULE", "JEV")}
    folds = fold_days(days)
    all_selection = {arm: [] for arm in combined}
    paths = []
    for index, fold in enumerate(folds):
        selected_sessions = {d: sessions[d] for d in fold if d in sessions}
        ops = opportunities_from_tape(tape, hypothesis, fold)
        if hypothesis.family == "order_flow" and not source.get("signed_delta_verified"):
            ops = ()  # reject fabricated/unattested delta before candidate generation can authorize
        result = run_arms(ops, selected_sessions, config=config, jev=jev, rule=rule, fold=f"{label}:{index}")
        path = Path(directory)/f"{label}_{hypothesis.name}_{hypothesis.threshold}_{index}.json"
        # Evidence records are kept separately; summary reports remain reviewable.
        dump(result, path)
        paths.append(dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        for arm, data in result["arms"].items():
            audit = audit_trades(data["trades"], ops, selected_sessions, config,
                                 fold=f"{label}:{index}", family=hypothesis.family,
                                 signed_delta_verified=source.get("signed_delta_verified", False))
            bootstrap = block_bootstrap(data["trades"], fold) if inferential else dict(
                sufficient=False, p_positive=None, expectancy_ci95=None, screening_only=True)
            combined[arm]["folds"].append(dict(sessions=fold, metrics=data["metrics"], bootstrap=bootstrap,
                                                audit=audit, selection=data["selection"], calibration=data["calibration"]))
            combined[arm]["trades"].extend(data["trades"])
            combined[arm]["filter_valid"] &= result["filter_valid"]
            combined[arm]["available"] &= data["available"]
            combined[arm]["audit_valid"] &= audit["status"] == "PASS"
            all_selection[arm].append(data["selection"])
    for arm, data in combined.items():
        data["metrics"] = summarize(data["trades"])
        data["raw_p"] = max((f["bootstrap"]["p_positive"] if f["bootstrap"]["p_positive"] is not None else 1
                             for f in data["folds"]), default=None)
        counts = sum(x["number_candidates"] for x in all_selection[arm])
        accepted = sum(x["accepted_resolved"] for x in all_selection[arm])
        rejected = sum(x["rejected_resolved"] for x in all_selection[arm])
        weighted = lambda name, key: (sum(x[name]*x[key] for x in all_selection[arm] if x[name] is not None)
                                     / sum(x[key] for x in all_selection[arm] if x[name] is not None)) if any(
                                         x[name] is not None and x[key] for x in all_selection[arm]) else None
        ea, er = weighted("ev_accepted", "accepted_resolved"), weighted("ev_rejected", "rejected_resolved")
        raw = weighted("ev_raw", "accepted_resolved") if arm == "RAW" else None
        data["selection"] = dict(number_candidates=counts, number_executed=len(data["trades"]),
                                 accepted_resolved=accepted, rejected_resolved=rejected,
                                 ev_accepted=ea, ev_rejected=er,
                                 acceptance_rate=sum((x["acceptance_rate"] or 0)*x["number_candidates"] for x in all_selection[arm])/counts if counts else None,
                                 stand_aside_rate=sum((x["stand_aside_rate"] or 0)*x["number_candidates"] for x in all_selection[arm])/counts if counts else None,
                                 ev_raw=raw, accepted_minus_rejected=ea-er if ea is not None and er is not None else None,
                                 unresolved=sum(x["unresolved"] for x in all_selection[arm]))
    raw_ev = combined["RAW"]["selection"]["ev_raw"]
    for data in combined.values():
        ea = data["selection"]["ev_accepted"]
        data["selection"]["ev_raw"] = raw_ev
        data["selection"]["selection_uplift"] = ea-raw_ev if ea is not None and raw_ev is not None else None
    return dict(arms=combined, artifacts=paths, dropped_tail_sessions=len(days)%20)


def paired_incremental(left, right):
    """Paired session P&L contrasts. Account paths differ; this is policy uplift."""
    folds = []
    for lf, rf in zip(left["folds"], right["folds"]):
        days = lf["sessions"]
        if days != rf["sessions"]:
            raise ValueError("Mismatched arms")
        values = []
        for day in days:
            x = sum(float(t["net_pnl"]) for t in left["trades"] if t["session"] == day)
            y = sum(float(t["net_pnl"]) for t in right["trades"] if t["session"] == day)
            values.append(dict(session=day, net_pnl=x-y))
        folds.append(block_bootstrap(values, days))
    return dict(folds=folds, raw_p=max((f["p_positive"] if f["p_positive"] is not None else 1 for f in folds), default=None),
                all_ci_positive=bool(folds) and all(f["sufficient"] and f["expectancy_ci95"][0]>0 for f in folds),
                estimand="paired_net_policy_PnL_per_session_including_abstentions")


def run_study(bars, source, directory, *, phase="development", config=ResearchConfig(), jev=None, rule=None):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    # Partition all observed session dates, including quarantine: never silently remove bad days.
    all_days = sorted({b.timestamp.astimezone(ET).date().isoformat()
                       for b in bars if time(9, 30) <= b.timestamp.astimezone(ET).time() < time(16)})
    spec = specification(config, jev.fingerprint if jev else None, rule.fingerprint if rule else None)
    if phase == "development":
        assert_development_allowed(root, source)
        plan = register(root, all_days, source, spec)
    elif phase == "test":
        plan = json.loads((root/"plan.json").read_text(encoding="utf-8"))
        verify_plan(plan, source, spec)
        development = json.loads((root/"development.json").read_text(encoding="utf-8"))
        seal = json.loads((root/"development.seal.json").read_text(encoding="utf-8"))
        if seal["sha256"] != hashlib.sha256((root/"development.json").read_bytes()).hexdigest():
            raise ValueError("Development evidence was changed after sealing")
        if development["plan_fingerprint"] != plan["fingerprint"]:
            raise ValueError("Development evidence from another protocol")
        consume_holdout(root, plan)
    else:
        raise ValueError("Only development or test phases supported")
    permitted_days = plan["partitions"]["train"]+plan["partitions"]["validation"]
    if phase == "test":
        permitted_days += plan["partitions"]["test"]
    allowed = set(permitted_days)
    # Holdout OHLCV values are not even quality-evaluated during development.
    # Only timestamp labels and the source checksum are used to define the split.
    scoped = [b for b in bars if b.timestamp.astimezone(ET).date().isoformat() in allowed]
    sessions, quality = validate_sessions(scoped)
    # No final-test feature tape is constructed during development.
    tape = feature_tape({d: sessions[d] for d in permitted_days if d in sessions})
    evaluation_days = plan["partitions"]["validation" if phase == "development" else "test"]
    results, pvalues, keys, neighborhoods = {}, [], [], {}
    for h in HYPOTHESES:
        result = evaluate(tape, sessions, evaluation_days, h, config, jev, source, root, phase, rule=rule)
        results[h.name] = result
        # Selected parameter was preregistered, never selected from validation performance.
        neighbors = {}
        if phase == "development":
            train = evaluate(tape, sessions, plan["partitions"]["train"], h, config, jev, source, root, "train", inferential=False, rule=rule)
            result["train_metrics"] = {arm: x["metrics"] for arm, x in train["arms"].items()}
            thresholds = NEIGHBORHOOD if h.family == "ohlcv" else (h.threshold,)
            for threshold in thresholds:
                neighbor = result if threshold == h.threshold else evaluate(tape, sessions, evaluation_days,
                                  replace(h, threshold=threshold), config, jev, source, root, "neighborhood", inferential=False, rule=rule)
                neighbors[str(threshold)] = {arm: x["metrics"]["net"] for arm, x in neighbor["arms"].items()}
                if threshold != h.threshold:
                    for arm, x in neighbor["arms"].items():
                        pvalues.append(x["raw_p"])
                        keys.append(f"{h.name}:{threshold}:{arm}:neighborhood")
            neighborhoods[h.name] = {arm: stability({k:dict(sample_size=v[arm]["sample_size"], expectancy=v[arm]["expectancy"])
                                                    for k,v in neighbors.items()}, str(h.threshold))
                                      if h.family == "ohlcv" else dict(status="STABLE", reason="no_tuned_parameter", neighborhood={})
                                      for arm in ("RAW", "RULE", "JEV")}
        else:
            neighborhoods[h.name] = development["neighborhoods"][h.name]
        for arm, data in result["arms"].items():
            pvalues.append(data["raw_p"])
            keys.append(f"{h.name}:{arm}:edge")
        result["contrasts"] = {}
        for lhs,rhs in (("RULE", "RAW"), ("JEV", "RAW"), ("JEV", "RULE")):
            contrast = paired_incremental(result["arms"][lhs], result["arms"][rhs])
            result["contrasts"][f"{lhs}-{rhs}"] = contrast
            pvalues.append(contrast["raw_p"])
            keys.append(f"{h.name}:{lhs}-{rhs}:uplift")
    # Include every development hypothesis in final multiplicity family; no winner-only correction.
    if phase == "test":
        pvalues += development["multiplicity"]["raw"]
        keys += ["development:"+k for k in development["multiplicity"]["keys"]]
    if phase == "development":
        prior = plan["prior_registered_hypotheses"]
        pvalues += [None]*prior
        keys += [f"prior_registered_trial:{i}" for i in range(prior)]
    corrected = adjust_pvalues(pvalues)
    corrected["keys"] = keys
    lookup = dict(zip(keys, corrected["adjusted"]))
    for h in HYPOTHESES:
        result = results[h.name]
        for pair, contrast in result["contrasts"].items():
            contrast["adjusted_p"] = lookup[f"{h.name}:{pair}:uplift"]
            lhs,rhs = pair.split("-")
            contrast["statistical_screen_positive"] = contrast["all_ci_positive"] and contrast["adjusted_p"] <= .05
            contrast["supported"] = (contrast["statistical_screen_positive"]
                and result["arms"][lhs]["available"] and result["arms"][rhs]["available"]
                and quality["status"] == "PASS" and source.get("independent_real_data",False)
                and source.get("unseen_holdout",False) and source.get("source_symbol") == "MNQ")
        for arm,data in result["arms"].items():
            data["data_valid"] = quality["status"] == "PASS"
            data["adjusted_p"] = lookup[f"{h.name}:{arm}:edge"]
            data["stability"] = neighborhoods[h.name][arm]
            incremental = dict(supported=all(result["contrasts"][p]["supported"] for p in ("JEV-RAW", "JEV-RULE"))) if arm == "JEV" else None
            data["evidence"] = evidence_state(data, source, family=h.family, stability_report=data["stability"],
                                               adjusted_p=data["adjusted_p"], incremental=incremental)
            if phase == "development":
                data["evidence"] = dict(state="INSUFFICIENT_EVIDENCE", reasons=["development_is_not_final_OOS_evidence"])
            data["family"] = h.family
            # Trades remain in fold evidence artifacts for future account/payout MC; no probability claim.
            data["trades_artifacts"] = result["artifacts"]
            del data["trades"]
    report = dict(version="0.3", phase=phase, plan_fingerprint=plan["fingerprint"], source=source,
                  protocol_verified=True, holdout_consumed=phase=="test", quality=quality,
                  results=results, neighborhoods=neighborhoods, multiplicity=corrected,
                  no_parameter_optimization=True, no_payout_probability_claim=True)
    report["practice_gate"] = practice_gate(report)
    dump(report, root/(phase+".json"))
    if phase == "development":
        dump(dict(sha256=hashlib.sha256((root/"development.json").read_bytes()).hexdigest(),
                  plan_fingerprint=plan["fingerprint"]), root/"development.seal.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("--source-symbol", choices=("MNQ", "NQ"), required=True)
    parser.add_argument("--timezone")
    parser.add_argument("--study-dir", required=True)
    parser.add_argument("--phase", choices=("development", "test"), default="development")
    parser.add_argument("--jev-records", help="Frozen JSON model_version/records; never invokes a model API")
    parser.add_argument("--rule-spec", help="Preregistered JSON list of feature/operator/value rules")
    args = parser.parse_args()
    path = Path(args.csv)
    source = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source_symbol=args.source_symbol,
                  independent_real_data=False, unseen_holdout=False, signed_delta_verified=False,
                  attestation="unverified_repository_data", timestamp_convention="one_minute_bar_open")
    jev = None
    if args.jev_records:
        payload = json.loads(Path(args.jev_records).read_text(encoding="utf-8"))
        jev = RecordedJEV(payload["records"], payload["model_version"])
    bars = load_bars(path, source_symbol=args.source_symbol, timezone=args.timezone)
    rule = FeatureRuleFilter(FeatureRule(**r) for r in json.loads(Path(args.rule_spec).read_text(encoding="utf-8"))) if args.rule_spec else None
    report = run_study(bars, source, args.study_dir, phase=args.phase, jev=jev, rule=rule)
    print(json.dumps(dict(phase=report["phase"], quality=report["quality"], practice_gate=report["practice_gate"]), indent=2))


if __name__ == "__main__":
    main()
