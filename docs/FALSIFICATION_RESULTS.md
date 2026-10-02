# JEV v0.3 — Actual repository-data results

Research run on 2026-10-02. No edge demonstrated; Practice remains **INSUFFICIENT_EVIDENCE**.

These are retrospective, unverified data, not independently untouched MNQ evidence. No delta or model decisions were manufactured. No parameters were optimized.

## NQ dataset

Source: `data\Dataset_NQ_1min_2022_2025.csv`; SHA-256 `1577e60a7feab411e49da7a56c7052a64738cd1757cfd60aa11fd783ff43b60b`.

Sessions: 765; valid 729; quarantined 36. Dataset audit: FAIL.

Train / validation / test: 459 / 153 / 153 sessions.

Final correction: Benjamini-Yekutieli, 144 hypotheses (including earlier registered preflight attempts as p=1; no failed attempt was deleted).

| Hypothesis | Arm | Final N | Gross $ | Net $ | Net EV $ | Net PF | Max realized DD $ | Adjusted p | Development stability | Evidence |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| jev_level_rejection | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_level_rejection | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_level_rejection | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_or_breakout | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_or_breakout | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_or_breakout | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_vwap_reclaim | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_vwap_reclaim | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_vwap_reclaim | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| ohlcv_orb | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_orb | RAW | 26 | 40.0000 | -90.0000 | -3.4615 | 0.8824 | 465.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_orb | RULE | 10 | 200.0000 | 150.0000 | 15.0000 | 1.6667 | 135.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_reversion | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_reversion | RAW | 79 | -572.0000 | -967.0000 | -12.2405 | 0.6230 | 1102.0000 | 1.0000 | FRAGILE | INSUFFICIENT_EVIDENCE |
| ohlcv_reversion | RULE | 14 | -12.0000 | -82.0000 | -5.8571 | 0.7975 | 180.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_trend | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_trend | RAW | 101 | -804.0000 | -1309.0000 | -12.9604 | 0.6015 | 1339.0000 | 1.0000 | FRAGILE | INSUFFICIENT_EVIDENCE |
| ohlcv_trend | RULE | 31 | -332.0000 | -487.0000 | -15.7097 | 0.5295 | 495.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |

Full gross/net metrics, fold CIs, selection diagnostics, multiplicity keys, audit results, neighborhoods and source/plan fingerprints: [nq.json](results/v03/nq.json).

### Validation observations (not final-test tuning)

| Hypothesis | RAW N / net $ | RULE N / net $ |
|---|---:|---:|
| ohlcv_trend | 88 / -1080.0 | 19 / -135.0 |
| ohlcv_orb | 34 / -90.0 | 20 / 60.0 |
| ohlcv_reversion | 68 / -213.0 | 14 / -30.0 |

## MNQ dataset

Source: `data\mnq_2026_1min.csv`; SHA-256 `321de169ddece8805a11b95aed769a4c4332fb38500aa499036c998877b12f46`.

Sessions: 83; valid 41; quarantined 42. Dataset audit: FAIL.

Train / validation / test: 49 / 17 / 17 sessions.

Final correction: Benjamini-Yekutieli, 144 hypotheses (including earlier registered preflight attempts as p=1; no failed attempt was deleted).

| Hypothesis | Arm | Final N | Gross $ | Net $ | Net EV $ | Net PF | Max realized DD $ | Adjusted p | Development stability | Evidence |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| jev_level_rejection | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_level_rejection | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_level_rejection | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_or_breakout | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_or_breakout | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_or_breakout | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_vwap_reclaim | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_vwap_reclaim | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| jev_vwap_reclaim | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | STABLE | INSUFFICIENT_EVIDENCE |
| ohlcv_orb | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_orb | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_orb | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_reversion | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_reversion | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_reversion | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_trend | JEV | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_trend | RAW | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| ohlcv_trend | RULE | 0 | 0.0000 | 0.0000 | unavailable | unavailable | 0.0000 | 1.0000 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |

Full gross/net metrics, fold CIs, selection diagnostics, multiplicity keys, audit results, neighborhoods and source/plan fingerprints: [mnq.json](results/v03/mnq.json).

## Conclusions and remaining evidence

- No strategy/arm demonstrated verified positive OOS edge. All 36 final dataset × strategy × arm states are INSUFFICIENT_EVIDENCE; this is not proof that every mechanism is unprofitable.
- RULE versus RAW: see the final tables and paired contrasts in the JSON. A higher descriptive EV/P&L is not statistically defensible incremental value when fold consistency, sample and corrected inference fail.
- JEV versus RAW/RULE: not demonstrated. There is no frozen model-decision log; JEV stands aside with zero executions. Cash avoiding a losing RAW strategy is not evidence of model skill.
- No tested edge survived the required adjusted inference, samples, quality and provenance layers. Fixed neighborhoods are reported, including FRAGILE and INSUFFICIENT_EVIDENCE outcomes; no optimum was selected.
- Mechanical audit of recorded trades passed. Dataset audit failed. Empty order-flow/JEV audits are explicitly vacuous, not proof of edge. Shortened holiday sessions are among rejected NQ days because no exchange calendar exists.
- MNQ has only 17 final sessions: zero full 20-session final folds; no thresholds were shortened. Signed-volume-dependent candidates stay unavailable.
- Before Practice: independently sourced clean MNQ history and genuinely new holdout; verified signed delta for order-flow; complete causal JEV logs if testing JEV; sufficient full OOS folds/trades; stable development neighborhood; positive net block CIs and BY support; valid market and trade audit; cost/roll/session validation. No Combine/live action is authorized.

## Verification

Full repository suite: **292 passed, 0 failed, 52 existing deprecation warnings, 475.92 seconds**. After the final research-only holdout-quality isolation and runtime-manifest refinements: **93 research/regression tests passed, 0 failed, 0 warnings, 5.95 seconds**. The 72 new tests include adversarial leakage, fake-delta provenance, costs/fills, risk bypass, direction/size modification, multiple-testing false winners, parameter fragility, holdout reuse and artifact tampering.

Large fold ledgers/shadow/actual trade artifacts remain in the local `output/falsification-v03/*-final/` directories; summaries publish their names and checksums. They are not committed wholesale. Preserve the plans, development seals, consumed-holdout and trial registries when archiving research. Reproduction requires the recorded code/runtime/input and trial history; rerunning a consumed test is intentionally refused.

See [methodology and exact frozen gates](FALSIFICATION.md).
