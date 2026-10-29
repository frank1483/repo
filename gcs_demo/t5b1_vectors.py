"""NEW synthetic Python outputs for a separate JS parity check. No datasets."""
import json
from .energy import (Wind, best_speed, leg_estimate, load_airframe,
                     rtl_energy, transition_estimate)


def main():
    a, h = {"lat": .01, "lon": 0, "alt": 60}, {"lat": 0, "lon": 0, "alt": 0}
    fw, vt = load_airframe("fw_example"), load_airframe("vtol_example")
    out = []
    for v in (fw, vt):
        for w in (Wind(), Wind(3, 0), Wind(4, 90)):
            out.append(leg_estimate(v, (0, 0), (.01, 0), 60, 75, 16, w,
                                    "fw" if v.type == "vtol_hybrid" else None))
            out.append(rtl_energy(a, h, v, w))
            out.append(best_speed(v, w))
    out.append(rtl_energy(a, h, vt, Wind(3, 70), mode="mc"))
    out.append(transition_estimate(vt, "mc", "fw"))
    print(json.dumps(out, allow_nan=False))


if __name__ == "__main__":
    main()
