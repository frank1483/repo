"""Explicit geographic wind-event energy scenarios and typed alternatives.

No route generation, endpoint constraint solver, landing model or live action.
Every scenario replays the same full event list with one constant wind. Its
drifted endpoint may differ; this is not an endpoint/trajectory safety bound.
"""
from __future__ import annotations

import json
import math

from .airframe_route import flight_mode, number, wind_values


def _snapshot(value):
    def check(x, stack):
        if x is None or isinstance(x, (str, bool)):
            return
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            if not math.isfinite(x):
                raise ValueError("geographic alert input must be finite JSON data")
            return
        if not isinstance(x, (list, dict)) or id(x) in stack:
            raise ValueError("geographic alert input must be finite JSON data")
        stack.add(id(x))
        if isinstance(x, dict):
            if not all(isinstance(k, str) for k in x):
                raise ValueError("JSON object keys must be strings")
            for item in x.values():
                check(item, stack)
        else:
            for item in x:
                check(item, stack)
        stack.remove(id(x))
    check(value, set())
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError) as exc:
        raise ValueError("geographic alert input must be finite JSON data") from exc


def geographic_wind_route_bounds(vehicle, entry, events, wind, start_pct=100.0, mode=None):
    """Nominal plus deduplicated wind/power/capacity corner scenarios.

    Scalars follow airframe_bounds: power scales total calibrated Wh once;
    capacity scales usable Wh, not starting %. Unscaled geometry/leg energy
    stays under base_estimate. Any unsupported scenario invalidates BOTH
    extrema, including when nominal fails. Negative percentages are retained.
    Geometry/tangency, 10 km and all part_i restrictions apply per scenario.
    """
    from .energy import Wind, geographic_wind_route_estimate

    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("geographic bounds require FW/hybrid profile")
    active = flight_mode(vehicle, mode)
    if active != "fw":
        raise ValueError("geographic bounds support only explicit FW flight")
    wind_values(wind)
    number(start_pct, "start_pct", 0, 100)
    usable = number(vehicle.battery_wh * vehicle.usable_frac, "usable capacity", 1e-9)
    reserve = number(vehicle.reserve_pct, "reserve_pct", 0, 100)
    request = _snapshot({"entry": entry, "events": events})
    u = vehicle.airframe_profile["uncertainty"]
    power = number(u["power_pct"], "uncertainty.power_pct", 0, 100) / 100
    capacity = number(u["capacity_pct"], "uncertainty.capacity_pct", 0, 100) / 100
    delta = number(u["wind_mps"], "uncertainty.wind_mps", 0)
    if capacity >= 1:
        raise ValueError("capacity uncertainty must leave positive usable Wh")
    tuples = [(wind.speed_mps, 1.0, 1.0)]
    for speed in (max(0.0, wind.speed_mps - delta), wind.speed_mps, wind.speed_mps + delta):
        for pm in (1 - power, 1 + power):
            for cm in (1 - capacity, 1 + capacity):
                if (speed, pm, cm) not in tuples:
                    tuples.append((speed, pm, cm))
    rows = []
    for i, (speed, pm, cm) in enumerate(tuples):
        row = {"id": "G" + str(i), "wind": {"speed_mps": speed, "from_deg": wind.from_deg},
               "power_multiplier": pm, "capacity_multiplier": cm}
        try:
            # No per-leg wind choice, event retargeting or implicit connectors.
            e = geographic_wind_route_estimate(vehicle, request["entry"], request["events"],
                                               Wind(speed, wind.from_deg), start_pct, active)
            wh = number(number(e["energy_wh"], "base energy_wh", 0) * pm, "scaled energy_wh", 0)
            cap = number(usable * cm, "scenario capacity", 1e-9)
            end = number(start_pct - wh / cap * 100, "end_pct")
            row.update({"status": "ok", "base_estimate": e, "base_energy_wh": e["energy_wh"],
                        "energy_wh": wh, "capacity_wh": cap, "end_pct": end,
                        "margin_pct": end - reserve, "energy_feasible": end >= reserve,
                        "landing_modeled": False})
        except (ValueError, NotImplementedError) as exc:
            row.update({"status": "unsupported", "reason": str(exc)})
        rows.append(row)
    available = all(r["status"] == "ok" for r in rows)
    low = min(rows, key=lambda r: r["end_pct"]) if available else None
    high = max(rows, key=lambda r: r["end_pct"]) if available else None
    # Independent JSON copies prevent consumer edits to nominal/conservative
    # from changing the scenario evidence (or any caller-owned input).
    return _snapshot({"available": available, "scenarios": rows, "nominal": rows[0],
                      "low_pct": low["end_pct"] if available else None,
                      "high_pct": high["end_pct"] if available else None,
                      "conservative": low, "optimistic": high,
                      "scope": "finite_geographic_event_scenarios_not_robust_or_probability_interval",
                      "wind_direction_varied": False, "return_inferred": False,
                      "common_endpoint_enforced": False, "geometry_replayed": True,
                      "landing_modeled": False, "feasible": False, "executable": False})


def evaluate_geographic_alert_candidates(vehicle, candidates, wind, start_pct=100.0):
    """Compare 1..16 caller-supplied geographic entry/events alternatives.

    Candidate keys: id, entry, events, optional mode. Never accepts normalized
    mission points, ENU tuples or actions. Unique IDs and finite JSON required.
    Unsupported geometry stays per candidate; malformed batch schema fails.
    Ranked energy is endpoint sample energy only; caller owns route intent.
    """
    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("geographic candidates require FW/hybrid profile")
    wind_values(wind)
    number(start_pct, "start_pct", 0, 100)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 16:
        raise ValueError("geographic candidates require 1..16 alternatives")
    items = _snapshot(candidates)
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not {"id", "entry", "events"} <= set(item):
            raise ValueError("geographic candidate requires id, entry, events")
        if set(item) - {"id", "entry", "events", "mode"}:
            raise ValueError("unsupported geographic candidate fields")
        key = item["id"]
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or key in seen:
            raise ValueError("candidate id must be unique, nonempty, at most 128 characters")
        seen.add(key)
    rows = []
    for item in items:
        row = {"id": item["id"], "feasible": False, "return_inferred": False,
               "sampled_energy_feasible": False}
        try:
            interval = geographic_wind_route_bounds(vehicle, item["entry"], item["events"],
                                                    wind, start_pct, item.get("mode"))
            supported = interval["available"]
            row.update({"status": "ok" if supported else "unsupported", "bounds": interval,
                        "sampled_energy_feasible": bool(supported and interval["low_pct"] >= vehicle.reserve_pct)})
            if not supported:
                row["reason"] = "one or more full geographic event scenarios unsupported"
        except (ValueError, NotImplementedError) as exc:
            row.update({"status": "unsupported", "reason": str(exc)})
        rows.append(row)
    eligible = [r for r in rows if r["sampled_energy_feasible"]]
    best = max(eligible, key=lambda r: r["bounds"]["low_pct"]) if eligible else None
    return {"scope": "caller_supplied_geographic_event_energy_comparison_only",
            "candidates": rows, "best_energy_id": best["id"] if best else None,
            "ranking": "maximum_sampled_low_pct_first_input_on_tie",
            "return_inferred": False, "wind_direction_varied": False,
            "common_endpoint_enforced": False, "feasible": False, "executable": False}
