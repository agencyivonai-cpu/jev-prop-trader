"""Frozen promotion criteria. Missing evidence cannot become PASS."""


def evidence_state(result, source, *, family, stability_report, adjusted_p, incremental=None):
    arms = result["folds"]
    missing = []
    if not source.get("independent_real_data"):
        missing.append("independent_real_data_provenance")
    if not source.get("unseen_holdout"):
        missing.append("genuinely_unseen_holdout")
    if source.get("source_symbol") != "MNQ":
        missing.append("MNQ_execution_volume_evidence_not_NQ_proxy")
    if family == "order_flow" and not source.get("signed_delta_verified"):
        missing.append("verified_real_signed_volume")
    if not result["data_valid"] or not result["audit_valid"] or not result["filter_valid"]:
        missing.append("valid_data_mechanical_audit_and_causal_filter")
    if not result["available"]:
        missing.append("frozen_jev_filter_decisions")
    if len(arms) < 3 or any(f["metrics"]["net"]["sample_size"] < 30 for f in arms):
        missing.append("three_OOS_folds_with_30_trades_each")
    if result["metrics"]["net"]["sample_size"] < 100:
        missing.append("100_OOS_trades")
    if any(not f["bootstrap"]["sufficient"] for f in arms) or adjusted_p is None:
        missing.append("adequate_session_block_inference_and_multiplicity")
    if stability_report["status"] == "INSUFFICIENT_EVIDENCE":
        missing.append("development_parameter_neighborhood_sample")
    if missing:
        return dict(state="INSUFFICIENT_EVIDENCE", reasons=missing)
    checks = dict(
        positive_net=result["metrics"]["net"]["expectancy"] > 0,
        profit_factor=result["metrics"]["net"]["profit_factor"] is not None
                      and result["metrics"]["net"]["profit_factor"] >= 1.2,
        drawdown=result["metrics"]["net"]["maximum_realized_drawdown"] <= 800,
        all_folds_positive=all(f["metrics"]["net"]["pnl"] > 0 for f in arms),
        all_folds_drawdown=all(f["metrics"]["net"]["maximum_realized_drawdown"] <= 800 for f in arms),
        block_ci_positive=all(f["bootstrap"]["expectancy_ci95"][0] > 0 for f in arms),
        adjusted_support=adjusted_p <= .05,
        stable=stability_report["status"] == "STABLE")
    if incremental is not None:
        checks["incremental_over_both_controls"] = incremental.get("supported", False)
    return dict(state="SURVIVES" if all(checks.values()) else "FAILS",
                checks=checks, reasons=[k for k, v in checks.items() if not v])


def practice_gate(report):
    if report.get("phase") != "test" or not report.get("protocol_verified") or not report.get("holdout_consumed"):
        return dict(status="INSUFFICIENT_EVIDENCE", reason="registered_final_test_required")
    states = []
    try:
        for h in report["results"].values():
            for arm,a in h["arms"].items():
                if any(f["audit"]["status"] != "PASS" for f in a["folds"]):
                    return dict(status="INSUFFICIENT_EVIDENCE", reason="mechanical_audit_failed")
                days = sum((f["sessions"] for f in a["folds"]), [])
                if days != sorted(set(days)):
                    return dict(status="INSUFFICIENT_EVIDENCE", reason="nonchronological_or_overlapping_folds")
                incremental = dict(supported=all(h["contrasts"][p]["supported"] for p in ("JEV-RAW","JEV-RULE"))) if arm=="JEV" else None
                state = evidence_state(a, report["source"], family=a["family"], stability_report=a["stability"],
                                       adjusted_p=a["adjusted_p"], incremental=incremental)
                states.append(state["state"])
    except (KeyError, TypeError, ValueError):
        return dict(status="INSUFFICIENT_EVIDENCE", reason="incomplete_falsification_evidence")
    if "SURVIVES" in states:
        return dict(status="PASS", reason="at_least_one_strategy_arm_survives_all_frozen_layers",
                    research_screen_only=True)
    if "FAILS" in states:
        return dict(status="FAIL", reason="sufficient_evidence_fails_frozen_criteria")
    return dict(status="INSUFFICIENT_EVIDENCE", reason="no_strategy_arm_has_sufficient_evidence")
