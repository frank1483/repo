"""Finite explicit P2 probes, not a continuous point-of-no-return solver.

Replay each outbound+return in ONE fixed geographic frame and ONE wind per
scenario. No connectors, turns, return, home identity or landing are inferred.
"""
from __future__ import annotations

import math

from ..airframe_route import flight_mode, number, wind_values
from ..geographic_alerts import _snapshot, geographic_wind_route_bounds


def _keys(obj, keys, name):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError(name + " requires exactly " + ", ".join(keys))


def _equal(a, b):
    # Match JSON/JS equality: booleans are not the numeric values 0 and 1.
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return False
    return a == b


def _request(entry, target, probes):
    request = _snapshot({"entry": entry, "target": target, "probes": probes})
    entry, target, probes = (request[k] for k in ("entry", "target", "probes"))
    _keys(entry, ("lat", "lon", "alt", "air_heading_deg"), "entry")
    _keys(target, ("lat", "lon", "alt", "tolerance_m"), "recovery target")
    for name, point in (("entry", entry), ("target", target)):
        number(point["lat"], name + " lat", -75, 75)
        number(point["lon"], name + " lon", -180, 180)
        number(point["alt"], name + " alt", 0)
    number(entry["air_heading_deg"], "air_heading_deg")
    number(target["tolerance_m"], "tolerance_m", 0, 100)
    if target["alt"] != entry["alt"]:
        raise ValueError("P2 recovery target must be at the entry flight altitude")
    if not isinstance(probes, list) or not 1 <= len(probes) <= 16:
        raise ValueError("P2 requires 1..16 explicit return probes")
    seen, previous, total = set(), [], 0
    for p in probes:
        _keys(p, ("id", "outbound_events", "return_events"), "probe")
        key = p["id"]
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or key in seen:
            raise ValueError("probe id must be unique, nonempty, at most 128 characters")
        seen.add(key)
        out, ret = p["outbound_events"], p["return_events"]
        if any(not isinstance(x, list) or not x for x in (out, ret)):
            raise ValueError("probe requires nonempty outbound and return event lists")
        # Strict event-prefix nesting is the route ordering, not sorting an
        # unverified caller ETA or ranking unrelated alternative missions.
        if len(out) <= len(previous) or not _equal(out[:len(previous)], previous):
            raise ValueError("outbound events must strictly extend the previous prefix")
        if any(not isinstance(e, dict) or not isinstance(e.get("kind"), str) for e in out + ret):
            raise ValueError("probe events require objects with kind")
        total += len(out) + len(ret)
        if total > 1000:
            raise ValueError("P2 batch exceeds 1000 total replayed events")
        previous = out
    return entry, target, probes


def _endpoint_error(pose, target, origin):
    # Exactly the existing adapter's plane, not a geodesic/spherical distance.
    from ..energy import R_EARTH
    metres = math.pi * R_EARTH / 180
    dl = (pose["lon"] - target["lon"] + 180) % 360 - 180
    return math.hypot(dl * metres * math.cos(math.radians(origin["lat"])),
                      (pose["lat"] - target["lat"]) * metres)


def typed_return_probe_snapshot(vehicle, entry, target, probes, wind, start_pct=100.0, mode=None):
    """Report ordered, caller-supplied round-trip samples from one current pose.

    Every probe explicitly extends the same outbound prefix and supplies its
    complete return events. Prefix boundary is BEFORE the first return event.
    The nominal and every finite uncertainty scenario must reach the same
    caller target within its explicit 0..100 m horizontal tolerance, at the
    entry altitude. Arrival is still FW in flight, with no heading/landing
    constraint. Wind-direction uncertainty is not modeled.

    ANY unsupported probe makes the aggregate unknown. Per-probe diagnostic
    evidence remains; there is no partial aggregate boundary. Nonmonotonic
    sampled feasibility is reported without inventing a continuous crossing.
    """
    if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
        raise ValueError("typed return probes require an explicit FW/hybrid profile")
    active = flight_mode(vehicle, mode)
    if active != "fw":
        raise ValueError("typed return probes require explicit FW flight")
    wind_values(wind)
    number(start_pct, "start_pct", 0, 100)
    entry, target, items = _request(entry, target, probes)
    rows = []
    for p in items:
        split = len(p["outbound_events"])
        interval = geographic_wind_route_bounds(vehicle, entry, p["outbound_events"] + p["return_events"],
                                                wind, start_pct, active)
        scenarios = []
        for s in interval["scenarios"]:
            row = {"id": s["id"], "status": s["status"], "endpoint_supported": False,
                   "wind": s["wind"], "power_multiplier": s["power_multiplier"],
                   "capacity_multiplier": s["capacity_multiplier"]}
            if s["status"] == "ok":
                e = s["base_estimate"]
                error = _endpoint_error(e["exit_geographic"], target, entry)
                supported = error <= target["tolerance_m"] and e["exit_geographic"]["alt"] == target["alt"]
                row.update({"endpoint_supported": supported, "endpoint_error_m": error,
                            "exit_geographic": e["exit_geographic"],
                            "probe_geographic": e["legs"][split - 1]["exit_geographic"],
                            "eta_s": sum(leg["time_s"] for leg in e["legs"][:split]),
                            "end_pct": s["end_pct"]})
            else:
                row["reason"] = s["reason"]
            scenarios.append(row)
        known = interval["available"] and all(s["endpoint_supported"] for s in scenarios)
        nominal = scenarios[0]
        rows.append({"id": p["id"], "status": "ok" if known else "unknown",
                     "reason": "finite_probe_supported" if known else "route_or_recovery_endpoint_unsupported",
                     "outbound_event_count": split,
                     "sampled_energy_risk": interval["low_pct"] < vehicle.reserve_pct if known else None,
                     "low_pct": interval["low_pct"] if known else None,
                     "high_pct": interval["high_pct"] if known else None,
                     "nominal_eta_s": nominal.get("eta_s"),
                     "scenarios": scenarios, "bounds": interval})
    known = all(r["status"] == "ok" for r in rows)
    first = last = None
    reentry = False
    if known:
        for r in rows:
            if r["sampled_energy_risk"]:
                if first is None:
                    first = r
            elif first is None:
                last = r
            else:
                reentry = True
    return _snapshot({"scope": "typed_P2_explicit_return_probe_samples_only",
                      "status": "ok" if known else "unknown", "entry": entry, "target": target,
                      "mode": active, "start_pct": start_pct, "reserve_pct": vehicle.reserve_pct,
                      "probes": rows, "sampled_energy_risk": first is not None if known else None,
                      "first_sampled_infeasible_id": first["id"] if first else None,
                      "first_sampled_infeasible_nominal_eta_s": first["nominal_eta_s"] if first else None,
                      "last_sampled_feasible_prefix_id": last["id"] if last else None,
                      "sampled_feasibility_reentry": reentry if known else None,
                      "sampled_endpoint_constraint_met": known,
                      "continuous_boundary_known": False, "return_inferred": False,
                      "recovery_reference_verified": False, "landing_modeled": False,
                      "wind_direction_varied": False, "feasible": False, "executable": False,
                      "candidates": [], "rule_choice": None})
