"""NEW synthetic Python/JS parity vectors; stdout JSON only, no archived input."""
import copy
import json

from .energy import load_airframe, power_w, speed_range, turn_geometry


def vectors():
    result = {"profiles": {}, "power": [], "turns": []}
    for name in ("x500", "fw_example", "vtol_example"):
        v = load_airframe(name)
        result["profiles"][name] = {"vehicle": v.to_dict(), "speed_range": speed_range(v)}
        modes = ("mc", "fw") if v.type == "vtol_hybrid" else (None,)
        for mode in modes:
            speeds = (0, 4, 8, 15) if mode == "mc" or v.type == "multirotor" else (12, 16, 24, 35)
            for s in speeds:
                for climb in (0, 2):
                    result["power"].append({"id": name, "v_air": s, "mode": mode,
                                            "climb_mps": climb, "bank_deg": 0,
                                            "watts": power_w(v, s, mode, climb_mps=climb)})
        if v.type != "multirotor":
            for bank in (0, 20, -20):
                result["power"].append({"id": name, "v_air": 24, "mode": "fw", "climb_mps": 0,
                                        "bank_deg": bank, "watts": power_w(v, 24, "fw", bank_deg=bank)})
            for radius in (40, 100):
                result["turns"].append({"id": name, "v_air": 16, "radius_m": radius,
                                        "result": turn_geometry(v, 16, radius_m=radius)})
    v = load_airframe("fw_example")
    p = copy.deepcopy(v.airframe_profile)
    p.update(prop_model={"id": "synthetic", "rpm": 6000, "diameter_m": .4}, eta_table=[[0, .4], [1, .8]])
    v.airframe_profile = p
    result["prop"] = {"profile": p, "v_air": 16, "watts_nominal_rpm": power_w(v, 16),
                      "watts_actual_j": power_w(v, 16, advance_ratio=.5)}
    return result


if __name__ == "__main__":
    print(json.dumps(vectors(), allow_nan=False, sort_keys=True))
