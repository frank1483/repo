"""NEW synthetic T5b1 checks; first functional execution is assigned to Claude."""
import copy
import math
import unittest
from dataclasses import replace

from .energy import (G, Vehicle, Wind, best_speed, estimate_route_energy, leg_estimate,
                     load_airframe, power_w, route_estimate, rtl_energy,
                     speed_range, transition_estimate)


class AirframeT5b1(unittest.TestCase):
    def setUp(self):
        self.fw = load_airframe("fw_example")
        self.vt = load_airframe("vtol_example")
        self.mc = load_airframe("x500")
        self.a = {"lat": 0.01, "lon": 0, "alt": 60}
        self.h = {"lat": 0, "lon": 0, "alt": 0}

    def leg(self, v, alt=60, w=None, mode=None):
        return leg_estimate(v, (0, 0), (.01, 0), 60, alt, 16, w or Wind(), mode)

    def test_fw_level_uses_fw_power_and_horizontal_time(self):
        e = self.leg(self.fw)
        self.assertAlmostEqual(e["energy_wh"], power_w(self.fw, 16) * e["time_s"] / 3600)
        self.assertAlmostEqual(e["time_s"], e["dist_m"] / 16)

    def test_fw_climb_adds_mechanical_energy_once(self):
        level, climb = self.leg(self.fw), self.leg(self.fw, 90)
        expect = self.fw.mass_kg * G * 30 / self.fw.airframe_profile["power"]["eta_prop"] / 3600
        self.assertAlmostEqual(climb["energy_wh"] - level["energy_wh"], expect)
        self.assertEqual(level["time_s"], climb["time_s"])

    def test_fw_descent_has_no_regeneration(self):
        self.assertEqual(self.leg(self.fw)["energy_wh"], self.leg(self.fw, 0)["energy_wh"])

    def test_fw_zero_distance_is_rejected(self):
        with self.assertRaises(ValueError):
            leg_estimate(self.fw, (0, 0), (0, 0), 60, 0, 16, Wind())

    def test_wind_ground_speed_is_not_airspeed(self):
        e = self.leg(self.fw, w=Wind(3, 0))
        self.assertAlmostEqual(e["v_air"], 19)
        self.assertAlmostEqual(e["headwind_mps"], 3)

    def test_ground_speed_under_stall_rejected(self):
        with self.assertRaises(ValueError):
            leg_estimate(self.fw, (0, 0), (.01, 0), 0, 0, 4, Wind())

    def test_hybrid_leg_requires_explicit_mode(self):
        with self.assertRaises(ValueError):
            self.leg(self.vt)
        self.assertEqual(self.leg(self.vt, mode="fw")["mode"], "fw")
        self.assertEqual(self.leg(self.vt, mode="mc")["mode"], "mc")

    def test_hybrid_vertical_mc_accounts_for_wind(self):
        w = Wind(3, 70)
        e = leg_estimate(self.vt, (0, 0), (0, 0), 60, 0, 16, w, "mc")
        self.assertEqual(e["time_s"], 30)
        self.assertAlmostEqual(e["energy_wh"], power_w(self.vt, 3, "mc") * 30 / 3600)

    def test_hybrid_mc_vertical_climb_energy(self):
        e = leg_estimate(self.vt, (0, 0), (0, 0), 0, 30, 16, Wind(), "mc")
        eta = self.vt.airframe_profile["power"]["mc"]["eta"]
        self.assertAlmostEqual(e["energy_wh"], (power_w(self.vt, 0, "mc") * 10 + self.vt.mass_kg * G * 30 / eta) / 3600)

    def test_transition_both_directions_and_noop(self):
        for a, b in (("mc", "fw"), ("fw", "mc")):
            t = transition_estimate(self.vt, a, b)
            self.assertEqual(t["energy_wh"], self.vt.airframe_profile["transition"]["to_" + b + "_wh"])
            self.assertEqual(t["dist_m"], 100 if b == "fw" else 0)
        for mode in ("mc", "fw"):
            self.assertEqual(transition_estimate(self.vt, mode, mode)["energy_wh"], 0)

    def test_transition_errors(self):
        for v, a, b in ((self.fw, "fw", "mc"), (self.mc, "mc", "fw"), (self.vt, "unknown", "fw")):
            with self.assertRaises(ValueError):
                transition_estimate(v, a, b)

    def test_rtl_default_hybrid_adds_to_mc_once(self):
        e = rtl_energy(self.a, self.h, self.vt, Wind())
        self.assertEqual(len(e["legs"]), 3)
        self.assertEqual(sum(x.get("to_mode") == "mc" for x in e["legs"]), 1)
        self.assertEqual(e["arrival_mode"], "mc")
        self.assertAlmostEqual(e["energy_wh"], sum(x["energy_wh"] for x in e["legs"]))
        self.assertAlmostEqual(e["used_pct"], e["energy_wh"] / 162 * 100)

    def test_rtl_at_home_still_includes_transition(self):
        pos = dict(self.h, alt=60)
        e = rtl_energy(pos, self.h, self.vt, Wind())
        self.assertEqual(len(e["legs"]), 2)
        self.assertEqual(e["legs"][0]["to_mode"], "mc")

    def test_rtl_mc_mode_has_no_transition(self):
        e = rtl_energy(self.a, self.h, self.vt, Wind(), mode="mc")
        self.assertEqual(len(e["legs"]), 1)
        self.assertTrue(e["landing_modeled"])

    def test_fw_rtl_reports_airborne_arrival(self):
        e = rtl_energy(self.a, self.h, self.fw, Wind())
        self.assertEqual(e["arrival_mode"], "fw")
        self.assertFalse(e["landing_modeled"])
        self.assertEqual(e["legs"][0], self.leg(self.fw))  # same distance reversed, zero wind

    def test_calib_applied_once_to_each_component(self):
        e = rtl_energy(self.a, self.h, self.vt, Wind())
        v = replace(self.vt, calib=1.7)
        f = rtl_energy(self.a, self.h, v, Wind())
        self.assertAlmostEqual(f["energy_wh"], e["energy_wh"] * 1.7)
        self.assertAlmostEqual(transition_estimate(v, "fw", "mc")["energy_wh"], 1.5 * 1.7)

    def test_best_speed_uses_envelope_and_wind_triangle(self):
        w = Wind(4, 90)
        best = best_speed(self.fw, w)
        lower, upper = speed_range(self.fw)
        self.assertTrue(lower <= best["airspeed_mps"] <= upper)
        self.assertAlmostEqual(math.hypot(best["speed_mps"], 4), best["airspeed_mps"])
        e = leg_estimate(self.fw, (0, 0), (.01, 0), 0, 0, best["speed_mps"], w)
        self.assertAlmostEqual(round(e["energy_wh"] / e["dist_m"] * 1000, 2), best["wh_per_km"])

    def test_best_speed_rejects_empty_interval_and_overpowering_wind(self):
        for kw in ({"lo": 100}, {"hi": 1}, {"wind": Wind(40, 90)}):
            kw = dict(kw)
            w = kw.pop("wind", Wind())
            with self.assertRaises(ValueError):
                best_speed(self.fw, w, **kw)

    def test_best_hybrid_defaults_to_fw(self):
        e = best_speed(self.vt, Wind())
        self.assertGreaterEqual(e["airspeed_mps"], speed_range(self.vt)[0])

    def test_rtl_does_not_mutate_inputs(self):
        before = copy.deepcopy((self.a, self.h, self.vt.to_dict()))
        rtl_energy(self.a, self.h, self.vt, Wind())
        self.assertEqual(before, (self.a, self.h, self.vt.to_dict()))

    def test_invalid_new_inputs_rejected(self):
        for speed in (0, -1, True, float("nan")):
            with self.assertRaises(ValueError):
                leg_estimate(self.fw, (0, 0), (.01, 0), 0, 0, speed, Wind())
        for kw in ({"pos": dict(self.a, alt=-1)}, {"home": dict(self.h, alt=10)}, {"wind": Wind(-1, 0)}):
            args = {"pos": self.a, "home": self.h, "vehicle": self.vt, "wind": Wind(), **kw}
            with self.assertRaises(ValueError):
                rtl_energy(**args)

    def test_legacy_mc_rtl_and_route_stay_equal(self):
        legacy = Vehicle()
        points = [dict(self.a, id="a"), dict(self.h, id="h")]
        for w in (Wind(), Wind(3, 80)):
            self.assertEqual(rtl_energy(self.a, self.h, self.mc, w), rtl_energy(self.a, self.h, legacy, w))
            self.assertEqual(route_estimate(self.mc, points, 8, w), route_estimate(legacy, points, 8, w))

    def test_complete_typed_route_remains_gated(self):
        points = [self.a, self.h]
        for v in (self.fw, self.vt):
            with self.assertRaises(NotImplementedError):
                estimate_route_energy(points, v, Wind())


if __name__ == "__main__":
    unittest.main()
