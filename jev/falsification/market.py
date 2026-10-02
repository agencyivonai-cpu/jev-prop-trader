"""Causal closed-bar features and explicitly separate research families."""
from collections import Counter, deque
from dataclasses import dataclass
from datetime import timedelta, time
from decimal import Decimal as D
from types import MappingProxyType

from ..challengers import MarketState, generate_challengers
from ..research import ET, valid_bar
from ..types import SignalCandidate


@dataclass(frozen=True)
class Hypothesis:
    name: str
    mechanism: str
    family: str = "ohlcv"
    threshold: D = D("0.75")


HYPOTHESES = (
    Hypothesis("ohlcv_trend", "pullback_continuation"),
    Hypothesis("ohlcv_orb", "opening_range_breakout"),
    Hypothesis("ohlcv_reversion", "vwap_reclaim"),
    Hypothesis("jev_vwap_reclaim", "vwap_reclaim", "order_flow"),
    Hypothesis("jev_or_breakout", "opening_range_breakout", "order_flow"),
    Hypothesis("jev_level_rejection", "prior_day_rejection", "order_flow"),
)
NEIGHBORHOOD = (D("0.65"), D("0.75"), D("0.85"))


@dataclass(frozen=True)
class Opportunity:
    candidate: SignalCandidate
    features: object
    observed_through: object
    session: str


def validate_sessions(bars):
    """No repair: preserve order, quarantine entire bad RTH sessions, report all errors."""
    sessions, errors = {}, Counter()
    previous = None
    for b in bars:
        if b.timestamp.utcoffset() is None:
            raise ValueError("Timezone required")
        local = b.timestamp.astimezone(ET)
        day = local.date().isoformat()
        if previous is not None and b.timestamp <= previous:
            errors["duplicate_or_nonmonotonic_bar"] += 1
            errors[day] += 1
        previous = b.timestamp
        if not time(9, 30) <= local.time() < time(16):
            continue
        sessions.setdefault(day, []).append(b)
        if not valid_bar(b):
            errors["invalid_ohlcv_or_tick_grid"] += 1
            errors[day] += 1
    accepted = {}
    for day, rows in sessions.items():
        if (len(rows) != 390 or rows[0].timestamp.astimezone(ET).time() != time(9, 30)
                or rows[-1].timestamp.astimezone(ET).time() != time(15, 59)
                or any(b.timestamp-a.timestamp != timedelta(minutes=1) for a, b in zip(rows, rows[1:]))):
            errors["missing_bars_or_session_boundary"] += 1
            errors[day] += 1
        if not errors[day]:
            accepted[day] = rows
    reasons = {k: v for k, v in errors.items() if not k[:4].isdigit()}
    return accepted, dict(status="PASS" if not reasons else "FAIL", errors=reasons,
                          total_sessions=len(sessions), valid_sessions=len(accepted),
                          quarantined_sessions=[d for d in sessions if d not in accepted])


class FeatureStream:
    """No future sequence available to a filter; previous-day time buckets only."""
    def __init__(self):
        self.previous = None
        self.day = None
        self.rows = []
        self.closed_days = deque(maxlen=20)
        self.pv = self.volume = D(0)
        self.closes = deque(maxlen=60)
        self.ranges = deque(maxlen=20)
        self.previous_high = self.previous_low = None
        self.tests_high = self.tests_low = 0

    def push(self, b):
        day = b.timestamp.astimezone(ET).date().isoformat()
        if day != self.day:
            if self.rows:
                self.closed_days.append(tuple(self.rows))
            self.previous = self.rows if self.rows and b.timestamp-self.rows[-1].timestamp <= timedelta(days=4) else None
            self.day, self.rows = day, []
            self.pv = self.volume = D(0)
            self.closes.clear()
            self.ranges.clear()
            self.previous_high = max(x.high for x in self.previous) if self.previous else None
            self.previous_low = min(x.low for x in self.previous) if self.previous else None
            self.tests_high = self.tests_low = 0
        prior_close = self.rows[-1].close if self.rows else b.open
        # ATR feature includes the just-closed bar only, never the entry bar.
        self.ranges.append(max(b.high-b.low, abs(b.high-prior_close), abs(b.low-prior_close)))
        self.rows.append(b)
        self.closes.append(b.close)
        self.pv += b.close * b.volume
        self.volume += b.volume
        if len(self.rows) == 15:
            self.opening_high = max(x.high for x in self.rows)
            self.opening_low = min(x.low for x in self.rows)
        past_hi, past_lo = self.tests_high, self.tests_low
        if len(self.rows) > 15:
            self.tests_high += int(b.low <= self.opening_high <= b.high)
            self.tests_low += int(b.low <= self.opening_low <= b.high)
        if len(self.rows) < 31 or not self.previous or len(self.previous) != 390:
            return None
        atr = sum(self.ranges) / len(self.ranges)
        if atr <= 0:
            return None
        index = len(self.rows)-1
        # Same-minute volume from completed prior sessions; no current-day full-session mean.
        bucket = [d[index].volume for d in self.closed_days if len(d) == 390]
        rvol = b.volume / (sum(bucket)/len(bucket)) if bucket else None
        hi, lo = self.opening_high, self.opening_low
        prev_hi, prev_lo = self.previous_high, self.previous_low
        vwap = self.pv/self.volume
        closes = list(self.closes)
        trend = (sum(closes[-15:])/15 - sum(closes[-30:-15])/15) / atr
        edge = hi if b.close >= hi else lo
        body = abs(b.close-b.open)/(b.high-b.low) if b.high>b.low else D(0)
        tests = past_hi if edge == hi else past_lo
        observed = b.timestamp+timedelta(minutes=1)
        f = dict(atr=atr, vwap=vwap, previous_close=prior_close, opening_high=hi, opening_low=lo,
                 previous_day_high=prev_hi, previous_day_low=prev_lo,
                 higher_timeframe_trend=trend, opening_range_atr=(hi-lo)/atr,
                 extension_atr=abs(b.close-edge)/atr, relative_volume_tod=rvol,
                 body_fraction=body, wick_fraction=D(1)-body, prior_level_tests=tests,
                 overnight_gap_atr=(self.rows[0].open-self.previous[-1].close)/atr,
                 prior_day_proximity_atr=min(abs(b.close-prev_hi), abs(b.close-prev_lo))/atr,
                 round_number_proximity_atr=abs(b.close-(b.close/D(100)).to_integral_value()*100)/atr,
                 volatility_regime="wide" if atr >= D(10) else "narrow",
                 time_of_day="morning" if b.timestamp.astimezone(ET).hour < 12 else "afternoon",
                 timestamp=observed, observed_through=observed)
        return MappingProxyType(f)


def candidates_for(b, features, hypothesis):
    if features is None or b.timestamp.astimezone(ET).time() >= time(15, 58):
        return ()
    f, h = features, hypothesis
    if h.family == "order_flow":
        if b.delta is None:
            return ()
        state = MarketState(f["timestamp"], b.close, f["previous_close"], f["vwap"],
                            f["opening_high"], f["opening_low"],
                            # Recover previous-day levels from distances is forbidden; explicit fields.
                            f["previous_day_high"], f["previous_day_low"], b.high, b.low,
                            f["relative_volume_tod"] if f["relative_volume_tod"] is not None else D(0),
                            b.delta, D(10))
        return tuple(c for c in generate_challengers(state) if c.model == h.name)
    direction = None
    if h.mechanism == "opening_range_breakout":
        if f["previous_close"] <= f["opening_high"] < b.close and f["extension_atr"] >= h.threshold:
            direction = "long"
        elif f["previous_close"] >= f["opening_low"] > b.close and f["extension_atr"] >= h.threshold:
            direction = "short"
    elif h.mechanism == "pullback_continuation":
        if f["higher_timeframe_trend"] >= h.threshold and f["previous_close"] <= f["vwap"] < b.close:
            direction = "long"
        elif f["higher_timeframe_trend"] <= -h.threshold and f["previous_close"] >= f["vwap"] > b.close:
            direction = "short"
    elif h.mechanism == "vwap_reclaim":
        if f["previous_close"] < f["vwap"] <= b.close and (f["vwap"]-b.low)/f["atr"] >= h.threshold:
            direction = "long"
        elif f["previous_close"] > f["vwap"] >= b.close and (b.high-f["vwap"])/f["atr"] >= h.threshold:
            direction = "short"
    else:
        raise ValueError("Unregistered hypothesis mechanism")
    if direction is None:
        return ()
    sign = D(1) if direction == "long" else D(-1)
    return (SignalCandidate(f"{h.name}:{h.threshold}:{f['timestamp'].isoformat()}:{direction}",
                            h.name, "MNQ", f["timestamp"], direction,
                            b.close, b.close-sign*10, b.close+sign*20),)


def opportunities(sessions, hypothesis):
    stream, result = FeatureStream(), []
    for day, bars in sessions.items():
        for b in bars:
            f = stream.push(b)
            for c in candidates_for(b, f, hypothesis):
                result.append(Opportunity(c, f, f["observed_through"], day))
    return tuple(result)


def feature_tape(sessions):
    stream = FeatureStream()
    return tuple((b, stream.push(b)) for bars in sessions.values() for b in bars)


def opportunities_from_tape(tape, hypothesis, days):
    result = []
    permitted = set(days)
    for b, f in tape:
        day = b.timestamp.astimezone(ET).date().isoformat()
        if day not in permitted:
            continue
        for c in candidates_for(b, f, hypothesis):
            result.append(Opportunity(c, f, f["observed_through"], day))
    return tuple(result)
