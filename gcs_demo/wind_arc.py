"""Constant-air-speed, constant-bank FW allowances in uniform steady wind.

These are air-relative circles that drift with the air mass, NOT ground-fixed
orbits, waypoint joins, normalized-route events, or executable flight plans.
Displacement is local east/north from the entry position; altitude is constant.
"""
from __future__ import annotations

import math

from .airframe_route import number, wind_values


def _estimate(v, v_air, duration_s, wind, entry_heading_deg, clockwise, geometry):
    from .energy import power_w
    number(entry_heading_deg, "entry_heading_deg")
    if not isinstance(clockwise, bool):
        raise ValueError("clockwise: boolean required")
    we, wn = wind_values(wind)
    # Bank sign follows the explicitly requested direction (heading clockwise
    # from north). Geometry uses its magnitude for load factor and stall checks.
    bank = abs(geometry["bank_deg"]) * (1 if clockwise else -1)
    radius = geometry["radius_m"]
    if radius is None:
        raise ValueError("wind arc/loiter requires a nonzero bank")
    omega = v_air / radius * (1 if clockwise else -1)
    entry = entry_heading_deg % 360
    sweep = omega * duration_s
    # Reduce periodic trig arguments, keeping total sweep separately.
    theta = math.radians(entry)
    end = theta + math.fmod(sweep, 2 * math.pi)
    ae = v_air / omega * (math.cos(theta) - math.cos(end))
    an = v_air / omega * (math.sin(end) - math.sin(theta))
    drift_e, drift_n = we * duration_s, wn * duration_s
    exit_e, exit_n = v_air * math.sin(end) + we, v_air * math.cos(end) + wn
    exit_speed = math.hypot(exit_e, exit_n)
    ground_heading = (math.degrees(math.atan2(exit_e, exit_n)) % 360
                      if exit_speed > 1e-9 else None)
    watts = power_w(v, v_air, "fw", bank)
    return {**geometry, "bank_deg": bank, "time_s": duration_s,
            "air_dist_m": v_air * duration_s,
            "energy_wh": watts * duration_s / 3600 * v.calib,
            "entry_air_heading_deg": entry,
            "exit_air_heading_deg": math.degrees(end) % 360,
            "signed_sweep_deg": math.degrees(sweep), "clockwise": clockwise,
            "air_displacement_m": {"east": ae, "north": an},
            "wind_drift_m": {"east": drift_e, "north": drift_n},
            "ground_displacement_m": {"east": ae + drift_e, "north": an + drift_n},
            "exit_ground_speed_mps": exit_speed,
            "exit_ground_heading_deg": ground_heading,
            "mode": "fw", "ground_fixed_orbit": False,
            "scope": "uniform_wind_air_relative_allowance_not_executable_route"}


def wind_arc_estimate(v, v_air, angle_deg, wind, entry_heading_deg,
                      clockwise=True, bank_deg=None, radius_m=None):
    """0..360-degree air-heading sweep; airspeed is NOT ground speed.

    A signed bank input supplies a magnitude only; clockwise controls direction.
    Existing turn geometry supplies the bank-adjusted speed/radius constraints.
    """
    from .energy import turn_geometry
    number(v_air, "v_air", 1e-9)
    number(angle_deg, "angle_deg", 0, 360)
    geometry = turn_geometry(v, v_air, bank_deg, radius_m)
    if geometry["radius_m"] is None:
        raise ValueError("wind arc/loiter requires a nonzero bank")
    duration = geometry["radius_m"] * math.radians(angle_deg) / v_air
    return _estimate(v, v_air, duration, wind, entry_heading_deg, clockwise, geometry)


def wind_loiter_estimate(v, v_air, duration_s, wind, entry_heading_deg,
                         clockwise=True, radius_m=None):
    """0..86400 s air-relative orbit allowance, including partial revolutions.

    Requires an explicit entry air heading; output gives the resulting exit air
    and ground headings. No desired exit heading/ground station hold is inferred.
    Hybrid callers must already be in FW mode; no transition is added here.
    """
    from .energy import turn_geometry
    number(v_air, "v_air", 1e-9)
    number(duration_s, "duration_s", 0, 86400)
    geometry = turn_geometry(v, v_air, radius_m=radius_m)
    return _estimate(v, v_air, duration_s, wind, entry_heading_deg, clockwise, geometry)
