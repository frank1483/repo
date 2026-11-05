"""Per-source monotonic samples; absent sources never acquire a last value."""
from dataclasses import dataclass
from enum import Enum
from .units import finite


class Truth(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


TRUE, FALSE, UNKNOWN = Truth.TRUE, Truth.FALSE, Truth.UNKNOWN
DEFAULT_TTL = {"voltage": 3.0, "fc_pct": 3.0, "current": 3.0,
               "position": 3.0, "wind": 10.0, "airspeed": 3.0,
               "link": 5.0, "satellites": 3.0, "eph": 3.0}


@dataclass(frozen=True)
class Sample:
    value: object
    sensed_t: float
    recv_t: float
    valid: bool = True


class Freshness:
    def __init__(self, ttl=None):
        self.ttl = {**DEFAULT_TTL, **(ttl or {})}
        if any(not finite(v) or v <= 0 for v in self.ttl.values()):
            raise ValueError("TTLs must be positive finite seconds")
        self.samples = {}
        self.dropped = {}

    def put(self, source, value, sensed_t, recv_t, *, valid=True):
        if source not in self.ttl:
            raise ValueError("declare source TTL before ingestion")
        if (not finite(sensed_t) or not finite(recv_t) or sensed_t > recv_t
                or not isinstance(valid, bool)):
            raise ValueError("timestamps must share a monotonic time domain")
        old = self.samples.get(source)
        if old and (sensed_t <= old.sensed_t or recv_t <= old.recv_t):
            self.dropped[source] = self.dropped.get(source, 0) + 1
            return False
        self.samples[source] = Sample(value, sensed_t, recv_t, valid)
        return True

    def get(self, source, now):
        if not finite(now):
            raise ValueError("finite monotonic now required")
        s = self.samples.get(source)
        if (s is None or not s.valid or s.value is None or now < s.recv_t
                or now - s.sensed_t > self.ttl[source]):
            return None
        return s

    def evaluate(self, required, now, predicate):
        """Gate only this predictor; required is its explicit input declaration."""
        samples = {name: self.get(name, now) for name in required}
        if any(s is None for s in samples.values()):
            return UNKNOWN
        result = predicate({name: s.value for name, s in samples.items()})
        if isinstance(result, Truth):
            return result
        if not isinstance(result, bool):
            raise ValueError("predictor must return bool or Truth")
        return TRUE if result else FALSE

    def reset(self):
        """Explicit new clock epoch; never combine pre-restart samples with new ones."""
        self.samples.clear()
