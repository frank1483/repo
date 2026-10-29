"""Typed P1 energy predictor for caller-owned geographic alternatives.

This additive predictor does not run the legacy ENU engine, calibrate a
battery, infer a return/landing route, choose a flight action or connect UI.
"""
from __future__ import annotations

import copy

from ..airframe_route import flight_mode, number
from ..geographic_alerts import _snapshot, evaluate_geographic_alert_candidates


def geographic_energy_alert_snapshot(vehicle, candidates, current_id, wind, start_pct=100.0):
    """Evaluate one explicit current plan and alternatives at a common start.

    All entry fields must match exactly, and flight modes must agree. Missing
    geometry remains unsupported, never a clear/safe result. Bounds describe
    finite energy samples, not flight feasibility or a landing prediction.
    """
    items = _snapshot(candidates)
    # Delegate full schema, profile, wind and percentage validation first.
    comparison = evaluate_geographic_alert_candidates(vehicle, items, wind, start_pct)
    if not isinstance(current_id, str) or current_id not in [x["id"] for x in items]:
        raise ValueError("current_id must identify one supplied candidate")
    current = next(x for x in items if x["id"] == current_id)
    active_mode = flight_mode(vehicle, current.get("mode"))
    if active_mode != "fw":
        raise ValueError("typed geographic alerts require FW mode")
    for item in items:
        pose = item["entry"]
        if not isinstance(pose, dict) or set(pose) != {"lat", "lon", "alt", "air_heading_deg"}:
            raise ValueError("typed alert entry requires lat, lon, alt, air_heading_deg")
        number(pose["lat"], "entry lat", -75, 75)
        number(pose["lon"], "entry lon", -180, 180)
        number(pose["alt"], "entry alt", 0)
        number(pose["air_heading_deg"], "entry air_heading_deg")
        if item["entry"] != current["entry"]:
            raise ValueError("typed alert alternatives require one identical entry pose")
        if flight_mode(vehicle, item.get("mode")) != active_mode:
            raise ValueError("typed alert alternatives require one flight mode")
    row = next(x for x in comparison["candidates"] if x["id"] == current_id)
    known = row["status"] == "ok"
    bounds = row.get("bounds", {})
    reserve = vehicle.reserve_pct
    risk = bounds["low_pct"] < reserve if known else None
    nominal = bounds.get("nominal", {})
    nominal_pct = nominal.get("end_pct") if nominal.get("status") == "ok" else None
    return _snapshot({
        "scope": "typed_geographic_P1_finite_energy_samples_only",
        "status": "ok" if known else "unsupported", "current_id": current_id,
        "entry": current["entry"], "mode": active_mode, "start_pct": start_pct,
        "reserve_pct": reserve, "sampled_energy_risk": risk,
        "nominal_end_pct": nominal_pct,
        "low_pct": bounds.get("low_pct") if known else None,
        "high_pct": bounds.get("high_pct") if known else None,
        "comparison": comparison, "rule_choice": None,
        "return_inferred": False, "landing_modeled": False,
        "feasible": False, "executable": False,
    })


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(name + " must be an integer in range")
    return value


class GeographicEnergyAlertPredictor:
    """Stateful P1-only latch; caller supplies a strictly increasing sequence.

    Unsupported input consumes its sequence, resets the latch and returns
    active=None. A later known sample must satisfy raise_ticks anew. Schema
    errors consume neither sequence nor streak. Each return is detached.
    """
    def __init__(self, vehicle, raise_ticks=3, clear_ticks=10):
        self._raise_ticks = _integer(raise_ticks, "raise_ticks", 1, 10000)
        self._clear_ticks = _integer(clear_ticks, "clear_ticks", 1, 10000)
        self._vehicle = copy.deepcopy(vehicle)
        self._last_sequence = -1
        self._active = False
        self._raise = self._clear = 0

    def tick(self, sequence, candidates, current_id, wind, start_pct=100.0):
        _integer(sequence, "sequence", 0, 9007199254740991)
        if sequence <= self._last_sequence:
            raise ValueError("sequence must increase strictly")
        result = geographic_energy_alert_snapshot(self._vehicle, candidates, current_id, wind, start_pct)
        # Commit state only after the complete request has validated/evaluated.
        self._last_sequence = sequence
        known = result["status"] == "ok"
        risk = result["sampled_energy_risk"]
        if not known:
            self._active = False
            self._raise = self._clear = 0
        elif risk:
            self._raise = min(self._raise + 1, self._raise_ticks)
            self._clear = 0
            if self._raise >= self._raise_ticks:
                self._active = True
        else:
            self._clear = min(self._clear + 1, self._clear_ticks)
            self._raise = 0
            if self._clear >= self._clear_ticks:
                self._active = False
        active = self._active if known else None
        severity = 5 if not active else (2 if result["nominal_end_pct"] < 0 else 4)
        finding = None
        if known:
            finding = {"key": "typed_geographic_energy", "active": active,
                       "severity": severity,
                       "title": "Typed geographic route energy samples",
                       "value": "sampled reserve risk" if risk else "sampled reserve met",
                       "evidence": [{"id": "E_TYPED_P1", "text": "finite energy samples; no landing modeled",
                                     "value": {k: result[k] for k in ("current_id", "nominal_end_pct", "low_pct", "high_pct", "reserve_pct")}}],
                       "candidates": [], "rule_choice": None, "lead_s": None}
        result.update({"sequence": sequence, "active": active, "finding": finding,
                       "raise_streak": self._raise, "clear_streak": self._clear,
                       "raise_ticks": self._raise_ticks, "clear_ticks": self._clear_ticks})
        return _snapshot(result)
