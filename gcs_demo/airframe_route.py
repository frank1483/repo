"""T5b1 straight-flight primitives, not a complete mission/turn planner.

All values are estimates. FW RTL ends in flight at home, not landed. Hybrid
RTL defaults to cruise (fw); callers knowing the current mode may pass mc.
Transitions are additive standalone allowances, not flown trajectories.
"""
from __future__ import annotations

import math


def number(x, name, low=-1e100, high=1e100):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(name + ": finite number required")
    if not low <= x <= high:
        raise ValueError(name + ": out of range")
    return x


def flight_mode(v, mode, default=None):
    expected = "fw" if v.type == "fixed_wing" else "mc"
    if v.type == "vtol_hybrid":
        mode = default if mode is None else mode
        if mode not in ("mc", "fw"):
            raise ValueError("hybrid straight leg requires explicit mode='mc' or 'fw'")
        return mode
    if mode not in (None, expected):
        raise ValueError("mode is incompatible with airframe type")
    return expected


def position(p):
    if not isinstance(p, (tuple, list)) or len(p) != 2:
        raise ValueError("position: [lat, lon] required")
    number(p[0], "lat", -90, 90)
    number(p[1], "lon", -180, 180)


def wind_values(w):
    number(w.speed_mps, "wind.speed_mps", 0)
    number(w.from_deg, "wind.from_deg")
    return w.vector()


def straight_leg(v, a, b, alt_a, alt_b, ground_mps, wind, mode=None):
    from .energy import G, bearing_rad, haversine_m, power_w
    mode = flight_mode(v, mode)
    position(a)
    position(b)
    number(alt_a, "alt_a")
    number(alt_b, "alt_b")
    number(ground_mps, "ground_mps", 1e-9)
    we, wn = wind_values(wind)
    dist = haversine_m(a, b)
    dh = alt_b - alt_a
    if mode == "fw" and dist < 0.5:
        raise ValueError("fixed-wing near-zero horizontal leg: loiter/takeoff/landing not modeled")
    if dist >= 0.5:
        brg = bearing_rad(a, b)
        ae, an = ground_mps * math.sin(brg) - we, ground_mps * math.cos(brg) - wn
        air = math.hypot(ae, an)
        head = -(we * math.sin(brg) + wn * math.cos(brg))
        duration = dist / ground_mps
    else:
        air, head, duration = wind.speed_mps, 0.0, 0.0
    if mode == "fw":
        # Altitude changes occur along the straight leg, not in an extra hover.
        watts = power_w(v, air, mode="fw", climb_mps=max(0, dh) / duration)
        wh = watts * duration / 3600 * v.calib
    else:
        if air > v.max_mps:
            raise ValueError("v_air: outside mc airspeed envelope")
        watts = power_w(v, air, mode="mc")
        vertical_s = max(0, dh) / 3 if dh > 0 else max(0, -dh) / 2
        # MC horizontal then vertical phase. Wind still applies in vertical phase.
        if wind.speed_mps > v.max_mps:
            raise ValueError("wind exceeds mc airspeed envelope during vertical flight")
        joules = watts * duration + power_w(v, wind.speed_mps, mode="mc") * vertical_s
        mc = v.airframe_profile["power"]["mc"] if v.type == "vtol_hybrid" else {"eta": v.eta}
        joules += v.mass_kg * G * max(0, dh) / mc["eta"]
        duration += vertical_s
        wh = joules / 3600 * v.calib
    return {"dist_m": dist, "time_s": duration, "energy_wh": wh,
            "v_air": air, "headwind_mps": head, "mode": mode,
            "scope": "straight_leg_only"}


def transition_estimate(vehicle, from_mode, to_mode):
    """Explicit allowance; caller must separately update its own mode/position.

    No inferred cmd3000 handling in this batch. Distances are allowance-only and
    must not be used as a location update or subtracted from a route silently.
    """
    if vehicle.type != "vtol_hybrid":
        raise ValueError("transition requires vtol_hybrid")
    if from_mode not in ("mc", "fw") or to_mode not in ("mc", "fw"):
        raise ValueError("transition modes must be mc or fw")
    t = vehicle.airframe_profile["transition"]
    changed = from_mode != to_mode
    prefix = "to_" + to_mode
    return {"from_mode": from_mode, "to_mode": to_mode,
            "energy_wh": t[prefix + "_wh"] * vehicle.calib if changed else 0.0,
            "time_s": t[prefix + "_s"] if changed else 0.0,
            "dist_m": t["to_fw_dist_m"] if changed and to_mode == "fw" else 0.0,
            "scope": "transition_allowance_only"}


def typed_rtl(pos, home, vehicle, wind, ground_mps=None, mode=None):
    """Hybrid: level return + to_mc once + MC descent; FW: arrival in flight.

    Both altitudes are relative to home ground (home alt must be 0). Obstacle
    clearance, approach geometry and an executable route are not produced.
    """
    from .energy import haversine_m
    v = vehicle
    mode = flight_mode(v, mode, default="fw")
    a, b = (pos["lat"], pos["lon"]), (home["lat"], home["lon"])
    position(a)
    position(b)
    alt = number(pos.get("alt", 0), "rtl.alt", 0)
    if number(home.get("alt", 0), "home.alt") != 0:
        raise ValueError("RTL expects altitude relative to home ground; home.alt must be zero")
    speed = v.cruise_mps if ground_mps is None else ground_mps
    number(speed, "ground_mps", 1e-9)
    wind_values(wind)
    legs = []
    if v.type == "fixed_wing":
        # A FW cannot vertically descend/land at home. Report airborne arrival.
        legs.append(straight_leg(v, a, b, alt, alt, speed, wind, "fw"))
    elif mode == "fw":
        if haversine_m(a, b) >= 0.5:
            legs.append(straight_leg(v, a, b, alt, alt, speed, wind, "fw"))
        legs.append(transition_estimate(v, "fw", "mc"))
        legs.append(straight_leg(v, b, b, alt, 0, speed, wind, "mc"))
    else:
        legs.append(straight_leg(v, a, b, alt, 0, speed, wind, "mc"))
    wh = sum(x["energy_wh"] for x in legs)
    cap = number(v.battery_wh * v.usable_frac, "usable capacity", 1e-9)
    return {"dist_m": sum(x["dist_m"] for x in legs),
            "time_s": sum(x["time_s"] for x in legs), "energy_wh": wh,
            "used_pct": wh / cap * 100, "legs": legs,
            "arrival_mode": "fw" if v.type == "fixed_wing" else "mc",
            "landing_modeled": v.type != "fixed_wing",
            "scope": "rtl_energy_only_not_executable_route"}


def typed_best_speed(v, wind, heading_deg=0.0, lo=4.0, hi=None, mode=None):
    """Search AIRspeed in 0.5 m/s steps, return achievable forward ground speed.

    Solve the wind triangle on the forward-air branch. A candidate requiring
    backwards air heading or nonpositive ground progress is excluded. This
    optimizes straight flight only, not turns, transitions or a full mission.
    """
    from .energy import power_w, speed_range
    mode = flight_mode(v, mode, default="fw")
    number(heading_deg, "heading_deg")
    number(lo, "lo", 0)
    minimum, maximum = speed_range(v) if mode == "fw" else (0.0, v.max_mps)
    upper = maximum if hi is None else min(maximum, number(hi, "hi", 0))
    lower = max(minimum, lo)
    we, wn = wind_values(wind)
    theta = math.radians(heading_deg)
    tail = we * math.sin(theta) + wn * math.cos(theta)
    cross = we * math.cos(theta) - wn * math.sin(theta)
    best = None
    for k in range(max(0, int(math.floor((upper - lower) / .5 + 1e-9)) + 1)):
        air = lower + k * .5
        if air <= abs(cross):
            continue
        ground = tail + math.sqrt(max(0, air * air - cross * cross))
        if ground <= 1e-9:
            continue
        per_km = power_w(v, air, mode=mode) * v.calib / ground / 3.6
        if best is None or per_km < best["wh_per_km"]:
            best = {"speed_mps": ground, "airspeed_mps": air, "wh_per_km": per_km}
    if best is None:
        raise ValueError("no feasible forward airspeed in configured search interval/wind")
    best["wh_per_km"] = round(best["wh_per_km"], 2)
    return best
