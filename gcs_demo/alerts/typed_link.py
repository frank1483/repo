"""Independent P4 distance/link fit on measured, caller-referenced distances.

No geographic conversion, route/ETA inference, RTL suggestion or action.
"""
from __future__ import annotations

import copy
import re

from ..airframe_route import number
from ..geographic_alerts import _snapshot
from .typed_geographic import _integer


def _identity(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise ValueError(name + " requires 1..128 ASCII identity characters")
    return value


def _profile(vehicle):
    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("typed link requires an explicit FW/hybrid profile")


def _options(options):
    defaults = {"window_s": 180.0, "min_samples": 60, "min_distance_span_m": 300.0,
                "max_gap_s": 30.0, "horizon_s": 300.0, "min_r2": 0.5,
                "link_min_pct": 35.0, "max_extrapolation_m": 0.0}
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - set(defaults):
        raise ValueError("unsupported typed link options")
    cfg = {**defaults, **options}
    _integer(cfg["min_samples"], "min_samples", 2, 601)
    number(cfg["window_s"], "window_s", 1e-6, 86400)
    number(cfg["max_gap_s"], "max_gap_s", 1e-6, cfg["window_s"])
    number(cfg["min_distance_span_m"], "min_distance_span_m", 1e-6, 10000)
    number(cfg["horizon_s"], "horizon_s", 0, 86400)
    number(cfg["min_r2"], "min_r2", 0, 1)
    number(cfg["link_min_pct"], "link_min_pct", 0, 100)
    number(cfg["max_extrapolation_m"], "max_extrapolation_m", 0, 10000)
    return cfg


def _measurement(rec):
    if not isinstance(rec, dict) or not {"t_s", "distance_m", "link_pct"} <= set(rec):
        raise ValueError("measured t_s, distance_m and link_pct required")
    return {"t_s": number(rec["t_s"], "t_s", 0, 9007199254740991),
            "distance_m": number(rec["distance_m"], "distance_m", 0, 10000),
            "link_pct": number(rec["link_pct"], "link_pct", 0, 100)}


def _history(samples, cfg):
    if not isinstance(samples, list) or not 1 <= len(samples) <= 601:
        raise ValueError("typed link requires 1..601 measured samples")
    pts = [_measurement(r) for r in samples]
    if any(b["t_s"] <= a["t_s"] for a, b in zip(pts, pts[1:])):
        raise ValueError("measured time must increase strictly")
    pts = [p for p in pts if p["t_s"] >= pts[-1]["t_s"] - cfg["window_s"]]
    cut = 0
    for i in range(1, len(pts)):
        if pts[i]["t_s"] - pts[i - 1]["t_s"] > cfg["max_gap_s"]:
            cut = i
    return pts[cut:]


def _probes(probes):
    items = _snapshot(probes)
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ValueError("typed link requires 1..1000 explicit probes")
    seen, previous_eta = set(), -1.0
    for p in items:
        if not isinstance(p, dict) or set(p) != {"id", "distance_m", "eta_s"}:
            raise ValueError("probe requires exactly id, distance_m and eta_s")
        key = _identity(p["id"], "probe id")
        if key in seen:
            raise ValueError("probe id must be unique")
        seen.add(key)
        number(p["distance_m"], "probe distance_m", 0, 10000)
        eta = number(p["eta_s"], "probe eta_s", 0, 86400)
        if eta <= previous_eta:
            raise ValueError("probe eta_s must increase strictly")
        previous_eta = eta
    return items


def typed_link_distance_snapshot(vehicle, reference_id, samples, probes, options=None):
    """Conditional distance regression at explicit probes, never route clearance.

    All distances must use the same caller-owned horizontal reference and
    measurement definition. The caller versions mission/reference changes.
    Zero extrapolation is the default; ANY unsupported probe makes the forward
    result unknown. Current measured quality at/below limit is known immediately.
    A positive fit is unknown; a constant fit is allowed only with distance span.
    No automatic return, failsafe verification or confidence interval is implied.
    """
    _profile(vehicle)
    _identity(reference_id, "reference_id")
    cfg = _options(options)
    pts, targets = _history(samples, cfg), _probes(probes)
    latest = pts[-1]
    lo, hi = min(p["distance_m"] for p in pts), max(p["distance_m"] for p in pts)
    result = {"scope": "typed_P4_caller_referenced_distance_probes_only",
              "reference_id": reference_id, "status": "unknown", "risk": None,
              "reason": "insufficient_samples", "t_s": latest["t_s"],
              "current_link_pct": latest["link_pct"], "link_min_pct": cfg["link_min_pct"],
              "sample_count": len(pts), "distance_min_m": lo, "distance_max_m": hi,
              "distance_span_m": hi - lo, "slope_pct_per_m": None, "r2": None,
              "first_probe_id": None, "lead_s": None, "probes": [],
              "distance_reference_verified": False, "eta_verified": False,
              "geometry_evaluated": False, "landing_modeled": False,
              "probability_interval": False, "sensor_validated": False,
              "feasible": False, "executable": False}
    if latest["link_pct"] <= cfg["link_min_pct"]:
        result.update(status="ok", risk=True, reason="observed_limit_reached", lead_s=0.0)
        return _snapshot(result)
    if len(pts) < cfg["min_samples"]:
        return _snapshot(result)
    if hi - lo < cfg["min_distance_span_m"]:
        result["reason"] = "insufficient_distance_span"
        return _snapshot(result)
    xs = [p["distance_m"] - latest["distance_m"] for p in pts]
    ys = [p["link_pct"] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = number(sxy / sxx, "link slope")
    fitted = number(my - slope * mx, "fitted current link")
    r2 = 1.0 if syy == 0 else max(0.0, min(1.0, sxy * sxy / (sxx * syy)))
    result.update(slope_pct_per_m=slope, r2=r2)
    if r2 < cfg["min_r2"] or slope > 0:
        result["reason"] = "distance_fit_unreliable" if r2 < cfg["min_r2"] else "distance_fit_increasing"
        return _snapshot(result)
    for p in targets:
        row = {**p, "status": "ok", "predicted_link_pct": None, "risk": None}
        if p["eta_s"] > cfg["horizon_s"]:
            row.update(status="unsupported", reason="beyond_horizon")
        elif not lo - cfg["max_extrapolation_m"] <= p["distance_m"] <= hi + cfg["max_extrapolation_m"]:
            row.update(status="unsupported", reason="outside_distance_envelope")
        else:
            quality = number(fitted + slope * (p["distance_m"] - latest["distance_m"]), "predicted link")
            row.update(predicted_link_pct=quality, risk=quality <= cfg["link_min_pct"])
        result["probes"].append(row)
    if any(p["status"] != "ok" for p in result["probes"]):
        result["reason"] = "one_or_more_probes_unsupported"
    else:
        first = next((p for p in result["probes"] if p["risk"]), None)
        result.update(status="ok", risk=first is not None,
                      reason="probe_limit_reached" if first else "probes_above_limit",
                      first_probe_id=first["id"] if first else None,
                      lead_s=first["eta_s"] if first else None)
    return _snapshot(result)


class TypedLinkDistancePredictor:
    """Independent bounded P4 latch, not yet the unified P1–P5 caller.

    Reference identity is fixed per instance. Mission changes or telemetry gaps
    reset history/latch. Invalid input consumes no state; unknown breaks streaks.
    """
    def __init__(self, vehicle, reference_id, options=None, raise_ticks=3, clear_ticks=10):
        _profile(vehicle)
        self._reference = _identity(reference_id, "reference_id")
        self._vehicle = copy.deepcopy(vehicle)
        self._options = _options(options)
        self._raise_ticks = _integer(raise_ticks, "raise_ticks", 1, 10000)
        self._clear_ticks = _integer(clear_ticks, "clear_ticks", 1, 10000)
        self._sequence, self._time, self._version = -1, -1.0, None
        self._history = []
        self._active = self._severity = None
        self._raise = self._clear = 0

    def tick(self, sequence, rec, probes, mission_version):
        _integer(sequence, "sequence", 0, 9007199254740991)
        if sequence <= self._sequence:
            raise ValueError("sequence must increase strictly")
        _identity(mission_version, "mission_version")
        tm = _measurement(rec)
        if tm["t_s"] <= self._time:
            raise ValueError("t_s must increase strictly")
        changed = self._version is not None and mission_version != self._version
        gap = self._time >= 0 and tm["t_s"] - self._time > self._options["max_gap_s"]
        reset = changed or gap
        history = _history((([] if reset else self._history) + [tm])[-601:], self._options)
        result = typed_link_distance_snapshot(self._vehicle, self._reference, history, probes, self._options)
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
        severity = 2 if active and tm["link_pct"] <= result["link_min_pct"] else (4 if active else 5)
        finding = {"key": "typed_link_distance", "active": active, "severity": severity,
                   "title": "Measured link quality by distance", "value": result["reason"],
                   "evidence": [{"id": "E_TYPED_P4", "text": "conditional explicit-distance probe fit",
                                 "value": {k: result[k] for k in ("reference_id", "current_link_pct", "link_min_pct", "slope_pct_per_m", "r2", "first_probe_id", "lead_s")}}],
                   "candidates": [], "rule_choice": None, "lead_s": result["lead_s"]}
        events = []

        def event(kind):
            events.append({**finding, "type": kind, "t": tm["t_s"], "status": result["status"],
                           "sequence": sequence, "mission_version": mission_version, "executable": False})
            if kind == "reset":
                events[-1].update(active=None, severity=5, value="history and latch reset", evidence=[], lead_s=None)

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
