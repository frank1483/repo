"""NEW synthetic engineering controls; Claude owns first functional execution."""
import copy
import json
import math
import sys
import unittest
from dataclasses import replace

from .energy import Wind, load_airframe, power_w, wind_route_estimate


ENTRY = {"east_m": 0, "north_m": 0, "air_heading_deg": 0}


def events(wind_speed=0, loiter=False, clockwise=True):
    duration = 40 * math.pi / 2 / 16
    first = {"kind": "loiter" if loiter else "arc", "v_air": 16,
             "clockwise": clockwise, "radius_m": 40}
    first.update({"duration_s": duration} if loiter else {"angle_deg": 90})
    direction = 1 if clockwise else -1
    return [first, {"kind": "straight", "east_m": direction * 40 + wind_speed * duration + (direction * 16 + wind_speed) * 10,
                    "north_m": 40, "ground_mps": abs(direction * 16 + wind_speed)}]


def vectors():
    v = load_airframe("fw_example")
    rows = []
    for speed, loiter, clockwise in [(0, False, True), (5, False, True), (3, True, True), (2, False, False)]:
        ev = events(speed, loiter, clockwise)
        rows.append({"entry": ENTRY, "events": ev, "wind": {"speed_mps": speed, "from_deg": 270},
                     "result": wind_route_estimate(v, ENTRY, ev, Wind(speed, 270))})
    return rows


class TestWindRoute(unittest.TestCase):
    def setUp(self):
        self.v = load_airframe("fw_example")

    def run_route(self, ev=None, wind=None, entry=None, **kwargs):
        return wind_route_estimate(self.v, ENTRY if entry is None else entry,
                                   events() if ev is None else ev, wind or Wind(), **kwargs)

    def near(self, a, b):
        self.assertAlmostEqual(a, b, delta=1e-9 * max(1, abs(a), abs(b)))

    def test_quarter_arc_join_independent_energy(self):
        r = self.run_route()
        t = 40 * math.pi / 2 / 16
        bank = math.degrees(math.atan(16 ** 2 / (9.81 * 40)))
        expected = (power_w(self.v, 16, "fw", bank) * t + power_w(self.v, 16, "fw") * 10) / 3600
        self.near(r["energy_wh"], expected)
        self.near(r["time_s"], t + 10)
        self.near(r["exit_local_m"]["east_m"], 200)
        self.near(r["exit_local_m"]["north_m"], 40)
        self.near(r["straight_dist_m"], 160)
        self.near(r["air_dist_m"], 40 * math.pi / 2 + 160)

    def test_drifted_exit_drives_straight_origin(self):
        r = self.run_route(events(5), Wind(5, 270))
        t = 40 * math.pi / 2 / 16
        self.near(r["legs"][1]["entry_local_m"]["east_m"], 40 + 5 * t)
        self.near(r["straight_dist_m"], 210)
        self.near(r["exit_ground_speed_mps"], 21)
        self.near(r["energy_wh"], self.run_route()["energy_wh"])

    def test_partial_loiter_can_depart_tangentially(self):
        a, b = self.run_route(events(3), Wind(3, 270)), self.run_route(events(3, True), Wind(3, 270))
        self.near(a["energy_wh"], b["energy_wh"])
        self.near(a["exit_local_m"]["east_m"], b["exit_local_m"]["east_m"])

    def test_left_turn_with_tailwind_vector(self):
        r = self.run_route(events(2, clockwise=False), Wind(2, 270))
        self.near(r["exit_air_heading_deg"], 270)
        self.near(r["exit_ground_speed_mps"], 14)

    def test_crosswind_air_heading_not_ground_heading(self):
        # End air velocity east=16; northward wind=5. Ground heading differs.
        t = 40 * math.pi / 2 / 16
        ev = [events()[0], {"kind": "straight", "east_m": 200, "north_m": 40 + 5 * t + 50,
                           "ground_mps": math.hypot(16, 5)}]
        r = self.run_route(ev, Wind(5, 180))
        self.near(r["exit_air_heading_deg"], 90)
        self.assertGreater(abs(r["exit_ground_heading_deg"] - 90), 1)
        self.near(r["legs"][1]["time_s"], 10)

    def test_nontangent_target_rejected(self):
        ev = events(); ev[1]["north_m"] += 20
        with self.assertRaisesRegex(ValueError, "not tangent"):
            self.run_route(ev)

    def test_speed_jump_rejected(self):
        ev = events(); ev[1]["ground_mps"] = 17
        with self.assertRaisesRegex(ValueError, "airspeed discontinuity"):
            self.run_route(ev)

    def test_consecutive_arcs_propagate_pose_heading(self):
        r = self.run_route([events()[0], events()[0]])
        self.near(r["exit_air_heading_deg"], 180)
        self.near(r["exit_local_m"]["east_m"], 80)
        self.near(r["exit_local_m"]["north_m"], 0)

    def test_translated_frame_same_energy(self):
        ev = events(); ev[1]["east_m"] += 100; ev[1]["north_m"] -= 70
        r = self.run_route(ev, entry={"east_m": 100, "north_m": -70, "air_heading_deg": 360})
        self.near(r["energy_wh"], self.run_route()["energy_wh"])
        self.near(r["exit_local_m"]["east_m"], 300)

    def test_single_straight_and_no_inferred_turn(self):
        r = self.run_route([{"kind": "straight", "east_m": 0, "north_m": 160, "ground_mps": 16}])
        self.near(r["time_s"], 10)
        self.assertEqual(len(r["legs"]), 1)

    def test_airspeed_heading_wrap_tolerance(self):
        r = self.run_route([{"kind": "straight", "east_m": 0, "north_m": 160, "ground_mps": 16}],
                           entry={**ENTRY, "air_heading_deg": -1e-8})
        self.near(r["exit_air_heading_deg"], 0)

    def test_fw_hybrid_mode_explicit_mc_rejected(self):
        h = load_airframe("vtol_example")
        self.assertEqual(wind_route_estimate(h, ENTRY, events(), Wind(), mode="fw")["arrival_mode"], "fw")
        for vehicle, mode in [(h, None), (h, "mc"), (load_airframe("x500"), None)]:
            with self.assertRaises(ValueError):
                wind_route_estimate(vehicle, ENTRY, events(), Wind(), mode=mode)

    def test_no_landing_feasibility_claim_and_reserve(self):
        r = self.run_route(start_pct=0)
        self.assertFalse(r["energy_feasible"])
        self.assertFalse(r["feasible"])
        self.assertFalse(r["landing_modeled"])
        self.assertNotIn("dist_m", r)

    def test_calibration_once_and_immutable_inputs(self):
        ev, entry, w = events(3), dict(ENTRY), Wind(3, 270)
        before = copy.deepcopy((self.v, ev, entry, w))
        a = wind_route_estimate(self.v, entry, ev, w)
        b = wind_route_estimate(replace(self.v, calib=1.3), entry, ev, w)
        self.near(b["energy_wh"], a["energy_wh"] * 1.3)
        self.assertEqual((self.v, ev, entry, w), before)

    def test_strict_fields_types_and_envelopes(self):
        for ev in [[], [{}], [{"kind": "unknown"}], [{**events()[0], "alt": 10}],
                   [{**events()[0], "clockwise": None}], [{**events()[0], "v_air": 1}],
                   [{"kind": "straight", "east_m": 0, "north_m": 0, "ground_mps": 16}],
                   [{"kind": "straight", "east_m": True, "north_m": 160, "ground_mps": 16}]]:
            with self.assertRaises(ValueError):
                self.run_route(ev)
        with self.assertRaises(ValueError):
            self.run_route(entry={**ENTRY, "lat": 0})
        with self.assertRaises(ValueError):
            self.run_route(wind=Wind(-1, 0))


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False, sort_keys=True))
    else:
        unittest.main()
