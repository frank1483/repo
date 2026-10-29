"""T5b2a normalized energy events; never a MAVLink parser or flight plan.

Coordinated arcs are air-relative, additive allowances. Until a ground-track
model is supplied, FW arcs/loiters require calm air. Straight legs retain wind.
"""
from __future__ import annotations

import math

from .airframe_route import (flight_mode, number, position, straight_leg,
                             transition_estimate, wind_values)


def turn_estimate(v, v_air, angle_deg, wind, bank_deg=None, radius_m=None):
    from .energy import power_w, turn_geometry
    number(angle_deg, "angle_deg", 0, 360)
    wind_values(wind)
    if wind.speed_mps != 0:
        raise ValueError("FW arc requires calm wind; ground-track turn model pending")
    g = turn_geometry(v, v_air, bank_deg, radius_m)
    if g["radius_m"] is None and angle_deg != 0:
        raise ValueError("nonzero turn requires nonzero bank")
    distance = (g["radius_m"] or 0) * math.radians(angle_deg)
    seconds = distance / number(v_air, "v_air", 1e-9)
    return {**g, "angle_deg": angle_deg, "dist_m": distance, "time_s": seconds,
            "energy_wh": power_w(v, v_air, "fw", g["bank_deg"]) * seconds / 3600 * v.calib,
            "mode": "fw", "scope": "additive_air_relative_arc_allowance"}


def loiter_estimate(v, v_air, duration_s, wind, radius_m=None, mode=None):
    from .energy import power_w, turn_geometry
    mode = flight_mode(v, mode)
    number(duration_s, "duration_s", 0, 86400)
    number(v_air, "v_air", 1e-9)
    wind_values(wind)
    if mode == "mc":
        if radius_m is not None:
            raise ValueError("MC hold does not accept an orbit radius")
        if wind.speed_mps > v.max_mps:
            raise ValueError("wind exceeds mc airspeed envelope during hold")
        return {"dist_m": 0.0, "time_s": duration_s,
                "energy_wh": power_w(v, wind.speed_mps, "mc") * duration_s / 3600 * v.calib,
                "mode": "mc", "scope": "stationary_mc_hold"}
    if wind.speed_mps != 0:
        raise ValueError("FW loiter requires calm wind; ground-track orbit model pending")
    g = turn_geometry(v, v_air, radius_m=radius_m)
    return {**g, "dist_m": v_air * duration_s, "time_s": duration_s,
            "energy_wh": power_w(v, v_air, "fw", g["bank_deg"]) * duration_s / 3600 * v.calib,
            "mode": "fw", "scope": "air_relative_loiter_allowance"}


def typed_route(v, points, ground_mps, wind, start_pct=100.0,
                hover_s_per_wp=5.0, mode=None):
    """Normalized local events, not raw mission items.

    First point is the current pose. Hybrid requires mode (or first.mode),
    except a first.kind=takeoff explicitly denotes an MC start. Movement
    points omit cmd. cmd=3000 requires to_mode=mc|fw, has no displacement,
    and any supplied coordinates/altitude must match the current pose.
    Hybrid takeoff/landing points use MC; cruise entry requires an explicit
    transition. FW landing/takeoff and unknown commands are rejected.
    """
    from .energy import bearing_rad, haversine_m
    if v.type == "multirotor":
        raise ValueError("typed_route is reserved for FW/hybrid; legacy MC route unchanged")
    if not isinstance(points, list) or not 2 <= len(points) <= 1000:
        raise ValueError("route requires 2..1000 normalized events")
    number(ground_mps, "ground_mps", 1e-9)
    number(start_pct, "start_pct", 0, 100)
    number(hover_s_per_wp, "hover_s_per_wp", 0, 86400)
    wind_values(wind)
    cap = number(v.battery_wh * v.usable_frac, "usable capacity", 1e-9)

    def pose(p):
        if not isinstance(p, dict):
            raise ValueError("point must be an object")
        position([p.get("lat"), p.get("lon")])
        number(p.get("alt", 0), "alt", 0)

    first = points[0]
    pose(first)
    if "cmd" in first or first.get("kind") in ("landing", "loiter"):
        raise ValueError("first event must be a pose, not a command/landing/loiter")
    if mode is not None and first.get("mode", mode) != mode:
        raise ValueError("initial mode contradicts first.mode")
    initial = first.get("mode") if mode is None else mode
    if initial is None and first.get("kind") == "takeoff":
        initial = "mc"
    active = flight_mode(v, initial)
    if first.get("kind") == "takeoff" and (v.type != "vtol_hybrid" or active != "mc" or first.get("alt", 0) != 0):
        raise ValueError("takeoff start requires hybrid mc on ground")
    current = dict(first, id=first.get("id", "P0"))
    legs, heading, landed, after_fw_loiter = [], None, False, False
    pct = start_pct

    def add(part, event_id):
        nonlocal pct
        pct -= part["energy_wh"] / cap * 100
        legs.append({**part, "from": current["id"], "to": event_id, "pct_after": pct})

    for i, raw in enumerate(points[1:], 1):
        if not isinstance(raw, dict):
            raise ValueError("event must be an object")
        event_id = raw.get("id", "P" + str(i))
        if landed:
            raise ValueError("events after landing are unsupported")
        if "cmd" in raw:
            if isinstance(raw["cmd"], bool) or raw["cmd"] != 3000 or v.type != "vtol_hybrid":
                raise ValueError("only normalized hybrid cmd3000 is supported")
            if set(raw) - {"id", "cmd", "to_mode", "lat", "lon", "alt"}:
                raise ValueError("unsupported cmd3000 fields; normalize before estimating")
            for key in ("lat", "lon", "alt"):
                if key in raw:
                    number(raw[key], key)
                    if raw[key] != current.get(key, 0):
                        raise ValueError("cmd3000 cannot change pose")
            t = transition_estimate(v, active, raw.get("to_mode"))
            changed = active != t["to_mode"]
            add({**t, "transition_allowance_dist_m": t["dist_m"], "dist_m": 0.0}, event_id)
            active = t["to_mode"]
            if changed:
                heading = None
                after_fw_loiter = False
            continue
        pose(raw)
        kind = raw.get("kind", "waypoint")
        if kind not in ("waypoint", "target", "home", "takeoff", "landing", "loiter"):
            raise ValueError("unsupported normalized point kind")
        if kind in ("takeoff", "landing"):
            if v.type != "vtol_hybrid":
                raise ValueError("FW takeoff/landing geometry is not modeled")
            if kind == "takeoff" and (current.get("alt", 0) != 0 or raw.get("alt", 0) <= 0):
                raise ValueError("takeoff must leave ground for positive altitude")
            if kind == "landing" and (raw.get("alt", 0) != 0 or current.get("alt", 0) <= 0):
                raise ValueError("landing must descend to relative ground altitude zero")
            if active != "mc":
                t = transition_estimate(v, active, "mc")
                add({**t, "transition_allowance_dist_m": t["dist_m"], "dist_m": 0.0}, event_id)
                active, heading, after_fw_loiter = "mc", None, False
        if raw.get("mode", active) != active:
            raise ValueError("mode changes require cmd3000 or a takeoff/landing event")
        a, b = [current["lat"], current["lon"]], [raw["lat"], raw["lon"]]
        distance = haversine_m(a, b)
        outbound = bearing_rad(a, b) if distance >= 0.5 else None
        if active == "fw" and after_fw_loiter and outbound is not None:
            raise ValueError("FW departure after loiter requires an exit-heading model")
        if active == "fw" and heading is not None and outbound is not None:
            angle = abs((math.degrees(outbound - heading) + 180) % 360 - 180)
            if angle > 1e-9:
                add(turn_estimate(v, ground_mps, angle, wind), current["id"])
        dwell = raw.get("loiter_s", hover_s_per_wp if kind == "target" else 0.0)
        number(dwell, "loiter_s", 0, 86400)
        if kind == "loiter" and dwell <= 0:
            raise ValueError("loiter event requires positive loiter_s")
        same_pose_hold = (active == "fw" and distance < 0.5 and raw.get("alt", 0) == current.get("alt", 0) and dwell > 0)
        if not same_pose_hold:
            add(straight_leg(v, a, b, current.get("alt", 0), raw.get("alt", 0), ground_mps, wind, active), event_id)
        if dwell > 0:
            add(loiter_estimate(v, ground_mps, dwell, wind, raw.get("radius_m"), active), event_id)
        elif "radius_m" in raw:
            raise ValueError("radius_m requires a positive loiter duration")
        heading = outbound if active == "fw" and dwell == 0 else None
        after_fw_loiter = active == "fw" and dwell > 0
        current = dict(raw, id=event_id)
        landed = kind == "landing"

    energy = sum(x["energy_wh"] for x in legs)
    energy_ok = pct >= v.reserve_pct
    return {"dist_m": sum(x["dist_m"] for x in legs), "time_s": sum(x["time_s"] for x in legs),
            "energy_wh": energy, "end_pct": pct, "used_pct": start_pct - pct,
            "margin_pct": pct - v.reserve_pct, "feasible": energy_ok and landed,
            "energy_feasible": energy_ok, "arrival_mode": active, "landing_modeled": landed,
            "transition_allowance_dist_m": sum(x.get("transition_allowance_dist_m", 0) for x in legs),
            "scope": "normalized_route_energy_only_not_executable_route", "legs": legs}
