"""Explicit tangent-connected FW energy events in one local east/north plane.

No latitude/longitude conversion, automatic waypoint fillet, altitude change,
mode transition, acceleration, landing or executable trajectory is inferred.
Caller supplies the entry air heading and each arc/loiter's airspeed/direction.
"""
from __future__ import annotations

import math

from .airframe_route import flight_mode, number, wind_values


def wind_route_estimate(v, entry, events, wind, start_pct=100.0, mode=None):
    """Join explicit arcs/loiters to straight targets; reject tangent mismatch.

    entry: {east_m, north_m, air_heading_deg}. Events:
    straight: {kind, east_m, north_m, ground_mps};
    arc: {kind, v_air, angle_deg, clockwise, bank_deg? OR radius_m?};
    loiter: {kind, v_air, duration_s, clockwise, radius_m?}.
    Only optional extra event key is id. All coordinates share the entry's
    flat local frame. Straight targets are measured from the drifted exit.
    Subsequent events must retain airspeed within 1e-6 m/s and air heading
    within 1e-6 degrees. Tolerances are numerical checks, not flight limits.
    """
    from .energy import power_w
    from .wind_arc import wind_arc_estimate, wind_loiter_estimate

    if flight_mode(v, mode) != "fw":
        raise ValueError("wind route requires FW mode")
    if not isinstance(entry, dict) or set(entry) != {"east_m", "north_m", "air_heading_deg"}:
        raise ValueError("entry requires only east_m, north_m, air_heading_deg")
    if not isinstance(events, list) or not 1 <= len(events) <= 1000:
        raise ValueError("wind route requires 1..1000 events")
    east = number(entry["east_m"], "east_m")
    north = number(entry["north_m"], "north_m")
    heading = number(entry["air_heading_deg"], "air_heading_deg") % 360
    number(start_pct, "start_pct", 0, 100)
    we, wn = wind_values(wind)
    capacity = number(v.battery_wh * v.usable_frac, "usable capacity", 1e-9)
    previous_air, legs, energy, seconds, air_distance, straight_distance = None, [], 0.0, 0.0, 0.0, 0.0
    allowed = {"straight": {"kind", "id", "east_m", "north_m", "ground_mps"},
               "arc": {"kind", "id", "v_air", "angle_deg", "clockwise", "bank_deg", "radius_m"},
               "loiter": {"kind", "id", "v_air", "duration_s", "clockwise", "radius_m"}}
    for index, event in enumerate(events):
        if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
            raise ValueError("event requires a kind")
        kind = event["kind"]
        if kind not in allowed or set(event) - allowed[kind]:
            raise ValueError("unsupported wind-route event fields")
        start = {"east_m": east, "north_m": north}
        if kind == "straight":
            target_e = number(event.get("east_m"), "east_m")
            target_n = number(event.get("north_m"), "north_m")
            speed = number(event.get("ground_mps"), "ground_mps", 1e-9)
            de, dn = target_e - east, target_n - north
            distance = number(math.hypot(de, dn), "straight distance", 1e-6)
            ae, an = speed * de / distance - we, speed * dn / distance - wn
            air = number(math.hypot(ae, an), "v_air", 1e-9)
            required = math.degrees(math.atan2(ae, an)) % 360
            if abs((required - heading + 180) % 360 - 180) > 1e-6:
                raise ValueError("straight target is not tangent to entry air heading")
            duration = distance / speed
            part = {"time_s": duration, "energy_wh": power_w(v, air, "fw") * duration / 3600 * v.calib,
                    "air_dist_m": air * duration, "straight_dist_m": distance,
                    "exit_air_heading_deg": required,
                    "exit_ground_heading_deg": math.degrees(math.atan2(de, dn)) % 360,
                    "exit_ground_speed_mps": speed,
                    "ground_displacement_m": {"east": de, "north": dn}}
        else:
            air = number(event.get("v_air"), "v_air", 1e-9)
            clockwise = event.get("clockwise")
            if kind == "arc":
                part = wind_arc_estimate(v, air, event.get("angle_deg"), wind, heading,
                                         clockwise, event.get("bank_deg"), event.get("radius_m"))
            else:
                part = wind_loiter_estimate(v, air, event.get("duration_s"), wind, heading,
                                            clockwise, event.get("radius_m"))
            part["straight_dist_m"] = 0.0
        if previous_air is not None and abs(air - previous_air) > 1e-6:
            raise ValueError("airspeed discontinuity: acceleration is not modeled")
        previous_air = air
        east = number(east + part["ground_displacement_m"]["east"], "exit east_m")
        north = number(north + part["ground_displacement_m"]["north"], "exit north_m")
        heading = part["exit_air_heading_deg"]
        energy = number(energy + part["energy_wh"], "route energy", 0)
        seconds = number(seconds + part["time_s"], "route time", 0)
        air_distance = number(air_distance + part["air_dist_m"], "air distance", 0)
        straight_distance = number(straight_distance + part["straight_dist_m"], "straight distance", 0)
        legs.append({**part, "kind": kind, "id": event.get("id", "E" + str(index)),
                     "entry_local_m": start, "exit_local_m": {"east_m": east, "north_m": north},
                     "pct_after": start_pct - energy / capacity * 100})
    end_pct = start_pct - energy / capacity * 100
    return {"energy_wh": energy, "time_s": seconds, "air_dist_m": air_distance,
            "straight_dist_m": straight_distance, "end_pct": end_pct,
            "used_pct": start_pct - end_pct, "margin_pct": end_pct - v.reserve_pct,
            "energy_feasible": end_pct >= v.reserve_pct,
            "feasible": False, "landing_modeled": False, "arrival_mode": "fw",
            "exit_local_m": {"east_m": east, "north_m": north},
            "exit_air_heading_deg": heading, "exit_ground_heading_deg": legs[-1]["exit_ground_heading_deg"],
            "exit_ground_speed_mps": legs[-1]["exit_ground_speed_mps"], "legs": legs,
            "scope": "explicit_local_tangent_energy_route_not_executable_route"}
