"""NEW synthetic checks; Claude owns first functional execution."""
import copy
import math
import unittest
from dataclasses import replace

from .energy import (Vehicle, Wind, estimate_route_energy, leg_estimate,
                     load_airframe, loiter_estimate, power_w, route_estimate,
                     turn_estimate)


def hybrid_events(explicit_mc=True):
    rows = [{"id": "H", "lat": 0, "lon": 0, "alt": 0, "kind": "takeoff"},
            {"id": "U", "lat": 0, "lon": 0, "alt": 60, "kind": "takeoff"},
            {"cmd": 3000, "to_mode": "fw"},
            {"id": "A", "lat": .01, "lon": 0, "alt": 60}]
    if explicit_mc:
        rows.append({"cmd": 3000, "to_mode": "mc"})
    rows.append({"id": "L", "lat": .01, "lon": 0, "alt": 0, "kind": "landing"})
    return rows


def corner():
    return [{"id": "A", "lat": 0, "lon": 0, "alt": 60},
            {"id": "B", "lat": .01, "lon": 0, "alt": 60},
            {"id": "C", "lat": .01, "lon": .01, "alt": 60}]


class AirframeT5b2a(unittest.TestCase):
    def setUp(self):
        self.fw = load_airframe("fw_example")
        self.vt = load_airframe("vtol_example")

    def route(self, rows=None, wind=None, v=None, **kw):
        return route_estimate(v or self.fw, rows or corner(), 16, wind or Wind(), **kw)

    def test_arc_radius_length_and_time(self):
        e = turn_estimate(self.fw, 16, 90, Wind())
        self.assertAlmostEqual(e["radius_m"], 40)
        self.assertAlmostEqual(e["dist_m"], 40 * math.pi / 2)
        self.assertAlmostEqual(e["time_s"], e["dist_m"] / 16)

    def test_arc_induced_drag_uses_n_squared(self):
        e = turn_estimate(self.fw, 16, 90, Wind())
        p, v, n = self.fw.airframe_profile["power"], 16, e["load_factor"]
        expected = ((.5 * 1.225 * v**3 * p["wing_area_m2"] * p["cd0"]
                     + 2 * p["k_induced"] * (self.fw.mass_kg * 9.81)**2 * n**2
                     / (1.225 * v * p["wing_area_m2"])) / p["eta_prop"] + p["p_avionics_w"])
        self.assertAlmostEqual(e["energy_wh"], expected * e["time_s"] / 3600)
        self.assertGreater(expected, power_w(self.fw, 16))

    def test_signed_bank_same_power(self):
        a = turn_estimate(self.fw, 16, 90, Wind(), bank_deg=20)
        b = turn_estimate(self.fw, 16, 90, Wind(), bank_deg=-20)
        self.assertAlmostEqual(a["energy_wh"], b["energy_wh"])

    def test_bad_arc_inputs_and_bank_stall(self):
        for angle in (-1, 361, True, float("nan")):
            with self.assertRaises(ValueError):
                turn_estimate(self.fw, 16, angle, Wind())
        for kw in ({"bank_deg": 0}, {"radius_m": 1}, {"bank_deg": 20, "radius_m": 100}):
            with self.assertRaises(ValueError):
                turn_estimate(self.fw, 16, 90, Wind(), **kw)
        with self.assertRaises(ValueError):
            turn_estimate(self.fw, 8.4, 90, Wind(), radius_m=40)

    def test_zero_arc(self):
        self.assertEqual(turn_estimate(self.fw, 16, 0, Wind(), bank_deg=0)["energy_wh"], 0)

    def test_loiter_uses_banked_power(self):
        e = loiter_estimate(self.fw, 16, 60, Wind())
        self.assertEqual(e["dist_m"], 960)
        self.assertAlmostEqual(e["energy_wh"], power_w(self.fw, 16, bank_deg=e["bank_deg"]) / 60)

    def test_mc_hold_has_wind_and_no_orbit(self):
        e = loiter_estimate(self.vt, 16, 30, Wind(3, 20), mode="mc")
        self.assertEqual(e["dist_m"], 0)
        self.assertAlmostEqual(e["energy_wh"], power_w(self.vt, 3, "mc") / 120)
        with self.assertRaises(ValueError):
            loiter_estimate(self.vt, 16, 30, Wind(), radius_m=40, mode="mc")

    def test_windy_arcs_and_loiter_fail_closed(self):
        for f in (lambda: turn_estimate(self.fw, 16, 90, Wind(1, 0)),
                  lambda: loiter_estimate(self.fw, 16, 60, Wind(1, 0)),
                  lambda: self.route(wind=Wind(1, 0))):
            with self.assertRaisesRegex(ValueError, "ground-track"):
                f()

    def test_route_adds_one_corner_and_sums_components(self):
        e = self.route()
        self.assertEqual(len(e["legs"]), 3)
        self.assertEqual(sum(x.get("angle_deg", 0) > 0 for x in e["legs"]), 1)
        for k in ("energy_wh", "time_s", "dist_m"):
            self.assertAlmostEqual(e[k], sum(x[k] for x in e["legs"]))

    def test_collinear_route_has_no_arc(self):
        rows = corner()
        rows[-1].update(lat=.02, lon=0)
        self.assertEqual(len(self.route(rows)["legs"]), 2)

    def test_fw_airborne_is_not_complete_feasible(self):
        e = self.route()
        self.assertTrue(e["energy_feasible"])
        self.assertFalse(e["feasible"])
        self.assertFalse(e["landing_modeled"])

    def test_target_dwell_is_loiter_and_can_be_disabled(self):
        rows = corner()[:2]
        rows[1]["kind"] = "target"
        a, b = self.route(rows), self.route(rows, hover_s_per_wp=0)
        self.assertAlmostEqual(a["time_s"] - b["time_s"], 5)
        self.assertEqual(a["legs"][-1]["scope"], "air_relative_loiter_allowance")

    def test_same_pose_loiter_has_no_zero_distance_fw_leg(self):
        rows = [corner()[0], dict(corner()[0], kind="loiter", loiter_s=30)]
        self.assertEqual(len(self.route(rows)["legs"]), 1)

    def test_fw_departure_after_loiter_requires_exit_heading(self):
        rows = corner()
        rows[1]["loiter_s"] = 5
        with self.assertRaisesRegex(ValueError, "exit-heading"):
            self.route(rows)

    def test_hybrid_modes_transition_counts_and_landing(self):
        e = self.route(hybrid_events(), v=self.vt)
        self.assertEqual([x["to_mode"] for x in e["legs"] if "to_mode" in x], ["fw", "mc"])
        self.assertTrue(e["landing_modeled"])
        self.assertEqual(e["arrival_mode"], "mc")
        self.assertTrue(e["feasible"])
        self.assertEqual(e["transition_allowance_dist_m"], 100)

    def test_implicit_landing_to_mc_exactly_once(self):
        a = self.route(hybrid_events(), v=self.vt)
        b = self.route(hybrid_events(False), v=self.vt)
        self.assertAlmostEqual(a["energy_wh"], b["energy_wh"])
        self.assertEqual(sum(x.get("to_mode") == "mc" for x in b["legs"]), 1)

    def test_transition_distance_not_added_to_flown_distance(self):
        e = self.route(hybrid_events(), v=self.vt)
        straight = leg_estimate(self.vt, (0, 0), (.01, 0), 60, 60, 16, Wind(), "fw")
        self.assertAlmostEqual(e["dist_m"], straight["dist_m"])

    def test_repeated_same_mode_transition_costs_zero(self):
        rows = hybrid_events()
        rows.insert(3, {"cmd": 3000, "to_mode": "fw"})
        self.assertAlmostEqual(self.route(rows, v=self.vt)["energy_wh"], self.route(hybrid_events(), v=self.vt)["energy_wh"])

    def test_hybrid_requires_initial_mode(self):
        with self.assertRaises(ValueError):
            self.route(v=self.vt)
        self.assertEqual(self.route(v=self.vt, mode="fw")["arrival_mode"], "fw")

    def test_cmd_pose_unknown_fields_and_raw_params_rejected(self):
        for event in ({"cmd": 3000, "to_mode": "fw", "lat": 1},
                      {"cmd": 3000, "param1": 4}, {"cmd": 16},
                      {"cmd": True}, {"cmd": 3000, "to_mode": "unknown"}):
            rows = hybrid_events()
            rows[2] = event
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.route(rows, v=self.vt)

    def test_takeoff_landing_and_after_landing_rejected(self):
        for rows in ([corner()[0], dict(corner()[1], kind="landing", alt=0)],
                     [corner()[0], dict(corner()[1], kind="takeoff")]):
            with self.assertRaises(ValueError):
                self.route(rows)
        rows = hybrid_events() + [{"cmd": 3000, "to_mode": "fw"}]
        with self.assertRaises(ValueError):
            self.route(rows, v=self.vt)

    def test_malformed_routes_and_dwell_rejected(self):
        for rows in ([], [corner()[0]], corner()*334,
                     [corner()[0], dict(corner()[1], alt=True)],
                     [corner()[0], dict(corner()[1], kind="loiter")],
                     [corner()[0], dict(corner()[1], mode="mc")]):
            with self.subTest(length=len(rows)), self.assertRaises(ValueError):
                route_estimate(self.fw, rows, 16, Wind())

    def test_calib_once_and_battery_arithmetic(self):
        a = self.route(hybrid_events(), v=self.vt)
        b = self.route(hybrid_events(), v=replace(self.vt, calib=1.7), start_pct=80)
        self.assertAlmostEqual(b["energy_wh"], a["energy_wh"] * 1.7)
        self.assertAlmostEqual(b["end_pct"], 80 - b["energy_wh"] / 162 * 100)

    def test_shared_entry_and_inputs_immutable(self):
        rows = hybrid_events()
        before = copy.deepcopy(rows)
        a = self.route(rows, v=self.vt, hover_s_per_wp=0)
        b = estimate_route_energy(rows, self.vt, Wind(), 16)
        self.assertEqual(a, b)
        self.assertEqual(rows, before)

    def test_legacy_mc_route_equal_to_x500(self):
        rows = corner()
        for w in (Wind(), Wind(3, 20)):
            self.assertEqual(route_estimate(Vehicle(), rows, 8, w),
                             route_estimate(load_airframe("x500"), rows, 8, w))

    def test_windy_straight_fw_route_retains_vector_wind(self):
        rows = corner()[:2]
        e = self.route(rows, wind=Wind(3, 0))
        self.assertAlmostEqual(e["legs"][0]["v_air"], 19)


if __name__ == "__main__":
    unittest.main()
