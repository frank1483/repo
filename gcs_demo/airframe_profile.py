"""T5a profile validation and aerodynamic primitives; no I/O except local JSON reads.

This is an engineering model, not a fitted or flight-validated airframe. Route,
transition and uncertainty integration is deliberately a subsequent patch.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

RHO = 1.225
G = 9.81
TYPES = ("multirotor", "fixed_wing", "vtol_hybrid")
DEFAULT_MC = {"p_hover_w": 190.0, "cda_m2": 0.12, "eta": 0.7}
DEFAULT_BATTERY = {"wh": 90.0, "usable_frac": 0.9, "cell_count": 4,
                   "cell_empty_v": 3.55, "cell_r_ohm": 0.004}
DEFAULT_LIMITS = {"reserve_pct": 20.0, "wind_limit_mps": 12.0,
                  "min_airspeed_mps": 0.0, "max_airspeed_mps": 15.0, "cruise_mps": 8.0}
DEFAULT_UNCERTAINTY = {"power_pct": 10.0, "capacity_pct": 5.0, "wind_mps": 2.0}


def _number(value, name, low=0.0, high=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name}: finite number required")
    if value < low or (positive and value <= low) or (high is not None and value > high):
        raise ValueError(f"{name}: out of range")
    return value


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name}: object required")
    return value


def _mc(power, prefix):
    power = {**DEFAULT_MC, **_object(power, prefix)}
    _number(power["p_hover_w"], prefix + ".p_hover_w", positive=True)
    _number(power["cda_m2"], prefix + ".cda_m2")
    _number(power["eta"], prefix + ".eta", high=1.0, positive=True)
    return power


def _fw(power, prefix):
    power = _object(power, prefix)
    # Missing aerodynamic data must not be silently replaced by another airframe.
    for key in ("wing_area_m2", "cd0", "k_induced", "eta_prop", "p_avionics_w",
                "v_stall_mps", "min_turn_radius_m"):
        if key not in power:
            raise ValueError(f"{prefix}.{key}: required for fixed-wing model")
        _number(power[key], prefix + "." + key,
                high=1.0 if key == "eta_prop" else None,
                positive=key != "p_avionics_w")
    return power


def validate_profile(value):
    """Return an independent normalized copy. Unknown fields survive for provenance."""
    def check_json(x):
        if x is None or isinstance(x, (str, bool)):
            return
        if isinstance(x, (int, float)):
            if not math.isfinite(x):
                raise ValueError("profile: nonfinite JSON number")
        elif isinstance(x, list):
            for item in x:
                check_json(item)
        elif isinstance(x, dict):
            for key, item in x.items():
                if not isinstance(key, str) or key in ("__proto__", "constructor", "prototype"):
                    raise ValueError("profile: non-string or reserved key")
                check_json(item)
        else:
            raise ValueError("profile: only JSON values are accepted")
    check_json(value)
    p = copy.deepcopy(_object(value, "profile"))
    p.setdefault("id", "UAV-01")
    if not isinstance(p["id"], str) or not p["id"].strip():
        raise ValueError("id: nonempty string required")
    p.setdefault("type", "multirotor")
    if p["type"] not in TYPES:
        raise ValueError("type: unsupported airframe")
    p.setdefault("schema", 0)
    if isinstance(p["schema"], bool) or p["schema"] != 0:
        raise ValueError("schema: only version 0 is supported")
    p.setdefault("mass_kg", 2.0)
    p.setdefault("calib", 1.0)
    p.setdefault("source", "assumed")
    if not isinstance(p["source"], str) or not p["source"].strip():
        raise ValueError("source: nonempty string required")
    _number(p["mass_kg"], "mass_kg", positive=True)
    _number(p["calib"], "calib", positive=True)
    for key, defaults in (("battery", DEFAULT_BATTERY), ("limits", DEFAULT_LIMITS),
                          ("uncertainty", DEFAULT_UNCERTAINTY)):
        p[key] = {**defaults, **_object(p.get(key, {}), key)}
    b, l, u = p["battery"], p["limits"], p["uncertainty"]
    _number(b["wh"], "battery.wh", positive=True)
    _number(b["usable_frac"], "battery.usable_frac", high=1.0, positive=True)
    _number(b["cell_count"], "battery.cell_count", positive=True)
    if int(b["cell_count"]) != b["cell_count"]:
        raise ValueError("battery.cell_count: integer required")
    _number(b["cell_empty_v"], "battery.cell_empty_v", positive=True)
    _number(b["cell_r_ohm"], "battery.cell_r_ohm")
    for key in DEFAULT_LIMITS:
        _number(l[key], "limits." + key, high=100.0 if key == "reserve_pct" else None,
                positive=key in ("max_airspeed_mps", "cruise_mps"))
    for key in DEFAULT_UNCERTAINTY:
        _number(u[key], "uncertainty." + key,
                high=100.0 if key.endswith("pct") else None)
    if u["capacity_pct"] >= 100:
        raise ValueError("uncertainty.capacity_pct: must leave positive capacity")
    power = p.get("power", {})
    if p["type"] == "multirotor":
        p["power"] = _mc(power, "power")
    elif p["type"] == "fixed_wing":
        p["power"] = _fw(power, "power")
    else:
        power = _object(power, "power")
        p["power"] = {**power, "mc": _mc(power.get("mc", {}), "power.mc"),
                      "fw": _fw(power.get("fw", {}), "power.fw")}
        transition = _object(p.get("transition", {}), "transition")
        for key in ("to_fw_wh", "to_fw_s", "to_fw_dist_m", "to_mc_wh", "to_mc_s"):
            if key not in transition:
                raise ValueError("transition." + key + ": required for hybrid model")
            _number(transition[key], "transition." + key)
        p["transition"] = transition
    # prop_model is either a provenance identifier, or an identifier with nominal
    # rpm and diameter_m. Actual advance ratio may always be supplied per call.
    prop = p.get("prop_model")
    if prop is not None:
        if isinstance(prop, str):
            if not prop.strip():
                raise ValueError("prop_model: nonempty identifier required")
        else:
            prop = _object(prop, "prop_model")
            if not isinstance(prop.get("id"), str) or not prop["id"].strip():
                raise ValueError("prop_model.id: nonempty string required")
            if ("rpm" in prop) != ("diameter_m" in prop):
                raise ValueError("prop_model: rpm and diameter_m must appear together")
            for key in ("rpm", "diameter_m"):
                if key in prop:
                    _number(prop[key], "prop_model." + key, positive=True)
    if "eta_table" in p:
        table = p["eta_table"]
        if not prop or not isinstance(table, list) or len(table) < 2:
            raise ValueError("eta_table: prop_model and at least two [J, eta] rows required")
        previous = -1.0
        for row in table:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError("eta_table: rows must be [J, eta]")
            j = _number(row[0], "eta_table.J")
            _number(row[1], "eta_table.eta", high=1.0, positive=True)
            if j <= previous:
                raise ValueError("eta_table: J must be strictly increasing")
            previous = j
    lo, hi = profile_speed_range(p)
    if lo > hi or not lo <= l["cruise_mps"] <= hi:
        raise ValueError("limits: cruise and max must satisfy the effective airspeed range")
    return p


def read_profile(path_or_id):
    value = Path(path_or_id)
    if value.parent == Path(".") and value.suffix == "":
        value = Path(__file__).with_name("airframes") / (str(value) + ".json")
    with value.open(encoding="utf-8-sig") as handle:
        return validate_profile(json.load(handle))


def profile_speed_range(profile, bank_deg=0.0):
    l = profile["limits"]
    lo = l["min_airspeed_mps"]
    if profile["type"] != "multirotor":
        f = profile["power"] if profile["type"] == "fixed_wing" else profile["power"]["fw"]
        n = load_factor(bank_deg)
        lo = max(lo, 1.2 * f["v_stall_mps"] * math.sqrt(n))
    return lo, l["max_airspeed_mps"]


def load_factor(bank_deg):
    _number(bank_deg, "bank_deg", low=-90.0, high=90.0)
    if abs(bank_deg) >= 90.0:
        raise ValueError("bank_deg: absolute bank must be less than 90 degrees")
    return 1.0 / math.cos(math.radians(bank_deg))


def prop_efficiency(profile, v_air, fallback, advance_ratio=None):
    """Linear J interpolation; clamp endpoints, never equate speed in m/s with J.

    No table, or no J/rpm+diameter context: constant eta_prop. Table source data
    is intentionally absent from shipped profiles. Nominal RPM is an assumption.
    """
    table = profile.get("eta_table")
    if not table:
        return fallback
    j = advance_ratio
    prop = profile.get("prop_model")
    if j is None and isinstance(prop, dict) and "rpm" in prop:
        j = v_air / (prop["rpm"] / 60.0 * prop["diameter_m"])
    if j is None:
        return fallback
    _number(j, "advance_ratio")
    if j <= table[0][0]:
        return table[0][1]
    for (j0, e0), (j1, e1) in zip(table, table[1:]):
        if j <= j1:
            return e0 + (e1 - e0) * (j - j0) / (j1 - j0)
    return table[-1][1]


def profile_power_w(profile, v_air, mode=None, bank_deg=0.0, climb_mps=0.0,
                    advance_ratio=None, mass_kg=None):
    """Electrical W before calib. Positive climb adds mechanical m*g*rate / eta.

    Hybrid instantaneous power requires an explicit mode, to prevent accidental
    omission of transition energy by a caller assuming a full mission estimate.
    """
    _number(v_air, "v_air")
    _number(climb_mps, "climb_mps", low=-1e100)
    load_factor(bank_deg)  # reject NaN/invalid bank even for mc
    kind = profile["type"]
    if kind == "vtol_hybrid":
        if mode not in ("mc", "fw"):
            raise ValueError("vtol_hybrid power requires explicit mode='mc' or 'fw'")
        p = profile["power"][mode]
    else:
        active = "mc" if kind == "multirotor" else "fw"
        if mode not in (None, active):
            raise ValueError("mode is incompatible with airframe type")
        mode, p = active, profile["power"]
    mass = profile["mass_kg"] if mass_kg is None else mass_kg
    _number(mass, "mass_kg", positive=True)
    climb = mass * G * max(0.0, climb_mps)
    if mode == "mc":
        if bank_deg != 0:
            raise ValueError("multirotor bank compensation is not modeled")
        return p["p_hover_w"] + 0.5 * RHO * p["cda_m2"] * v_air ** 3 / p["eta"] + climb / p["eta"]
    n = load_factor(bank_deg)
    lo, hi = profile_speed_range(profile, bank_deg)
    if v_air < lo or v_air > hi:
        raise ValueError("v_air: outside fixed-wing airspeed/stall envelope")
    eta = prop_efficiency(profile, v_air, p["eta_prop"], advance_ratio)
    drag_power = (0.5 * RHO * v_air ** 3 * p["wing_area_m2"] * p["cd0"]
                  + 2 * p["k_induced"] * (mass * G) ** 2 * n ** 2
                  / (RHO * v_air * p["wing_area_m2"]))
    return (drag_power + climb) / eta + p["p_avionics_w"]


def profile_turn_geometry(profile, v_air, bank_deg=None, radius_m=None):
    """Coordinated-turn primitive. Does not add arcs to a route in T5a."""
    if profile["type"] == "multirotor":
        raise ValueError("turn geometry is defined only for fixed-wing flight")
    p = profile["power"] if profile["type"] == "fixed_wing" else profile["power"]["fw"]
    _number(v_air, "v_air", positive=True)
    if bank_deg is not None and radius_m is not None:
        raise ValueError("specify bank_deg or radius_m, not both")
    if bank_deg is None:
        radius_m = p["min_turn_radius_m"] if radius_m is None else radius_m
        _number(radius_m, "radius_m", positive=True)
        bank_deg = math.degrees(math.atan(v_air ** 2 / (G * radius_m)))
    n = load_factor(bank_deg)
    radius = None if bank_deg == 0 else v_air ** 2 / (G * abs(math.tan(math.radians(bank_deg))))
    if radius is not None and radius < p["min_turn_radius_m"] - 1e-9:
        raise ValueError("turn radius below configured minimum")
    lo, hi = profile_speed_range(profile, bank_deg)
    if not lo <= v_air <= hi:
        raise ValueError("turn exceeds bank-adjusted stall/airspeed envelope")
    return {"bank_deg": bank_deg, "load_factor": n, "radius_m": radius,
            "min_airspeed_mps": lo}
