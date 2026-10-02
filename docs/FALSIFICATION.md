# JEV v0.3 — Three-arm falsification protocol

This extends `jev/research.py`; it does not replace strategies, RiskGate, or live
components. Research only. **AI proposes → deterministic risk code authorizes →
simulated executor executes.** There is no broker/model API invocation in this package.

Methodology inspiration: [aabrole/claude-trading-desk](https://github.com/aabrole/claude-trading-desk):
identical-candidate three-arm controls, chronological OOS evidence, gross beside net,
and independent mechanical trade audit. Its implementation/deployment integrations
were not imported. The additional safeguards below are specific to this repository.

## Experiment and two families

Every hypothesis/parameter/fold produces one immutable opportunity tuple before
any arm is evaluated. RAW approves all candidates, RULE applies fixed interpretable
filters, and JEV can only APPROVE or STAND_ASIDE. Direction, entry, stop, target,
contracts, account risk and authorization are outside the filter schema. Every
approved candidate still passes the existing RiskGate. All arms have separate
identical starting accounts and identical cost/execution settings. Account paths
can diverge, so policy-P&L differences are not pure selection effects.

Default RULE: relative volume at the same minute >=1.2, candle body fraction >=0.5,
and signed 30-minute trend alignment >0. This is a control hypothesis, not proven alpha.

Order-flow family preserves all three v0.1 challengers without altering their rules.
Missing actual signed-volume delta produces no candidates. Even a populated `delta`
column is not used by the study unless external signed-volume provenance is attested.
No delta/CVD/imbalance is fabricated from candles. Numerical validation cannot prove
authenticity; provider/feed documentation remains required.

Separate OHLCV hypotheses, each with fixed 10-point stop and 20-point target:

| Hypothesis | Mechanical trigger | Frozen neighborhood |
|---|---|---|
| `ohlcv_trend` | VWAP cross after signed 30-minute trend separation exceeds threshold × ATR | 0.65, 0.75, 0.85 |
| `ohlcv_orb` | Cross of first 15-minute range, with extension >= threshold × ATR | 0.65, 0.75, 0.85 |
| `ohlcv_reversion` | VWAP reclaim after opposite wick displacement >= threshold × ATR | 0.65, 0.75, 0.85 |

The selected value is **0.75, fixed before evaluation**. No search selects a winner.
Order-flow rules have no tuned neighborhood parameter; their existing thresholds
are fixed and recorded. A STABLE label there means “not tuned”, not evidence of robustness.

Features use only closed one-minute bars. ATR is a rolling 20-bar true-range mean.
The interpretable higher-timeframe proxy compares the last two 15-bar mean closes;
it is not a separately sourced higher-timeframe feed. Same-minute relative volume
uses up to 20 completed preceding sessions; no current full-day volume is accessed.
Additional ORB features: range/ATR, edge extension/ATR, body/wick fractions, previous
level tests, overnight gap/ATR, prior-day and round-number proximity/ATR, wide/narrow
ATR regime (10-point threshold), morning/afternoon ET. `--rule-spec` accepts explicit
feature/operator/value conjunctions to preregister falsifiable ablations. It cannot
reference future/outcome keys. Each ablation is another hypothesis; no automatic
feature search or assertion of improvement is made.

## Data and execution contract

CSV compatibility and open-time timestamp convention are inherited from v0.2.
The source symbol must be declared. NQ is a price/volume proxy, not MNQ evidence.
No sorting, rounding, forward-fill or volume replacement occurs. Entire invalid
RTH sessions are quarantined with reasons, and the dataset is invalid for promotion;
valid-session results are descriptive subsets, not a silently repaired dataset.
Required RTH session is exactly 390 contiguous bars, 09:30–15:59 New York time.
This excludes shortened sessions rather than assuming an incomplete full session
was complete. An exchange holiday/early-close calendar is not implemented.

Shared execution: next bar open must equal the reference entry, otherwise cancel.
No same-bar fills based on the signal candle. One exposure per arm; RiskGate sets
size and budgets ($60 per trade, $200/day, $800 internal drawdown, up to 3 entries,
stop after 2 consecutive net losses). The fixed $48,000 floor is a research profile,
not the full firm's trailing floor or payout rule. Stops resolve before targets if
both touch; an adverse stop gap fills at the worse open. Targets fill at target.
Entry and exit each incur 1 MNQ tick of adverse slippage; round-trip commission is
$1.50/contract. Configurable cost totals may not exceed the gate's $3 reserve.
Exit after 30 bars or the 15:59 close. No position crosses session/fold boundaries.

Gross P&L is reference-price movement × **$2/point/contract**, before either cost.
Net = gross − explicit two-side slippage − round-trip commission. Execution prices
also show slippage; costs are not charged twice. Initial R denominator is reference
stop distance × multiplier × contracts, excluding costs. Both gross and net R
expectancy are reported. Costs are assumptions, not a verified broker schedule.

## TRAIN → VALIDATION → TEST

Session timestamps define chronological 60% train / 20% validation / 20% final test.
Development does not compute final-test features, market-quality statistics or
outcomes. Train is a descriptive baseline; validation contains fixed disjoint
20-session rolling OOS folds. Fixed parameter neighborhoods are evaluated only on
validation. Final test uses later disjoint 20-session folds; partial tails are
reported and omitted. Feature warmup uses completed earlier sessions, never their
future outcomes. No train/validation/test trade crosses boundaries.

`plan.json` freezes source SHA-256, splits, hypotheses, filter/model-log fingerprint,
execution settings, bootstrap, correction, gates, Python/NumPy/SciPy versions and
implementation hash. Changed code, parameters, model logs, source or splits invalidate
the plan. Development results are checksum-sealed. Final-test consumption is written
**before** outcomes, using exclusive file creation. Failure does not allow a retry.
A shared sibling dataset registry blocks reuse in another study directory and
further development after final-test consumption. A shared trial registry retains
54 hypotheses per earlier registered development plan, conservatively counting
unavailable prior results as p=1. Keep these registries with the research artifacts.

These are local research-discipline controls, not a security boundary against
someone deleting registries, falsifying provenance, or supplying post-hoc model
logs. Unknown earlier searches cannot be inferred from files. All prior trials and
model training/contamination history must be disclosed before genuine promotion.
The existing repo has historical optimization outputs, so its chronological test
is labelled **retrospective/unverified**, not independently untouched evidence.

## Statistical engine and contrasts

Per strategy/arm/fold: sample, gross/net P&L, expectancy, expectancy in R, win rate,
average win/loss, payoff ratio, profit factor, realized drawdown from zero, sample
variance/std, standard error, t-statistic and Student-t 95% expectancy CI.
[SciPy t-test diagnostics](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_1samp.html)
are descriptive IID statistics; they do not establish serially dependent edge.
Empty/constant samples produce unavailable statistics, not invented certainty.

Inference uses moving blocks of **5 adjacent sessions**, retaining intraday trade
order and zero-trade days, 20,000 replicates, seed 731. At least 20 sessions, two
trades, varying daily P&L and 95% usable resamples are required. Outputs include
percentile 95% CI for expectancy, net P&L and realized drawdown; a centered one-sided
null test of mean net return <=0 uses plus-one Monte Carlo p-values. No blocks cross
folds. All folds must support the hypothesis; the maximum per-fold p-value is the
conservative intersection-union result. This does not assume independence across
folds. Block length is frozen; dependence beyond five sessions remains a limitation.

[Benjamini–Yekutieli correction](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html)
handles dependence between arms/hypotheses. All 18 selected strategy/arm tests,
18 arm contrasts, and 18 OHLCV neighborhood attempts count in development (54).
Neighborhoods are stability screens with p=1 for inference, not additional significance
claims. Final test adds 36 tests to all development attempts and previously registered
trials. Missing/failed hypotheses remain p=1. Report raw/adjusted results and the exact
family size. No isolated best performer, IID p<0.05, or t>2 authorizes promotion.

Selection diagnostics use **identical one-contract shadow outcomes** for all arms:
EV(accepted), EV(rejected), EV(raw), accepted−raw and accepted−rejected, acceptance/
stand-aside rates, candidate/execution counts and unresolved outcomes. Overlapping
shadow trades are explicitly counterfactual, never account performance. Inferential
uplift uses paired session net-P&L contrasts RULE−RAW, JEV−RAW, JEV−RULE, including
abstention days. This measures policy uplift, which includes account-path effects.

JEV logs must bind each candidate + causal features to a digest and exact decision
timestamp/model version. Missing/invalid decisions stand aside and make JEV evidence
unavailable. No model is invented or called in this PR. Optional P(chosen action),
explicit P(win), and confidence remain distinct. Only explicit P(win) is calibrated
against net-positive unit outcomes: five probability buckets, actual frequencies,
Brier score, calibration error and descriptive rank correlations. P(action) is
analysed separately and by action; confidence is never interpreted as probability.
Calibration adequacy requires >=100 outcomes and >=10 observations in every bucket.
These rank diagnostics are exploratory, not promotion tests or probability of payout.

## Mechanical audit

Independent auditor does not call the simulated fill function. It reconstructs
first possible fill/exit, stop-first ambiguity, adverse gaps, information times,
session/fold boundaries, candidate/feature integrity, risk authorization/size,
exposure overlap, OHLC/tick/volume/gaps, multiplier, commission/slippage and gross/net
P&L. Audit failure invalidates evidence. Empty audit PASS means no recorded trade
failed; it is explicitly not proof of correctness/edge. Data audit is separate.
Actual signed-volume authenticity and hidden external model leakage require provider
evidence; a mathematical consistency check cannot establish either.

## Exact evidence states and Practice gate

INSUFFICIENT_EVIDENCE if any required item is unavailable: independently verified
real MNQ data (NQ proxy is insufficient), genuinely untouched holdout, verified delta
for order-flow, no unresolved data errors, valid causal filter and mechanical audit,
complete JEV decisions for JEV arm, >=3 OOS folds with >=30 trades each and >=100
total, adequate session-block inference, registered multiplicity correction and
adequate development neighborhood samples (>=30 per tested neighbor).

With sufficient evidence, SURVIVES requires **all**: net expectancy >0, finite net
PF >=1.2, combined and each-fold realized drawdown <=$800, positive net P&L in every
fold, each-fold block-bootstrap CI lower bound >0, BY-adjusted edge p<=0.05, and
all three development neighbors net-positive. An isolated optimum is FRAGILE and
fails. JEV additionally needs supported adjusted paired uplift over **both** RAW
and RULE; matching RULE does not demonstrate incremental JEV value. Otherwise FAILS.

Practice PASS requires a consumed, verified final-test protocol and at least one
arm that survives every relevant layer. With no survivors but a sufficiently
evidenced failure, FAIL; otherwise INSUFFICIENT_EVIDENCE. The gate recomputes states
instead of trusting a user-supplied SURVIVES label. v0.2-only summaries always return
INSUFFICIENT_EVIDENCE. PASS is an internal research screen, never live authorization.

## Run and preserve evidence

```
python -m jev.falsification.study data/Dataset_NQ_1min_2022_2025.csv --source-symbol NQ --timezone America/New_York --study-dir output/studies/nq --phase development
python -m jev.falsification.study data/Dataset_NQ_1min_2022_2025.csv --source-symbol NQ --timezone America/New_York --study-dir output/studies/nq --phase test
```

Optional `--rule-spec` is a JSON list of feature/operator/value rules; optional
`--jev-records` contains `model_version` and `records` keyed by candidate ID. Both
are frozen before the test. CLI cannot self-attest independent provenance, an unseen
holdout, or delta authenticity. Programmatic source attestations must be backed by
external evidence; booleans alone are not verification performed by this framework.

Artifacts include plan, development/test summaries, checksums, full fold candidate
ledgers and shadow/actual trades. Actual trades record session, contracts, initial
risk, costs, authorized risk and times, allowing a later validated account/payout
simulator. **P(first payout before failure) is not implemented or claimed.** Remaining
limitations include fixed floor, no exchange calendar, spreads/queues/market impact,
contract rolls/news, open-position drawdown and cost-stress tests. The strict unchanged
next-open rule rejects many signals; it has not been relaxed to obtain more trades.
