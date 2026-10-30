"""Independent measured P5 speed trend; no legacy engine, route or action."""
from __future__ import annotations

import copy
import re

from ..airframe_route import number
from ..geographic_alerts import _snapshot
from .typed_geographic import _integer


def _options(options):
    defaults = {"window_s": 180.0, "min_samples": 60, "min_span_s": 30.0,
                "max_gap_s": 30.0, "horizon_s": 300.0,
                "min_slope_mps2": 0.002, "min_r2": 0.6}
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - set(defaults):
        raise ValueError("unsupported typed wind options")
    out = {**defaults, **options}
    _integer(out["min_samples"], "min_samples", 2, 601)
    number(out["window_s"], "window_s", 1e-6, 86400)
    number(out["min_span_s"], "min_span_s", 1e-6, out["window_s"])
    number(out["max_gap_s"], "max_gap_s", 1e-6, out["window_s"])
    number(out["horizon_s"], "horizon_s", 0, 86400)
    number(out["min_slope_mps2"], "min_slope_mps2", 0, 1000)
    number(out["min_r2"], "min_r2", 0, 1)
    return out


def _limit(vehicle):
    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("typed wind requires an explicit FW/hybrid profile")
    return number(vehicle.airframe_profile["limits"]["wind_limit_mps"], "wind_limit_mps", 0)


def _measurement(rec):
    if not isinstance(rec, dict) or not {"t_s", "wind_mps"} <= set(rec):
        raise ValueError("measured t_s and wind_mps required")
    return {"t_s": number(rec["t_s"], "t_s", 0, 9007199254740991),
            "wind_mps": number(rec["wind_mps"], "wind_mps", 0)}


def _history(samples, cfg):
    if not isinstance(samples, list) or not 1 <= len(samples) <= 601:
        raise ValueError("typed wind requires 1..601 measured samples")
    points = [_measurement(rec) for rec in samples]
    if any(b["t_s"] <= a["t_s"] for a, b in zip(points, points[1:])):
        raise ValueError("measured time must increase strictly")
    points = [p for p in points if p["t_s"] >= points[-1]["t_s"] - cfg["window_s"]]
    cut = 0
    for i in range(1, len(points)):
        if points[i]["t_s"] - points[i - 1]["t_s"] > cfg["max_gap_s"]:
            cut = i
    return points[cut:]


def typed_wind_trend_snapshot(vehicle, samples, options=None):
    """Finite-window OLS speed forecast conditional on the observed trend.

    At/above the configured limit is known immediately. Otherwise warmup or
    poor fit is UNKNOWN, not a clear result. A qualified rising fit predicts
    the first limit crossing only within the configured horizon. Constant or
    qualified non-rising fit is known below limit. No direction, probability,
    landing/route feasibility, sensor validation or execution is implied.
    """
    cfg, limit = _options(options), _limit(vehicle)
    points = _history(samples, cfg)
    latest = points[-1]
    span = latest["t_s"] - points[0]["t_s"]
    result = {"scope": "typed_P5_measured_speed_trend_only", "status": "unknown",
              "reason": "insufficient_samples", "risk": None,
              "limit_mps": limit, "current_wind_mps": latest["wind_mps"],
              "sample_count": len(points), "span_s": span, "t_s": latest["t_s"],
              "trend_mps_per_s": None, "fitted_now_mps": None, "r2": None,
              "lead_s": None, "horizon_s": cfg["horizon_s"],
              "direction_predicted": False, "probability_interval": False,
              "sensor_validated": False, "feasible": False, "executable": False}
    if latest["wind_mps"] >= limit:
        result.update(status="ok", reason="observed_limit_reached", risk=True, lead_s=0.0)
        return _snapshot(result)
    if len(points) < cfg["min_samples"]:
        return _snapshot(result)
    if span < cfg["min_span_s"]:
        result["reason"] = "insufficient_span"
        return _snapshot(result)
    xs = [p["t_s"] - latest["t_s"] for p in points]
    ys = [p["wind_mps"] for p in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = number(sxy / sxx, "trend slope")
    fitted = number(my - slope * mx, "fitted wind")
    r2 = 1.0 if syy == 0 else max(0.0, min(1.0, sxy * sxy / (sxx * syy)))
    result.update(trend_mps_per_s=slope, fitted_now_mps=fitted, r2=r2)
    if syy == 0:
        result.update(status="ok", reason="constant_wind", risk=False)
    elif r2 < cfg["min_r2"]:
        result["reason"] = "trend_fit_unreliable"
    elif slope <= cfg["min_slope_mps2"]:
        result.update(status="ok", reason="trend_not_rising", risk=False)
    else:
        lead = number(max(0.0, (limit - fitted) / slope), "lead_s", 0)
        risk = lead <= cfg["horizon_s"]
        result.update(status="ok", reason="crossing_within_horizon" if risk else "crossing_beyond_horizon",
                      risk=risk, lead_s=lead)
    return _snapshot(result)


class TypedWindTrendPredictor:
    """Independent P5 latch with explicit version and at most 601 samples.

    Version change or telemetry gap resets history and latch. Schema errors
    consume no state. Unknown consumes the valid sample and breaks streaks;
    recovery emits known, never a fabricated resolve for unknown telemetry.
    This is not wired into the P1-only geographic feed in this batch.
    """
    def __init__(self, vehicle, options=None, raise_ticks=3, clear_ticks=10):
        _limit(vehicle)
        self._vehicle = copy.deepcopy(vehicle)
        self._options = _options(options)
        self._raise_ticks = _integer(raise_ticks, "raise_ticks", 1, 10000)
        self._clear_ticks = _integer(clear_ticks, "clear_ticks", 1, 10000)
        self._sequence, self._time, self._version = -1, -1.0, None
        self._history = []
        self._active = self._severity = None
        self._raise = self._clear = 0

    def tick(self, sequence, rec, mission_version):
        _integer(sequence, "sequence", 0, 9007199254740991)
        if sequence <= self._sequence:
            raise ValueError("sequence must increase strictly")
        if not isinstance(mission_version, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", mission_version):
            raise ValueError("mission_version requires 1..128 ASCII version characters")
        tm = _measurement(rec)
        if tm["t_s"] <= self._time:
            raise ValueError("t_s must increase strictly")
        changed = self._version is not None and mission_version != self._version
        gap = self._time >= 0 and tm["t_s"] - self._time > self._options["max_gap_s"]
        reset = changed or gap
        history = ([] if reset else self._history) + [tm]
        history = _history(history[-601:], self._options)
        result = typed_wind_trend_snapshot(self._vehicle, history, self._options)
        previous = None if reset else self._active
        active = False if reset or self._active is None else self._active
        raising, clearing = (0, 0) if reset else (self._raise, self._clear)
        if result["status"] != "ok":
            active, raising, clearing = None, 0, 0
        elif result["risk"]:
            raising, clearing = min(raising + 1, self._raise_ticks), 0
            active = active or raising >= self._raise_ticks
        else:
            raising, clearing = 0, min(clearing + 1, self._clear_ticks)
            if clearing >= self._clear_ticks:
                active = False
        severity = 2 if active and tm["wind_mps"] >= result["limit_mps"] else (4 if active else 5)
        finding = {"key": "typed_wind_trend", "active": active, "severity": severity,
                   "title": "Measured wind speed trend", "value": result["reason"],
                   "evidence": [{"id": "E_TYPED_P5", "text": "conditional finite-window speed trend",
                                 "value": {k: result[k] for k in ("current_wind_mps", "limit_mps", "trend_mps_per_s", "r2", "lead_s")}}],
                   "candidates": [], "rule_choice": None, "lead_s": result["lead_s"]}
        events = []

        def event(kind):
            events.append({**finding, "type": kind, "t": tm["t_s"], "status": result["status"],
                           "sequence": sequence, "mission_version": mission_version, "executable": False})
            if kind == "reset":
                events[-1].update(active=None, severity=5, value="history and latch reset",
                                  evidence=[], lead_s=None)

        if reset:
            event("reset")
        if active is None:
            if previous is not None or self._version is None or reset:
                event("unknown")
        elif active:
            if previous is not True:
                event("raise")
            elif severity < self._severity:
                event("update")
        elif previous is True:
            event("resolve")
        elif previous is None:
            event("known")
        result.update(sequence=sequence, mission_version=mission_version, active=active,
                      raise_streak=raising, clear_streak=clearing, finding=finding, events=events,
                      reset_reason="mission_version_changed" if changed else ("telemetry_gap" if gap else None))
        detached = _snapshot(result)
        self._sequence, self._time, self._version = sequence, tm["t_s"], mission_version
        self._history, self._active, self._severity = history, active, severity
        self._raise, self._clear = raising, clearing
        return detached
