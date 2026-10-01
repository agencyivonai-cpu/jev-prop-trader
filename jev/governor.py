from threading import Lock
from .types import AccountSnapshot, SignalCandidate, Action, Proposal, RiskDecision


class Governor:
    """AI proposes a candidate ID only; gate alone determines size and permission.

    Research-only: returns an authorized plan, never invokes any executor/broker.
    One reservation at a time prevents duplicate approvals against a stale snapshot.
    """
    def __init__(self, gate):
        self.gate = gate
        self._seen = set()
        self._stopped_sessions = set()
        self._reservation = None
        self._reservation_snapshot = None
        self._lock = Lock()

    def evaluate(self, proposal, candidates, account, now):
        with self._lock:
            if (not isinstance(account, AccountSnapshot) or not account.session_id or
                    not isinstance(candidates, (list, tuple)) or
                    any(not isinstance(c, SignalCandidate) for c in candidates)):
                return RiskDecision("invalid_input")
            if not isinstance(proposal, Proposal) or not isinstance(proposal.action, Action):
                return RiskDecision("invalid_proposal")
            if proposal.action == Action.STOP_DAY:
                self._stopped_sessions.add(account.session_id)
                return RiskDecision("stop_day")
            if account.session_id in self._stopped_sessions:
                return RiskDecision("stop_day")
            if proposal.action != Action.TRADE:
                return RiskDecision(proposal.action.value.lower())
            if self._reservation is not None:
                return RiskDecision("reservation_pending")
            matches = [c for c in candidates if c.candidate_id == proposal.candidate_id]
            if len(matches) != 1:
                return RiskDecision("unknown_or_ambiguous_candidate")
            c = matches[0]
            if c.candidate_id in self._seen:
                return RiskDecision("duplicate_candidate")
            result = self.gate.authorize(c, account, now)
            if result.allowed:
                self._seen.add(c.candidate_id)
                self._reservation = result.order
                self._reservation_snapshot = account
            return result

    def acknowledge(self, candidate_id, *, reconciled_snapshot):
        """Release only with newer reconciled evidence recording the simulated entry.

        Restart persistence and real execution are explicitly outside v0.1.
        """
        with self._lock:
            if self._reservation is None or self._reservation.candidate.candidate_id != candidate_id:
                raise ValueError("Unknown reservation")
            if (reconciled_snapshot.reconciled is not True or
                    reconciled_snapshot.session_id != self._reservation_snapshot.session_id or
                    reconciled_snapshot.timestamp <= self._reservation_snapshot.timestamp or
                    reconciled_snapshot.trades_today <= self._reservation_snapshot.trades_today):
                raise ValueError("New reconciled entry evidence required")
            self._reservation = None
            self._reservation_snapshot = None
