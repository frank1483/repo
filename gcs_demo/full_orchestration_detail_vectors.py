"""NEW full-caller detail vectors; no existing test entrypoint is imported/run."""
import copy
import json
import sys
from dataclasses import replace

from .energy import load_airframe
from .alerts.typed_full_orchestration import TypedFullMissionOrchestrator

CONTRACT = "typed_full_orchestration_detail_P1_comparison_P2_bounds_v1"
NAMES = ("safe_detail", "risk_alternative", "uncertain_multi", "p1_unsupported",
         "p2_unsupported", "hybrid_detail", "version_detail", "endpoint_unknown")


def vehicle(name, uncertain):
    v = load_airframe(name)
    p = copy.deepcopy(v.airframe_profile)
    p["uncertainty"] = {"power_pct": 10 if uncertain else 0,
                        "capacity_pct": 5 if uncertain else 0,
                        "wind_mps": 1 if uncertain else 0}
    return replace(v, battery_wh=100, airframe_profile=p)


def step(i, name):
    pose = {"lat": 23, "lon": 120, "alt": 80, "air_heading_deg": 0}
    arc = {"kind": "arc", "v_air": 16, "angle_deg": 180,
           "clockwise": True, "radius_m": 40}
    candidate = {"id": "current", "entry": pose,
                 "events": [copy.deepcopy(arc) for _ in range(4)], "mode": "fw"}
    probe = {"id": "A", "outbound_events": [copy.deepcopy(arc)],
             "return_events": [copy.deepcopy(arc)]}
    pct = 20.5 if name == "risk_alternative" else 90
    used = 5 * i
    m = {"mission": {"t_s": i, **pose, "battery_pct": pct,
                     "wind_mps": 0, "wind_from": 0, "mode": "fw"},
         "capacity": {"t_s": i, "battery_id": "battery:one", "used_wh": used,
                      "voltage": (4.2 - 0.65 / 80 * used - 5 * 0.004) * 4,
                      "current_a": 5, "cell_count": 4, "battery_pct": pct},
         "link": {"t_s": i, "distance_m": i * 100, "link_pct": 90 - i * 10},
         "wind": {"t_s": i, "wind_mps": 0}}
    r = {"capacity_session_id": "session:one", "mission": {
        "mission_version": "v2" if name == "version_detail" and i == 3 else "v1",
        "recovery_reference_id": "site:home", "p1": {
            "current_id": "current", "candidates": [candidate]}, "p2": {
            "target": {"lat": 23, "lon": 120, "alt": 80, "tolerance_m": 0.001},
            "probes": [probe], "mode": "fw"}},
        "link": {"reference_id": "radio:home", "probes": [
            {"id": "probe:A", "distance_m": 200, "eta_s": 10}]}}
    if name in ("risk_alternative", "uncertain_multi"):
        alternative = copy.deepcopy(candidate)
        alternative.update(id="alternative", events=[copy.deepcopy(arc)])
        r["mission"]["p1"]["candidates"].append(alternative)
    if name == "uncertain_multi":
        # Strictly extending outbound prefix; each return completes a circle.
        r["mission"]["p2"]["probes"].append({"id": "B",
            "outbound_events": [copy.deepcopy(arc) for _ in range(3)],
            "return_events": [copy.deepcopy(arc)]})
    if name == "p1_unsupported":
        candidate["events"] = [copy.deepcopy(arc), {"kind": "landing"}]
    if name == "p2_unsupported":
        probe["return_events"] = [{"kind": "landing"}]
    if name == "endpoint_unknown":
        r["mission"]["p2"]["target"]["lat"] += 0.001
    return {"sequence": i, "measurement": m, "request": r}


def vectors():
    cases = []
    for name in NAMES:
        airframe = "vtol_example" if name == "hybrid_detail" else "fw_example"
        uncertain = name == "uncertain_multi"
        f = TypedFullMissionOrchestrator(vehicle(airframe, uncertain),
            {"cell_r_ohm": 0.004, "cell_empty_v": 3.55, "min_samples": 3},
            "radio:home", {"min_samples": 3, "min_distance_span_m": 100},
            {"min_samples": 3, "min_span_s": 2}, 2, 2, 30, 3)
        steps = [step(i, name) for i in range(4)]
        outputs = [f.tick(s["sequence"], s["measurement"], s["request"]) for s in steps]
        # Full raw output: no P1 comparison, P2 bounds or other field deletion.
        cases.append({"name": name, "airframe": airframe, "uncertain": uncertain,
                      "steps": steps, "outputs": outputs})
    return {"contract": CONTRACT, "cases": cases}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("one NEW output path required")
    data = json.dumps(vectors(), ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with open(sys.argv[1], "x", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
