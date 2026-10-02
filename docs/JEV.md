# JEV Prop Trader v0.1 — offline research only

AI proposes → deterministic risk code authorizes → executor executes.

This PR implements the first two stages and returns immutable authorized plans.
It does **not** connect JEV to `LiveExecutor`, Topstep, IB, or a real account.
No AI API, credentials, account purchase, or trading activation is required.

## Architecture review

The inherited repository has mutable `strategy.models.base.Signal`, twelve
models assembled by `MultiModelGenerator`, and shared `Config` defaults aimed
at a 100K account. `LiveExecutor` performs sizing and calls broker adapters;
`AdaptiveGuard`, `PostTradeAnalyzer`, and `PnLReconciler` provide additional
controls. Existing runners can place real orders and are not JEV runners.

The new `jev/` package is independent of those runners. Its read-only adapter
converts legacy signals to immutable `SignalCandidate` objects with explicit
instrument and source timezone. Risk is recomputed from actual price geometry,
not legacy `risk_ticks`, `rr`, or AI-supplied sizing.

The earlier full audit was not present in the supplied conversation or files;
this implementation follows the requested component scope and the retrieved
design context. Three independent challengers are VWAP reclaim, opening-range
breakout, and previous-day-level rejection. They consume explicit closed-bar
features and remain unvalidated research hypotheses. Legacy models need an
explicit registry entry before the gate accepts them; no implicit risk exists.

## Topstep 50K research profile

Reference Combine parameters: $50,000 initial balance, $3,000 target, $2,000
maximum loss limit, 5 minis / 50 micros. Sources checked 2026-10-01:

- https://help.topstep.com/en/articles/8284197-trading-combine-parameters
- https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit
- https://help.topstep.com/en/articles/13613539-risk-adjustments-high-risk-high-volatility

The research profile only allows MNQ, at most 3 contracts, $60 risk including a
$3 per-contract cost/slippage reserve, $200 daily loss, $800 internal drawdown,
3 entries/day and a stop after 2 consecutive losses. These are internal research
limits, not claims about mandatory Topstep daily loss rules. The firm's MLL is
EOD trailing and intraday enforced; the gate requires a supplied reconciled
floor rather than inferring it from intraday peaks. The internal high-water
limit can be stricter. Unknown or stale account evidence denies authorization.

This profile does not certify challenge passage, consistency, payout eligibility,
XFA scaling or time/news compliance. No transition to Combine/XFA is implemented.

## Offline usage

```python
from jev.governor import Governor
from jev.registry import challenger_registry
from jev.risk import RiskGate
from jev.types import Action, Proposal

governor = Governor(RiskGate(challenger_registry()))
# candidates: generate_challengers(closed_bar_state)
# snapshot: explicit, fresh, reconciled AccountSnapshot
# proposal: untrusted AI choice, limited to action + candidate ID
decision = governor.evaluate(
    Proposal(Action.TRADE, candidates[0].candidate_id), candidates, snapshot, now)
# decision.order is a research plan only; no broker is called.
```

WAIT/SKIP never authorize. STOP_DAY latches for a session. Successful approval
reserves the candidate and blocks further plans until a newer reconciled entry
snapshot acknowledges it; IDs cannot be replayed. This reservation is in-memory
and requires retaining one Governor instance. Durable restart recovery, session
calendars, order/fill reconciliation, actual slippage, historical feature
generation and Practice promotion gates are required before future execution
integration. A cost reserve is not a guarantee of maximum realized loss.

The only inherited executor change rejects missing/non-finite/nonpositive model
risk at entry instead of silently allocating $400. Existing registered-model
behavior remains covered by the regression suite.

## Tests

Run `python -m pytest tests`. Tests mock broker operations and do not start any
runner. New cases cover malformed input, geometry, sizing, account limits,
stale timestamps, unknown models, proposal restrictions, replay/reservation,
STOP_DAY, the adapter, all three challengers and the inherited fallback block.
