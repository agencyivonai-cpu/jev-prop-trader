"""Three independent experimental setups; no imported legacy alpha models.

Input features must be computed from closed bars only. These prototypes have no
validated edge and must only generate offline research candidates.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from .types import SignalCandidate


@dataclass(frozen=True)
class MarketState:
    timestamp: datetime
    close: D
    previous_close: D
    vwap: D
    opening_high: D
    opening_low: D
    previous_day_high: D
    previous_day_low: D
    high: D
    low: D
    relative_volume: D
    delta: D
    stop_distance: D


def generate_challengers(s):
    values = [getattr(s, name) for name in s.__dataclass_fields__ if name != "timestamp"]
    if (s.timestamp.utcoffset() is None or
            any(not isinstance(v, D) or not v.is_finite() for v in values) or
            s.stop_distance <= 0 or s.relative_volume < D("1.2") or
            s.opening_low >= s.opening_high or s.low > s.close or s.high < s.close):
        return []
    setups = [
        ("jev_vwap_reclaim", s.previous_close <= s.vwap < s.close,
         s.previous_close >= s.vwap > s.close),
        ("jev_or_breakout", s.previous_close <= s.opening_high < s.close,
         s.previous_close >= s.opening_low > s.close),
        ("jev_level_rejection", s.low < s.previous_day_low < s.close,
         s.high > s.previous_day_high > s.close),
    ]
    result = []
    for name, long_setup, short_setup in setups:
        direction = "long" if long_setup and s.delta > 0 else (
            "short" if short_setup and s.delta < 0 else None)
        if direction is None:
            continue
        sign = 1 if direction == "long" else -1
        result.append(SignalCandidate(
            f"{name}:{s.timestamp.isoformat()}:{direction}", name, "MNQ", s.timestamp,
            direction, s.close, s.close - sign * s.stop_distance,
            s.close + sign * 2 * s.stop_distance))
    return result
