# JEV v0.2 Research Harness

Offline only: `python -m jev.research INPUT.csv --source-symbol MNQ --output report.json`.
For the existing NQ CSV use `--source-symbol NQ --timezone America/New_York`.
NQ is an explicitly declared price/volume proxy, not MNQ execution evidence.
CSV columns: datetime/timestamp/timestamp ET, open, high, low, close, volume,
optional actual signed-volume delta. Timestamps label the OPEN of one-minute bars.
Naive timestamps require a timezone; ambiguous/nonexistent local DST times fail.
Rows are not sorted, rounded, forward-filled, or assigned invented volume/delta.

Only complete preceding 390-bar 09:30–16:00 New York sessions supply prior-day
levels, with at most four calendar days between sessions. A full exchange holiday
calendar is not implemented. The first 15 closed bars define the opening range. VWAP and relative volume
use only observed closed bars; regime means above/below current VWAP, not a fitted
classifier. Time-of-day means morning before noon and afternoon after noon ET.
Missing actual delta disables candidate generation. Existing OHLCV-only files
therefore do not establish challenger edge. The repo's 2026 file also contains
zero volume and prices outside the MNQ tick grid; these fail closed.

The default proposer picks the first candidate in the fixed challenger order.
An optional offline proposer receives only the current immutable candidates and
may select an ID or WAIT/SKIP/STOP_DAY. It cannot set contracts or risk.
AI proposes -> deterministic risk code authorizes -> executor executes; this
module contains only a simulated executor and imports no live/broker modules.

Ledger records every RTH closed-bar decision, full candidates, selected ID,
authorization and RiskGate reason, plus actual simulated fills and cancellations.
Denied TRADE proposals are recorded as SKIP with the original proposed action.
An authorized TRADE proposal is a plan, not a fill: the next bar must be contiguous,
valid, in session and open at the planned reference entry. Otherwise it is cancelled.
RiskGate runs again at fill time. Only one open/pending position is possible.
Simulation charges $1.50 round-trip commission/contract plus one tick slippage
on each side; configurable costs cannot exceed the existing $3/contract gate reserve.
Stop gaps fill at the worse of open and stop, with slippage; simultaneous stop/target
hits resolve to stop. Targets fill at the target with adverse exit slippage.
Timeout is 30 bars; positions close at 15:59. Missing position bars or an incomplete
horizon invalidate evidence rather than invent a close. Account equity and loss
streak are updated after net costs; daily limits and STOP_DAY latch block new entries.
The profile's explicit $48,000 floor is held fixed for this research simulation;
this is not a simulation of every Topstep trailing-floor or payout rule.

Metrics: arithmetic net expectancy per completed trade, gross positive net-P&L
sum divided by absolute negative net-P&L sum (profit factor), realized equity
peak-to-trough drawdown starting at zero, positive-net win rate and sample size.
No-loss profit factor is null (with a separate flag), never an invented finite value.
Attribution groups completed trades by challenger, VWAP regime and time-of-day
at signal time; no subgroup edge claim is made.

Walk-forward uses fixed 20-session training / 10-session test windows, rolling
by ten sessions, with disjoint test windows. Training ranges are recorded but no
parameters or model selection are fitted. Each test fold starts a fresh account;
its first day is feature warmup. No position crosses folds. Partial tail windows
are excluded and counted. Fold ledgers/trades allow independent inspection.
Parameters must be frozen before evaluation; changing them requires fresh held-out
data. This harness does not optimize on the full dataset.

## Exact internal Practice gate

INSUFFICIENT_EVIDENCE if independent real-data provenance is not attested, fewer
than three full OOS folds exist, any fold has invalid data/unresolved execution,
any fold has fewer than 30 completed trades, or combined OOS sample is below 100.
The CLI deliberately never self-attests provenance; file SHA-256 identifies the
input, but does not prove provenance. The programmatic `real_data=True` flag is
an explicit external attestation, not validation performed by the harness.

With sufficient evidence, PASS requires combined net expectancy > 0, finite
profit factor >= 1.2, combined realized drawdown <= $800, positive net P&L in
every fold, and each fold's realized drawdown <= $800. Otherwise FAIL.
These are frozen internal research criteria, not proof of edge or authorization
for live execution. They do not include confidence intervals, stress-cost scenarios,
unrealized drawdown, queue position, spread, news filtering or contract-roll checks.
Practice deployment, broker/API integration, Combine purchase and live runners
are outside this PR. Synthetic tests verify mechanics only.
