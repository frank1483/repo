"""Transactional P1/P2/P3 composition; P4/P5 remain explicitly unassessed.

No capacity correction, candidate generation, continuous deadline or action.
"""
from __future__ import annotations

import copy

from ..geographic_alerts import _snapshot
from .typed_capacity_feed import TypedCapacityFeed
from .typed_link import _identity
from .typed_mission_feed import TypedMissionSampleFeed
from .typed_return import _keys


class TypedMissionOrchestrator:
    """One caller tick, common measured time/SOC, all-or-nothing feed commit.

    Mission changes reset P1/P2 only. A battery session change must also carry
    a new mission_version, so old P1/P2 streaks cannot cross battery sessions.
    P3 follows its own session/gap rules and remains a conditional hypothesis.
    Unsupported geometry and capacity warmup consume an unknown sample; they
    are not malformed input, recovery, or permission to act.
    """
    def __init__(self, vehicle, capacity_options, raise_ticks=3, clear_ticks=10,
                 max_gap_s=30.0, max_samples=601):
        self._mission = TypedMissionSampleFeed(vehicle, raise_ticks, clear_ticks, max_gap_s)
        self._capacity = TypedCapacityFeed(vehicle, capacity_options, raise_ticks, clear_ticks, max_samples)
        self._session = self._version = None

    def tick(self, sequence, measurement, request):
        m, r = _snapshot(measurement), _snapshot(request)
        _keys(m, ("mission", "capacity"), "orchestrator measurement")
        _keys(r, ("mission", "capacity_session_id"), "orchestrator request")
        _identity(r["capacity_session_id"], "capacity_session_id")
        if not isinstance(m["mission"], dict) or not isinstance(m["capacity"], dict):
            raise ValueError("both measured mission and capacity objects required")
        if not isinstance(r["mission"], dict):
            raise ValueError("mission request object required")
        for key in ("t_s", "battery_pct"):
            if key not in m["mission"] or key not in m["capacity"] or m["mission"][key] != m["capacity"][key]:
                raise ValueError("mission and capacity require identical measured " + key)
        session = r["capacity_session_id"]
        version = r["mission"].get("mission_version")
        if self._session is not None and session != self._session and version == self._version:
            raise ValueError("battery session change requires new mission_version")
        # The existing feeds mutate only these private copies. If capacity or
        # final serialization rejects, even a successful P1/P2 tick is discarded.
        mission, capacity = copy.deepcopy(self._mission), copy.deepcopy(self._capacity)
        a = mission.tick(sequence, m["mission"], r["mission"])
        b = capacity.tick(sequence, m["capacity"], session)
        predictors = {"P1": a["predictors"]["P1"], "P2": a["predictors"]["P2"], "P3": b}
        events = [{**e, "mission_version": a["mission_version"],
                   "recovery_reference_id": a["recovery_reference_id"],
                   "session_id": session, "battery_id": b["battery_id"]}
                  for e in a["events"] + b["events"]]
        output = _snapshot({
            "caller_scope": "atomic_measured_P1_P2_P3_only",
            "status": "ok" if all(p["status"] == "ok" for p in predictors.values()) else "unknown",
            "sequence": a["sequence"], "t_s": a["t_s"], "mission_version": a["mission_version"],
            "recovery_reference_id": a["recovery_reference_id"], "session_id": session,
            "battery_id": b["battery_id"], "mode": a["mode"],
            "predictors": predictors, "events": events,
            "reset_reasons_by_predictor": {"P1": a["reset_reasons"], "P2": a["reset_reasons"], "P3": b["reset_reasons"]},
            "evaluated_predictors": ["P1", "P2", "P3"], "unassessed_predictors": ["P4", "P5"],
            "continuous_boundary_known": False, "latest_return_deadline_s": None,
            "return_now_evaluated": False, "recovery_reference_verified": False,
            "telemetry_freshness_verified": False, "measured_capacity": False,
            "sensor_validated": False, "independent_window_evidence": False,
            "energy_correction_applied": False, "landing_modeled": False,
            "feasible": False, "executable": False, "candidates": [], "rule_choice": None})
        self._mission, self._capacity = mission, capacity
        self._session, self._version = session, a["mission_version"]
        return output
