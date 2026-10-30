"""Atomic measured P1/P2 sample feed. No continuous return deadline or action.

P2 is a latch on explicitly replayed samples, including their endpoint limits.
It cannot certify the interval between probes, current return, or landing.
"""
from __future__ import annotations

import copy

from ..airframe_route import number
from ..energy import Wind
from ..geographic_alerts import _snapshot
from .typed_geographic import _integer, geographic_energy_alert_snapshot
from .typed_link import _identity
from .typed_return import _equal, _keys, typed_return_probe_snapshot


def _measurement(rec):
    if not isinstance(rec, dict):
        raise ValueError("measured geographic telemetry required")
    fields = ("t_s", "lat", "lon", "alt", "air_heading_deg", "battery_pct", "wind_mps", "wind_from", "mode")
    if any(k not in rec for k in fields):
        raise ValueError("missing measured telemetry field")
    tm = _snapshot({k: rec[k] for k in fields})
    for k in fields[:-1]:
        number(tm[k], k)
    number(tm["t_s"], "t_s", 0, 9007199254740991)
    number(tm["lat"], "lat", -75, 75)
    number(tm["lon"], "lon", -180, 180)
    number(tm["alt"], "alt", 0)
    number(tm["battery_pct"], "battery_pct", 0, 100)
    number(tm["wind_mps"], "wind_mps", 0)
    if tm["mode"] != "fw":
        raise ValueError("measured mode must explicitly be fw")
    return tm


def _request(request, pose):
    r = _snapshot(request)
    _keys(r, ("mission_version", "recovery_reference_id", "p1", "p2"), "mission sample request")
    _identity(r["mission_version"], "mission_version")
    _identity(r["recovery_reference_id"], "recovery_reference_id")
    _keys(r["p1"], ("current_id", "candidates"), "p1")
    _keys(r["p2"], ("target", "probes", "mode"), "p2")
    if r["p2"]["mode"] != "fw":
        raise ValueError("p2 mode must match measured fw mode")
    items = r["p1"]["candidates"]
    if not isinstance(items, list) or not 1 <= len(items) <= 16:
        raise ValueError("p1 requires 1..16 explicit alternatives")
    for c in items:
        if not isinstance(c, dict) or not _equal(c.get("entry"), pose):
            raise ValueError("every p1 entry must equal the measured pose")
        if c.get("mode") != "fw":
            raise ValueError("every p1 candidate requires explicit measured fw mode")
    current = next((c for c in items if c.get("id") == r["p1"]["current_id"]), None)
    if current is None or not isinstance(current.get("events"), list) or not current["events"]:
        raise ValueError("current_id must identify a nonempty explicit current route")
    probes = r["p2"]["probes"]
    if not isinstance(probes, list) or not 1 <= len(probes) <= 16:
        raise ValueError("p2 requires 1..16 explicit return probes")
    for p in probes:
        out = p.get("outbound_events") if isinstance(p, dict) else None
        if not isinstance(out, list) or not out or len(out) > len(current["events"]) or not _equal(out, current["events"][:len(out)]):
            raise ValueError("every P2 outbound must prefix the current P1 route")
    return r


def _empty_latch():
    return {"active": None, "severity": 5, "raise": 0, "clear": 0}


def _reduce(code, snapshot, previous, reset, raise_ticks, clear_ticks, context):
    old = _empty_latch() if reset else previous
    known, risk = snapshot["status"] == "ok", snapshot["sampled_energy_risk"]
    active, raising, clearing = old["active"], old["raise"], old["clear"]
    if not known:
        active, raising, clearing = None, 0, 0
    elif risk:
        raising, clearing = min(raising + 1, raise_ticks), 0
        active = active is True or raising >= raise_ticks
    else:
        raising, clearing = 0, min(clearing + 1, clear_ticks)
        active = active is True and clearing < clear_ticks
    # Future P2 sample deficit is not an observed present return emergency.
    severity = 5 if active is not True else (2 if code == "P1" and snapshot["nominal_end_pct"] < 0 else 4)
    value = "sampled_risk" if risk is True else ("sampled_reserve_met" if known else "unknown_samples")
    if active is True and risk is False:
        value = "sampled_risk_latched_pending_clear"
    keys = (("current_id", "nominal_end_pct", "low_pct", "high_pct", "reserve_pct") if code == "P1" else
            ("first_sampled_infeasible_id", "first_sampled_infeasible_nominal_eta_s", "last_sampled_feasible_prefix_id", "sampled_feasibility_reentry", "reserve_pct"))
    finding = {"key": "typed_mission_sample_" + code.lower(), "predictor": code,
               "active": active, "severity": severity, "title": code + " explicit energy samples",
               "value": value, "evidence": [{"id": "E_TYPED_" + code + "_SAMPLES", "text": "finite samples; no continuous deadline or landing", "value": {k: snapshot[k] for k in keys}}] if known else [],
               "candidates": [], "rule_choice": None, "lead_s": None, "executable": False}
    events = []

    def event(kind):
        e = {**finding, **context, "type": kind, "status": "ok" if known else "unknown"}
        if kind == "reset":
            e.update(active=None, severity=5, value="latch_reset", evidence=[])
        events.append(e)

    if reset:
        event("reset")
    if active is None:
        if old["active"] is not None or context["initial"] or reset:
            event("unknown")
    elif active:
        if old["active"] is not True:
            event("raise")
        elif severity < old["severity"]:
            event("update")
    elif old["active"] is True:
        event("resolve")
    elif old["active"] is None:
        event("known")
    result = {"status": "ok" if known else "unknown", "sampled_energy_risk": risk,
              "active": active, "raise_streak": raising, "clear_streak": clearing,
              "raise_ticks": raise_ticks, "clear_ticks": clear_ticks,
              "finding": finding, "snapshot": snapshot}
    return result, {"active": active, "severity": severity, "raise": raising, "clear": clearing}, events


class TypedMissionSampleFeed:
    """One measured tick, explicit common route, independent atomic P1/P2 latches.

    Version binds current_id, recovery identity and target. A changed version
    or telemetry gap resets both latches. Schema/evaluation errors commit
    nothing, including P1 when P2 rejects. Unsupported geometry is a consumed
    unknown sample and breaks only that predictor's latch, without resolve.
    Even two inactive latches mean only sampled energy risk was not raised.
    """
    def __init__(self, vehicle, raise_ticks=3, clear_ticks=10, max_gap_s=30.0):
        if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
            raise ValueError("typed mission samples require explicit FW/hybrid profile")
        self._raise_ticks = _integer(raise_ticks, "raise_ticks", 1, 10000)
        self._clear_ticks = _integer(clear_ticks, "clear_ticks", 1, 10000)
        self._max_gap_s = number(max_gap_s, "max_gap_s", 1e-6, 86400)
        self._vehicle = copy.deepcopy(vehicle)
        self._sequence, self._time = -1, -1.0
        self._request = None
        self._latches = {k: _empty_latch() for k in ("P1", "P2")}

    def tick(self, sequence, rec, request):
        _integer(sequence, "sequence", 0, 9007199254740991)
        if sequence <= self._sequence:
            raise ValueError("sequence must increase strictly")
        tm = _measurement(rec)
        if tm["t_s"] <= self._time:
            raise ValueError("t_s must increase strictly")
        pose = {k: tm[k] for k in ("lat", "lon", "alt", "air_heading_deg")}
        r = _request(request, pose)
        initial = self._request is None
        changed = not initial and r["mission_version"] != self._request["mission_version"]
        if not initial and not changed:
            if (r["p1"]["current_id"] != self._request["p1"]["current_id"] or
                    r["recovery_reference_id"] != self._request["recovery_reference_id"] or
                    not _equal(r["p2"]["target"], self._request["p2"]["target"])):
                raise ValueError("current route/recovery identity or target change requires new mission_version")
        reasons = (["mission_version_changed"] if changed else [])
        if self._time >= 0 and tm["t_s"] - self._time > self._max_gap_s:
            reasons.append("telemetry_gap")
        w = Wind(tm["wind_mps"], tm["wind_from"])
        # Evaluate BOTH before computing/committing any latch state.
        snapshots = {
            "P1": geographic_energy_alert_snapshot(self._vehicle, r["p1"]["candidates"], r["p1"]["current_id"], w, tm["battery_pct"]),
            "P2": typed_return_probe_snapshot(self._vehicle, pose, r["p2"]["target"], r["p2"]["probes"], w, tm["battery_pct"], r["p2"]["mode"]),
        }
        context = {"sequence": sequence, "t": tm["t_s"], "mission_version": r["mission_version"],
                   "recovery_reference_id": r["recovery_reference_id"], "initial": initial,
                   "continuous_boundary_known": False, "latest_return_deadline_s": None}
        results, states, events = {}, {}, []
        for code in ("P1", "P2"):
            result, state, emitted = _reduce(code, snapshots[code], self._latches[code], bool(reasons), self._raise_ticks, self._clear_ticks, context)
            results[code], states[code] = result, state
            events.extend(emitted)
        output = _snapshot({"caller_scope": "atomic_measured_P1_P2_explicit_samples_only",
                            "status": "ok" if all(x["status"] == "ok" for x in results.values()) else "unknown",
                            "sequence": sequence, "t_s": tm["t_s"], "mission_version": r["mission_version"],
                            "recovery_reference_id": r["recovery_reference_id"], "mode": tm["mode"],
                            "predictors": results, "events": events, "reset_reasons": reasons,
                            "evaluated_predictors": ["P1", "P2"], "unassessed_predictors": ["P3", "P4", "P5"],
                            "continuous_boundary_known": False, "latest_return_deadline_s": None,
                            "return_now_evaluated": False, "recovery_reference_verified": False,
                            "telemetry_freshness_verified": False, "landing_modeled": False,
                            "feasible": False, "executable": False, "candidates": [], "rule_choice": None})
        self._sequence, self._time, self._request, self._latches = sequence, tm["t_s"], r, states
        return output
