"""Finite full-route uncertainty scenarios; not a probabilistic/robust bound.

No route inference: caller must include the outbound AND return events. One
Wind is used for the whole route in each replay. Unsupported scenarios make
the entire interval unavailable, rather than disappearing from the extrema.
"""
from __future__ import annotations

import copy
import json
import math


def _number(x, name, low=0, high=1e100):
    if (isinstance(x, bool) or not isinstance(x, (int, float))
            or not math.isfinite(x) or x < low or (high is not None and x > high)):
        raise ValueError(name + ": finite number in range required")
    return x


def _snapshot(x):
    return json.loads(json.dumps(x, allow_nan=False))


def _request(v, points, ground_mps, wind, start_pct, hover_s_per_wp, mode):
    from .airframe_route import position, wind_values
    if not isinstance(points, list) or not 2 <= len(points) <= 1000:
        raise ValueError("bounds route: requires 2..1000 explicit events")
    for p in points:
        if not isinstance(p, dict):
            raise ValueError("bounds route event must be an object")
        if "cmd" in p and v.type != "vtol_hybrid":
            raise ValueError("mode events require a hybrid airframe")
        if "cmd" not in p:
            position((p["lat"], p["lon"]))
            _number(p.get("alt", 0), "alt")
        if "loiter_s" in p:
            _number(p["loiter_s"], "loiter_s", 0, 86400)
    _number(ground_mps, "ground_mps", 1e-9)
    _number(start_pct, "start_pct", 0, 100)
    _number(hover_s_per_wp, "hover_s_per_wp", 0, 86400)
    _number(v.battery_wh * v.usable_frac, "usable capacity", 1e-9)
    _number(v.reserve_pct, "reserve_pct", 0, 100)
    if mode not in (None, "mc", "fw"):
        raise ValueError("unknown flight mode")
    wind_values(wind)
    normalized = [dict(p, id=p.get("id", "P" + str(i))) for i, p in enumerate(points)]
    return _snapshot({"schema": 1, "route": normalized, "ground_mps": ground_mps,
                      "wind": {"speed_mps": wind.speed_mps, "from_deg": wind.from_deg},
                      "start_pct": start_pct, "hover_s_per_wp": hover_s_per_wp,
                      "mode": mode, "vehicle": v.to_dict()})


def estimate_for_bounds(vehicle, points, ground_mps, wind, start_pct=100.0,
                        hover_s_per_wp=0.0, mode=None):
    """Normal estimate + a detached JSON replay context; old APIs unchanged."""
    from .energy import route_estimate
    c = _request(vehicle, points, ground_mps, wind, start_pct, hover_s_per_wp, mode)
    result = route_estimate(vehicle, copy.deepcopy(c["route"]), ground_mps, wind,
                            start_pct, hover_s_per_wp, mode)
    return {**result, "bounds_context": c}


def bounds(estimate, vehicle):
    """Return sampled endpoint-% extrema and full wind/power/capacity evidence.

    Nominal plus the Cartesian product of three wind speeds and two power /
    capacity multipliers (duplicates removed). Direction is held fixed. Power
    uncertainty scales ALL energy, including climbs/transitions, exactly once;
    capacity uncertainty scales usable Wh only, never starting percentage.
    """
    from .energy import Wind, route_estimate
    if not isinstance(estimate, dict) or not isinstance(estimate.get("bounds_context"), dict):
        raise ValueError("bounds requires estimate_for_bounds replay context")
    c = _snapshot(estimate["bounds_context"])
    keys = {"schema", "route", "ground_mps", "wind", "start_pct", "hover_s_per_wp", "mode", "vehicle"}
    if set(c) != keys or type(c["schema"]) is not int or c["schema"] != 1:
        raise ValueError("unsupported bounds context")
    if c["vehicle"] != _snapshot(vehicle.to_dict()):
        raise ValueError("bounds context belongs to a different vehicle snapshot")
    if not isinstance(c["wind"], dict) or set(c["wind"]) != {"speed_mps", "from_deg"}:
        raise ValueError("invalid context wind")
    w = Wind(**c["wind"])
    _request(vehicle, c["route"], c["ground_mps"], w, c["start_pct"], c["hover_s_per_wp"], c["mode"])
    if not vehicle.airframe_profile:
        raise ValueError("bounds requires a profile with explicit uncertainty")
    u = vehicle.airframe_profile["uncertainty"]
    power = _number(u["power_pct"], "uncertainty.power_pct", 0, 100) / 100
    capacity = _number(u["capacity_pct"], "uncertainty.capacity_pct", 0, 100) / 100
    delta = _number(u["wind_mps"], "uncertainty.wind_mps")
    if capacity >= 1:
        raise ValueError("capacity uncertainty must leave positive usable Wh")
    tuples = [(w.speed_mps, 1.0, 1.0)]
    for speed in (max(0.0, w.speed_mps - delta), w.speed_mps, w.speed_mps + delta):
        for pm in (1 - power, 1 + power):
            for cm in (1 - capacity, 1 + capacity):
                if (speed, pm, cm) not in tuples:
                    tuples.append((speed, pm, cm))
    rows = []
    for i, (speed, pm, cm) in enumerate(tuples):
        row = {"id": "S" + str(i), "wind": {"speed_mps": speed, "from_deg": w.from_deg},
               "power_multiplier": pm, "capacity_multiplier": cm}
        try:
            # NEVER split outbound/return or perturb wind per leg.
            e = route_estimate(vehicle, copy.deepcopy(c["route"]), c["ground_mps"],
                               Wind(speed, w.from_deg), c["start_pct"], c["hover_s_per_wp"], c["mode"])
            wh = _number(_number(e["energy_wh"], "replayed energy_wh") * pm, "scaled energy_wh")
            cap = _number(vehicle.battery_wh * vehicle.usable_frac * cm, "scenario capacity", 1e-9)
            end = _number(c["start_pct"] - wh / cap * 100, "end_pct", -1e100)
            # Keep negative endpoint percentages: saturation would hide deficit.
            row.update({"status": "ok", "base_energy_wh": e["energy_wh"], "energy_wh": wh,
                        "capacity_wh": cap, "end_pct": end, "margin_pct": end - vehicle.reserve_pct,
                        "energy_feasible": end >= vehicle.reserve_pct,
                        "landing_modeled": e.get("landing_modeled", False),
                        "legs": e["legs"]})
        except (ValueError, NotImplementedError) as exc:
            row.update({"status": "unsupported", "reason": str(exc)})
        rows.append(row)
    ok = all(r["status"] == "ok" for r in rows)
    low = min(rows, key=lambda r: r["end_pct"]) if ok else None
    high = max(rows, key=lambda r: r["end_pct"]) if ok else None
    return {"available": ok, "scope": "finite_full_route_scenarios_not_robust_or_probability_interval",
            "wind_direction_varied": False, "return_inferred": False,
            "low_pct": low["end_pct"] if ok else None, "high_pct": high["end_pct"] if ok else None,
            "conservative": low, "optimistic": high, "nominal": rows[0], "scenarios": rows}
