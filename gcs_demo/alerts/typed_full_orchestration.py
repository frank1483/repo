"""Atomic measured P1-P5 composition; no route, candidate or action generation.

This opt-in Python caller leaves the established P1/P2/P3 caller unchanged.
JS parity and UI/report integration are separate pending batches.
"""
from __future__ import annotations

import copy

from ..geographic_alerts import _snapshot
from .typed_link import TypedLinkDistancePredictor, _identity
from .typed_orchestration import TypedMissionOrchestrator
from .typed_return import _keys
from .typed_wind import TypedWindTrendPredictor


class TypedFullMissionOrchestrator:
    """One atomic tick across independently bounded measured predictors.

    All four measurement objects require the same caller-measured time. Wind
    speed in P5 must equal the P1/P2 mission sample; neither is inferred.
    The P4 horizontal distance reference is fixed for this instance and must
    be explicitly supplied on every request. Changing it needs a new caller.
    Unknown/unsupported forward probes are valid samples, never clearance.
    """

    def __init__(self, vehicle, capacity_options, link_reference_id,
                 link_options=None, wind_options=None, raise_ticks=3,
                 clear_ticks=10, max_gap_s=30.0, max_samples=601):
        self._reference = _identity(link_reference_id, "link_reference_id")
        self._mission = TypedMissionOrchestrator(
            vehicle, capacity_options, raise_ticks, clear_ticks,
            max_gap_s, max_samples)
        self._link = TypedLinkDistancePredictor(
            vehicle, self._reference, link_options, raise_ticks, clear_ticks)
        self._wind = TypedWindTrendPredictor(
            vehicle, wind_options, raise_ticks, clear_ticks)

    def tick(self, sequence, measurement, request):
        m, r = _snapshot(measurement), _snapshot(request)
        _keys(m, ("mission", "capacity", "link", "wind"), "full measurement")
        _keys(r, ("mission", "capacity_session_id", "link"), "full request")
        if not all(isinstance(m[k], dict) for k in m):
            raise ValueError("all full measurement members must be objects")
        if not isinstance(r["mission"], dict) or not isinstance(r["link"], dict):
            raise ValueError("mission and link request objects required")
        _keys(r["link"], ("reference_id", "probes"), "full link request")
        if _identity(r["link"]["reference_id"], "reference_id") != self._reference:
            raise ValueError("link reference change requires a new caller")
        times = [m[k].get("t_s") for k in ("mission", "capacity", "link", "wind")]
        if any("t_s" not in m[k] for k in m) or any(t != times[0] for t in times[1:]):
            raise ValueError("all predictors require identical measured t_s")
        if ("wind_mps" not in m["mission"] or "wind_mps" not in m["wind"]
                or m["mission"]["wind_mps"] != m["wind"]["wind_mps"]):
            raise ValueError("mission and P5 require identical measured wind_mps")

        # No original child commits until ALL ticks and final JSON snapshot pass.
        mission, link, wind = copy.deepcopy((self._mission, self._link, self._wind))
        a = mission.tick(sequence, {k: m[k] for k in ("mission", "capacity")},
                         {k: r[k] for k in ("mission", "capacity_session_id")})
        version = a["mission_version"]
        p4 = link.tick(sequence, m["link"], r["link"]["probes"], version)
        p5 = wind.tick(sequence, m["wind"], version)
        predictors = {**a["predictors"], "P4": p4, "P5": p5}
        events = list(a["events"])
        for name, result in (("P4", p4), ("P5", p5)):
            for event in result["events"]:
                events.append({**event, "predictor_id": name,
                               "mission_version": version,
                               "recovery_reference_id": a["recovery_reference_id"],
                               "session_id": a["session_id"], "battery_id": a["battery_id"],
                               **({"reference_id": self._reference} if name == "P4" else {})})
        resets = dict(a["reset_reasons_by_predictor"])
        for name, result in (("P4", p4), ("P5", p5)):
            resets[name] = [result["reset_reason"]] if result["reset_reason"] else []
        output = _snapshot({
            **a, "caller_scope": "atomic_measured_P1_P2_P3_P4_P5_only",
            "status": "ok" if all(p["status"] == "ok" for p in predictors.values()) else "unknown",
            "link_reference_id": self._reference, "predictors": predictors, "events": events,
            "reset_reasons_by_predictor": resets,
            "evaluated_predictors": ["P1", "P2", "P3", "P4", "P5"],
            "unassessed_predictors": [],
            # P1-P5 evaluation does not establish physical/action feasibility.
            "continuous_boundary_known": False, "latest_return_deadline_s": None,
            "return_now_evaluated": False, "recovery_reference_verified": False,
            "telemetry_freshness_verified": False, "measured_capacity": False,
            "sensor_validated": False, "independent_window_evidence": False,
            "energy_correction_applied": False, "landing_modeled": False,
            "feasible": False, "executable": False, "candidates": [], "rule_choice": None})
        self._mission, self._link, self._wind = mission, link, wind
        return output
