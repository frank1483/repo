"""NEW synthetic Python/JS parity values; run once by Claude."""
import json
from .energy import Wind, load_airframe, loiter_estimate, route_estimate, turn_estimate
from .test_airframe_t5b2a import corner, hybrid_events


def rows():
    fw, vt = load_airframe("fw_example"), load_airframe("vtol_example")
    out = []
    for v in (fw, vt):
        for angle in (0, 90, 180):
            out.append(turn_estimate(v, 16, angle, Wind()))
        out.append(loiter_estimate(v, 16, 60, Wind(), mode="fw"))
    out.append(route_estimate(fw, corner(), 16, Wind()))
    out.append(route_estimate(fw, corner()[:2], 16, Wind(3, 0)))
    out.append(route_estimate(vt, hybrid_events(), 16, Wind()))
    out.append(route_estimate(vt, hybrid_events(False), 16, Wind()))
    out.append(loiter_estimate(vt, 16, 30, Wind(3, 20), mode="mc"))
    return out


if __name__ == "__main__":
    print(json.dumps(rows(), ensure_ascii=False, allow_nan=False))
