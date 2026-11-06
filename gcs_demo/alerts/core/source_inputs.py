"""Explicit source ingestion/readiness for the next legacy-engine adapter.

This module does not call PredictiveAlertEngine.update or invent a complete
Telemetry snapshot. Consumers must declare their own required source set.
All clocks are caller-provided seconds in the SAME monotonic domain.
"""
from .freshness import Freshness
from .units import finite, parse_current, check_current_range


class SourceInputs:
    def __init__(self, ttl=None):
        self.freshness = Freshness(ttl)
        self._invalid_reason = {}

    def put(self, source, value, sensed_t, recv_t, *, valid=True,
            invalid_reason="invalid"):
        """Store a validated sample; generic value validation stays with caller.

        A newer invalid sample supersedes an older valid sample. A duplicate or
        out-of-order sample never changes either the value or its validity.
        """
        if not isinstance(invalid_reason, str) or not invalid_reason:
            raise ValueError("nonempty diagnostic required")
        accepted = self.freshness.put(source, value, sensed_t, recv_t, valid=valid)
        if accepted:
            if valid and value is not None:
                self._invalid_reason.pop(source, None)
            else:
                self._invalid_reason[source] = invalid_reason
        return accepted

    def put_mavlink_current(self, raw_ca, message, airframe_limits,
                            sensed_t, recv_t):
        """10 mA -> A; ONLY -1 is missing; limits must be supplied by profile.

        Protocol/limit configuration errors raise. Missing/out-of-range samples
        are stored as invalid so an earlier current cannot masquerade as fresh.
        No inferred airframe defaults and no absolute-value/sign conversion.
        """
        amps = parse_current(raw_ca, message)
        # Validate profile limits even when the sample is missing.
        result = check_current_range(amps, airframe_limits)
        reason = "missing_current" if amps is None else "out_of_airframe_range"
        return self.put("current", amps, sensed_t, recv_t,
                        valid=result == "valid", invalid_reason=reason)

    def status(self, source, now):
        """Return diagnostic fields, retaining both timestamps/ages and value."""
        if source not in self.freshness.ttl:
            raise ValueError("required source must have an explicit TTL")
        if not finite(now):
            raise ValueError("finite monotonic now required")
        sample = self.freshness.samples.get(source)
        result = {"source": source, "status": "unknown", "reason": "missing",
                  "sensed_t": None, "recv_t": None, "sensed_age_s": None,
                  "recv_age_s": None, "ttl_s": self.freshness.ttl[source],
                  "value": None, "dropped": self.freshness.dropped.get(source, 0)}
        if sample is None:
            return result
        result.update(value=sample.value, sensed_t=sample.sensed_t,
                      recv_t=sample.recv_t, sensed_age_s=now - sample.sensed_t,
                      recv_age_s=now - sample.recv_t)
        if now < sample.recv_t:
            result["reason"] = "future_sample"
        elif not sample.valid or sample.value is None:
            result["reason"] = self._invalid_reason.get(source, "invalid")
        elif (now - sample.sensed_t > result["ttl_s"]
              or now - sample.recv_t > result["ttl_s"]):
            result["reason"] = "expired"
        else:
            result.update(status="ready", reason=None)
        return result

    def readiness(self, required, now):
        """Gate exactly one declared consumer; never impose a global all-valid.

        An empty declaration is rejected to prevent accidental always-ready
        predictors. Unknown sources are configuration errors, not inferred data.
        """
        if isinstance(required, (str, bytes)):
            raise ValueError("explicit nonempty source sequence required")
        names = tuple(required)
        if (not names or any(not isinstance(n, str) for n in names)
                or len(set(names)) != len(names)):
            raise ValueError("explicit nonempty unique source sequence required")
        rows = {name: self.status(name, now) for name in names}
        unknown = [name for name, row in rows.items() if row["status"] != "ready"]
        return {"status": "unknown" if unknown else "ready",
                "unknown_sources": unknown, "sources": rows}

    def reset(self):
        """Explicit new clock epoch; retain cumulative drop counters for audit."""
        self.freshness.reset()
        self._invalid_reason.clear()
