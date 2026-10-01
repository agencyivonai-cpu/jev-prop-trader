from datetime import datetime
from decimal import Decimal
from .types import SignalCandidate


def adapt_signal(signal, *, symbol, source_timezone):
    """Read-only adapter; requires caller to state instrument and source zone.

    Derived legacy risk_ticks/rr are intentionally ignored and recomputed by gate.
    """
    ts = signal.ts.to_pydatetime() if hasattr(signal.ts, "to_pydatetime") else signal.ts
    if not isinstance(ts, datetime):
        raise ValueError("Invalid signal timestamp")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=source_timezone)
    if ts.utcoffset() is None:
        raise ValueError("Timezone required")
    return SignalCandidate(
        f"{signal.model}:{symbol}:{ts.isoformat()}:{signal.idx}:{signal.direction}",
        signal.model, symbol, ts, signal.direction,
        *(Decimal(str(value)) for value in (signal.entry, signal.stop, signal.target)))
