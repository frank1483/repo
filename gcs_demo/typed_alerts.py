"""Typed alert preparation, with explicit caller-owned mission alternatives.

No candidate generation, automatic RTL/landing, live engine or application.
The normalized mission backend retains all its unsupported-geometry limits.
"""
from __future__ import annotations

import json

from .airframe_route import flight_mode, number, wind_values


def _snapshot(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError) as exc:
        raise ValueError("typed alert input must be finite JSON data") from exc


def typed_alert_speeds(vehicle, requested, mode=None, bank_deg=0.0):
    """Filter explicit AIRSPEED options; never convert them to ground speeds.

    Hybrid mode is mandatory. MC does not inherit FW stall limits; MC bank
    is unsupported. Options outside the envelope are reported, not clipped.
    These are envelope options, not an optimum or an acceleration model.
    """
    from .energy import speed_range
    if not vehicle.airframe_profile:
        raise ValueError("typed alerts require an explicit airframe profile")
    active = flight_mode(vehicle, mode)
    number(bank_deg, "bank_deg", -89.999999, 89.999999)
    if active == "mc":
        if bank_deg != 0:
            raise ValueError("MC airspeed options do not model bank")
        limits = vehicle.airframe_profile["limits"]
        low, high = limits["min_airspeed_mps"], limits["max_airspeed_mps"]
    else:
        low, high = speed_range(vehicle, bank_deg)
    number(low, "minimum airspeed", 0)
    number(high, "maximum airspeed", low)
    if not isinstance(requested, list) or not 1 <= len(requested) <= 101:
        raise ValueError("requested airspeeds require 1..101 values")
    values = sorted(set(number(x, "requested airspeed", 0) for x in requested))
    return {"basis": "airspeed_mps_not_ground_speed", "mode": active,
            "minimum_mps": low, "maximum_mps": high,
            "accepted_mps": [x for x in values if low <= x <= high],
            "rejected_mps": [x for x in values if not low <= x <= high]}


def evaluate_typed_alert_candidates(vehicle, candidates, wind, start_pct=100.0):
    """Evaluate 1..16 explicit normalized mission alternatives.

    Each object: id, points, ground_mps, optional mode and hover_s_per_wp.
    Caller supplies the entire outbound/return/transition sequence; no return
    is inferred or certified. Unknown fields and duplicate IDs fail the batch.
    Unsupported route/scenario stays visible. Ranking uses conservative sampled
    endpoint energy only; it does not establish a safe or executable action.
    """
    from .airframe_bounds import bounds, estimate_for_bounds
    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("typed candidate evaluator requires FW/hybrid profile")
    wind_values(wind)
    number(start_pct, "start_pct", 0, 100)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 16:
        raise ValueError("typed candidates require 1..16 alternatives")
    items = _snapshot(candidates)
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not {"id", "points", "ground_mps"} <= set(item):
            raise ValueError("candidate requires id, points, ground_mps")
        if set(item) - {"id", "points", "ground_mps", "mode", "hover_s_per_wp"}:
            raise ValueError("unsupported typed candidate fields")
        key = item["id"]
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or key in seen:
            raise ValueError("candidate id must be unique, nonempty, at most 128 characters")
        seen.add(key)
    rows = []
    for item in items:
        row = {"id": item["id"], "feasible": False, "return_inferred": False}
        try:
            active = flight_mode(vehicle, item.get("mode"))
            points = item["points"]
            if not isinstance(points, list) or not 2 <= len(points) <= 1000:
                raise ValueError("candidate points require 2..1000 events")
            for point in points:
                if not isinstance(point, dict) or ("cmd" not in point and not {"lat", "lon"} <= set(point)):
                    raise ValueError("candidate movement event requires lat/lon")
            estimate = estimate_for_bounds(vehicle, item["points"], item["ground_mps"], wind,
                                           start_pct, item.get("hover_s_per_wp", 0.0), active)
            interval = bounds(estimate, vehicle)
            # Keep unsupported scenarios and nominal evidence, never silently
            # calculate extrema from only the scenarios that happened to work.
            supported = interval["available"]
            row.update({"status": "ok" if supported else "unsupported",
                        "estimate": estimate, "bounds": interval,
                        "sampled_energy_feasible": bool(supported and interval["low_pct"] >= vehicle.reserve_pct)})
            if not supported:
                row["reason"] = "one or more full-route scenarios unsupported"
        except (ValueError, NotImplementedError) as exc:
            row.update({"status": "unsupported", "reason": str(exc),
                        "sampled_energy_feasible": False})
        rows.append(row)
    eligible = [r for r in rows if r["sampled_energy_feasible"]]
    best = max(eligible, key=lambda r: r["bounds"]["low_pct"]) if eligible else None
    return {"scope": "caller_supplied_normalized_mission_energy_comparison_only",
            "candidates": rows, "best_energy_id": best["id"] if best else None,
            "ranking": "maximum_sampled_low_pct_first_input_on_tie",
            "return_inferred": False, "wind_direction_varied": False,
            "feasible": False, "executable": False}
