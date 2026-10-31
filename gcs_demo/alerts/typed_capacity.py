"""Finite-window P3 hypothesis, not measured capacity or an energy correction.

Caller supplies chemistry/resistance assumptions and one discharging battery
session. No implicit cell chemistry, hardware, action, history or P1/P2 wiring.
"""
from __future__ import annotations

from ..airframe_route import number
from ..geographic_alerts import _snapshot
from .typed_geographic import _integer
from .typed_link import _identity
from .typed_return import _keys


def typed_battery_capacity_snapshot(vehicle, samples, options):
    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("typed capacity requires explicit FW/hybrid profile")
    nominal = number(vehicle.battery_wh, "battery_wh", 1e-6, 1e9)
    defaults = {"min_samples": 90, "min_energy_span_fraction": 0.08,
                "min_r2": 0.8, "max_gap_s": 30.0,
                "min_fall_v_per_wh": 1e-6, "capacity_ratio_limit": 0.9,
                "soc_gap_limit_pct": 3.0}
    if not isinstance(options, dict) or not {"cell_r_ohm", "cell_empty_v"} <= set(options) or set(options) - set(defaults) - {"cell_r_ohm", "cell_empty_v"}:
        raise ValueError("explicit cell_r_ohm and cell_empty_v required; unsupported option")
    cfg = _snapshot({**defaults, **options})
    _integer(cfg["min_samples"], "min_samples", 3, 601)
    for key, low, high in (("cell_r_ohm", 0, 1), ("cell_empty_v", 0.1, 10),
                           ("min_energy_span_fraction", 1e-6, 1), ("min_r2", 0, 1),
                           ("max_gap_s", 1e-6, 86400), ("min_fall_v_per_wh", 1e-12, 10),
                           ("capacity_ratio_limit", 1e-6, 1), ("soc_gap_limit_pct", 0, 100)):
        number(cfg[key], key, low, high)
    rows = _snapshot(samples)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 601:
        raise ValueError("capacity requires 1..601 ordered samples")
    fields = ("t_s", "battery_id", "used_wh", "voltage", "current_a", "cell_count", "battery_pct")
    gap = False
    volts = []
    for i, row in enumerate(rows):
        _keys(row, fields, "capacity sample")
        _identity(row["battery_id"], "battery_id")
        _integer(row["cell_count"], "cell_count", 1, 100)
        for key, low, high in (("t_s", 0, 9007199254740991), ("used_wh", 0, 1e9),
                               ("voltage", 1e-6, 1000), ("current_a", 0, 10000),
                               ("battery_pct", 0, 100)):
            number(row[key], key, low, high)
        if row["battery_id"] != rows[0]["battery_id"] or row["cell_count"] != rows[0]["cell_count"]:
            raise ValueError("mixed battery/cell identity; supply one explicit battery session")
        if i:
            if row["t_s"] <= rows[i-1]["t_s"] or row["used_wh"] < rows[i-1]["used_wh"]:
                raise ValueError("strictly increasing time and nondecreasing used_wh required")
            gap = gap or row["t_s"] - rows[i-1]["t_s"] > cfg["max_gap_s"]
        volts.append(number(row["voltage"] / row["cell_count"] + row["current_a"] * cfg["cell_r_ohm"], "compensated cell voltage", 0.1, 10))
    latest = rows[-1]
    out = {"predictor": "P3", "status": "unknown", "reason": "insufficient_samples", "risk": None,
           "battery_id": latest["battery_id"], "cell_count": latest["cell_count"],
           "sample_count": len(rows), "energy_span_wh": latest["used_wh"] - rows[0]["used_wh"],
           "nominal_wh": nominal, "compensated_cell_v": volts[-1],
           "slope_v_per_wh": None, "r2": None, "estimated_total_wh": None,
           "capacity_ratio": None, "estimated_remaining_wh": None,
           "soc_remaining_wh": latest["battery_pct"] / 100 * nominal,
           "conservative_remaining_wh": None, "soc_overestimate_pct": None,
           "assumptions": cfg, "measured_capacity": False, "sensor_validated": False,
           "probability_interval": False, "energy_correction_applied": False,
           "feasible": False, "executable": False, "candidates": [], "rule_choice": None}
    if gap:
        out["reason"] = "telemetry_gap"
        return _snapshot(out)
    if len(rows) < cfg["min_samples"]:
        return _snapshot(out)
    if out["energy_span_wh"] < nominal * cfg["min_energy_span_fraction"]:
        out["reason"] = "insufficient_energy_span"
        return _snapshot(out)
    xs = [r["used_wh"] - rows[0]["used_wh"] for r in rows]
    mx, my = sum(xs) / len(xs), sum(volts) / len(volts)
    sxx = sum((x - mx)**2 for x in xs)
    syy = sum((y - my)**2 for y in volts)
    sxy = sum((x - mx)*(y - my) for x, y in zip(xs, volts))
    if sxx <= 1e-12 or syy <= 1e-12:
        out["reason"] = "degenerate_fit"
        return _snapshot(out)
    slope = number(sxy / sxx, "capacity slope")
    r2 = max(0.0, min(1.0, sxy*sxy / (sxx*syy)))
    out.update(slope_v_per_wh=slope, r2=r2)
    if slope >= -cfg["min_fall_v_per_wh"] or r2 < cfg["min_r2"]:
        out["reason"] = "capacity_fit_unreliable"
        return _snapshot(out)
    total = number(rows[0]["used_wh"] + (cfg["cell_empty_v"] - (my - slope*mx)) / slope, "estimated total Wh")
    if total <= latest["used_wh"]:
        out["reason"] = "extrapolated_empty_reached"
        return _snapshot(out)
    remaining = total - latest["used_wh"]
    conservative = min(out["soc_remaining_wh"], remaining)
    gap_pct = (out["soc_remaining_wh"] - conservative) / nominal * 100
    risk = total / nominal < cfg["capacity_ratio_limit"] and gap_pct > cfg["soc_gap_limit_pct"]
    out.update(status="ok", reason="conditional_capacity_risk" if risk else "conditional_capacity_no_risk",
               risk=risk, estimated_total_wh=total, capacity_ratio=total/nominal,
               estimated_remaining_wh=remaining, conservative_remaining_wh=conservative,
               soc_overestimate_pct=gap_pct)
    return _snapshot(out)
