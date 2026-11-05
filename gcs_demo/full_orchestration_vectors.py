"""New full-caller vectors only; never selects any prior passed test suite."""
import copy
import json
import sys

from .alerts.typed_full_orchestration import TypedFullMissionOrchestrator
from .test_typed_full_orchestration import full_measurement, full_request, LINK_OPTIONS, WIND_OPTIONS
from .test_typed_orchestration import vehicle, options, summary


def vectors():
    cases = []
    names = ("normal", "p4_reject", "envelope_reject", "time_reject", "wind_reject",
             "reference_reject", "session_reject", "version", "session_version",
             "gap", "unsupported_probe", "unsupported_return", "hybrid")
    for name in names:
        steps = [{"sequence": i, "measurement": full_measurement(i),
                  "request": full_request(), "expect_error": False} for i in range(4)]
        final = {"sequence": 4, "measurement": full_measurement(4),
                 "request": full_request(), "expect_error": False}
        if name.endswith("_reject"):
            bad = copy.deepcopy(final)
            bad["expect_error"] = True
            if name == "p4_reject":
                bad["measurement"]["link"]["link_pct"] = 101
            elif name == "envelope_reject":
                bad["measurement"]["unexpected"] = 1
            elif name == "time_reject":
                bad["measurement"]["wind"]["t_s"] = 5
            elif name == "wind_reject":
                bad["measurement"]["wind"]["wind_mps"] = 5
            elif name == "reference_reject":
                bad["request"]["link"]["reference_id"] = "radio:other"
            else:
                bad["request"]["capacity_session_id"] = "session:two"
            steps.append(bad)
        elif name in ("version", "session_version"):
            final["request"]["mission"]["mission_version"] = "v2"
            if name == "session_version":
                final["request"]["capacity_session_id"] = "session:two"
                final["measurement"]["capacity"]["battery_id"] = "battery:two"
        elif name == "gap":
            for member in final["measurement"].values():
                member["t_s"] = 35
        elif name == "unsupported_probe":
            final["request"]["link"]["probes"][0]["distance_m"] = 9999
        elif name == "unsupported_return":
            final["request"]["mission"]["p2"]["probes"][0]["return_events"] = [{"kind": "landing"}]
        steps.append(final)
        airframe = "vtol_example" if name == "hybrid" else "fw_example"
        f = TypedFullMissionOrchestrator(vehicle(airframe), options(), "radio:home",
                                        LINK_OPTIONS, WIND_OPTIONS, 2, 2, 30, 3)
        outputs = []
        for step in steps:
            try:
                out = f.tick(step["sequence"], step["measurement"], step["request"])
            except ValueError:
                if not step["expect_error"]:
                    raise
                outputs.append({"error": True})
            else:
                if step["expect_error"]:
                    raise AssertionError("expected refusal: " + name)
                outputs.append({"output": summary(out)})
        cases.append({"name": name, "airframe": airframe, "steps": steps, "outputs": outputs})
    return {"contract": "typed_full_orchestration_P1_P5_v1", "cases": cases}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("one NEW output path required")
    # Compute first; exclusive create prevents replacing earlier evidence.
    data = json.dumps(vectors(), ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with open(sys.argv[1], "x", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
