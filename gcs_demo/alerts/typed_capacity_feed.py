"""Bounded P3 caller. Conditional hypotheses only, no P1/P2 energy mutation.

One explicitly identified battery session and one ordered sample per tick.
Debounce counts overlapping windows, not independent statistical evidence.
"""
from __future__ import annotations

import copy

from ..airframe_route import number
from ..geographic_alerts import _snapshot
from .typed_capacity import typed_battery_capacity_snapshot
from .typed_geographic import _integer
from .typed_link import _identity


def _empty():
    return {"active": None, "raise": 0, "clear": 0}


class TypedCapacityFeed:
    """Atomic P3-only feed, independent of the P1/P2 mission caller.

    Explicit session change or a gap discards the old window and latch.
    Identity/cell/counter changes within a session reject without committing.
    Sequence and t_s increase globally, even across sessions. A clock restart
    requires a new feed. Configuration/vehicle are frozen copies per feed.
    """
    def __init__(self, vehicle, options, raise_ticks=3, clear_ticks=10, max_samples=601):
        if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
            raise ValueError("typed capacity feed requires explicit FW/hybrid profile")
        number(vehicle.battery_wh, "battery_wh", 1e-6, 1e9)
        defaults = {"min_samples": 90, "min_energy_span_fraction": 0.08,
                    "min_r2": 0.8, "max_gap_s": 30.0,
                    "min_fall_v_per_wh": 1e-6, "capacity_ratio_limit": 0.9,
                    "soc_gap_limit_pct": 3.0}
        if not isinstance(options, dict) or not {"cell_r_ohm", "cell_empty_v"} <= set(options) or set(options) - set(defaults) - {"cell_r_ohm", "cell_empty_v"}:
            raise ValueError("explicit chemistry options required; unsupported option")
        cfg = _snapshot({**defaults, **options})
        _integer(cfg["min_samples"], "min_samples", 3, 601)
        for key, low, high in (("cell_r_ohm", 0, 1), ("cell_empty_v", 0.1, 10),
                               ("min_energy_span_fraction", 1e-6, 1), ("min_r2", 0, 1),
                               ("max_gap_s", 1e-6, 86400), ("min_fall_v_per_wh", 1e-12, 10),
                               ("capacity_ratio_limit", 1e-6, 1), ("soc_gap_limit_pct", 0, 100)):
            number(cfg[key], key, low, high)
        self._raise_ticks = _integer(raise_ticks, "raise_ticks", 1, 10000)
        self._clear_ticks = _integer(clear_ticks, "clear_ticks", 1, 10000)
        self._max_samples = _integer(max_samples, "max_samples", cfg["min_samples"], 601)
        self._vehicle, self._options = copy.deepcopy(vehicle), cfg
        self._sequence, self._time, self._session = -1, -1.0, None
        self._rows, self._latch = [], _empty()

    def tick(self, sequence, rec, session_id):
        _integer(sequence, "sequence", 0, 9007199254740991)
        if sequence <= self._sequence:
            raise ValueError("sequence must increase strictly")
        _identity(session_id, "session_id")
        row = _snapshot(rec)
        # Validate this sample before comparing fields or touching any state.
        typed_battery_capacity_snapshot(self._vehicle, [row], self._options)
        if row["t_s"] <= self._time:
            raise ValueError("t_s must increase strictly across sessions")
        initial = self._session is None
        changed = not initial and session_id != self._session
        if self._rows and not changed:
            last = self._rows[-1]
            if (row["battery_id"] != last["battery_id"] or row["cell_count"] != last["cell_count"] or
                    row["used_wh"] < last["used_wh"]):
                raise ValueError("battery/cell/counter change requires new session_id")
        reasons = ["session_changed"] if changed else []
        if self._time >= 0 and row["t_s"] - self._time > self._options["max_gap_s"]:
            reasons.append("telemetry_gap")
        rows = (([] if reasons else self._rows) + [row])[-self._max_samples:]
        snapshot = typed_battery_capacity_snapshot(self._vehicle, rows, self._options)
        old = _empty() if reasons else self._latch
        active, raising, clearing = old["active"], old["raise"], old["clear"]
        known, risk = snapshot["status"] == "ok", snapshot["risk"]
        if not known:
            active, raising, clearing = None, 0, 0
        elif risk:
            raising, clearing = min(raising + 1, self._raise_ticks), 0
            active = active is True or raising >= self._raise_ticks
        else:
            raising, clearing = 0, min(clearing + 1, self._clear_ticks)
            active = active is True and clearing < self._clear_ticks
        value = snapshot["reason"]
        if active is True and risk is False:
            value = "conditional_capacity_risk_latched_pending_clear"
        evidence_keys = ("sample_count", "energy_span_wh", "capacity_ratio", "soc_overestimate_pct", "assumptions")
        finding = {"key": "typed_capacity_P3", "predictor": "P3", "active": active,
                   "severity": 4 if active is True else 5, "title": "P3 conditional capacity hypothesis",
                   "value": value, "evidence": [{"id": "E_TYPED_P3_WINDOW", "text": "conditional fit, overlapping windows; not measured capacity", "value": {k: snapshot[k] for k in evidence_keys}}] if known else [],
                   "lead_s": None, "candidates": [], "rule_choice": None, "executable": False}
        events = []

        def event(kind):
            e = {**finding, "type": kind, "status": snapshot["status"], "sequence": sequence,
                 "t": row["t_s"], "session_id": session_id, "battery_id": row["battery_id"]}
            if kind == "reset":
                e.update(active=None, severity=5, value="window_and_latch_reset", evidence=[])
            events.append(e)

        if reasons:
            event("reset")
        if active is None:
            if old["active"] is not None or initial or reasons:
                event("unknown")
        elif active:
            if old["active"] is not True:
                event("raise")
        elif old["active"] is True:
            event("resolve")
        elif old["active"] is None:
            event("known")
        output = _snapshot({"caller_scope": "bounded_P3_only_conditional_capacity_feed",
                            "status": snapshot["status"], "sequence": sequence, "t_s": row["t_s"],
                            "session_id": session_id, "battery_id": row["battery_id"],
                            "active": active, "risk": risk, "raise_streak": raising, "clear_streak": clearing,
                            "raise_ticks": self._raise_ticks, "clear_ticks": self._clear_ticks,
                            "window_sample_count": len(rows), "max_samples": self._max_samples,
                            "snapshot": snapshot, "finding": finding, "events": events, "reset_reasons": reasons,
                            "evaluated_predictors": ["P3"], "unassessed_predictors": ["P1", "P2", "P4", "P5"],
                            "measured_capacity": False, "sensor_validated": False, "telemetry_freshness_verified": False,
                            "independent_window_evidence": False, "energy_correction_applied": False,
                            "landing_modeled": False, "feasible": False, "executable": False,
                            "candidates": [], "rule_choice": None})
        # Commit only after every validation, evaluation and serialization succeeds.
        self._sequence, self._time, self._session = sequence, row["t_s"], session_id
        self._rows, self._latch = rows, {"active": active, "raise": raising, "clear": clearing}
        return output
