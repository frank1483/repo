"""New synthetic contracts only. Claude owns first execution."""
import json
import math
import sys
import unittest
from dataclasses import replace

from .energy import (Wind, load_airframe, power_w, route_estimate, turn_estimate,
                     wind_arc_estimate, wind_loiter_estimate)


def vectors():
    v = load_airframe("fw_example")
    rows = []
    for angle, heading, clockwise, speed, source in [
            (90, 0, True, 5, 270), (90, 0, False, 5, 270),
            (360, 37, True, 3, 20), (0, -20, True, 2, 180)]:
        rows.append({"args": [angle, heading, clockwise, speed, source],
                     "result": wind_arc_estimate(v, 16, angle, Wind(speed, source),
                                                 heading, clockwise, radius_m=40)})
    return rows


class WindArc(unittest.TestCase):
    def setUp(self):
        self.v = load_airframe("fw_example")

    def assertDeepNear(self, a, b):
        if isinstance(a, dict):
            self.assertEqual(set(a), set(b))
            for k in a:
                self.assertDeepNear(a[k], b[k])
        elif isinstance(a, float) or isinstance(b, float):
            self.assertTrue(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f"{a} != {b}")
        else:
            self.assertEqual(a, b)

    def arc(self, wind=None, **kw):
        return wind_arc_estimate(self.v, 16, kw.pop("angle", 90),
                                 wind or Wind(), kw.pop("heading", 0),
                                 radius_m=kw.pop("radius", 40), **kw)

    def test_quarter_circle_clockwise(self):
        r = self.arc()
        self.assertAlmostEqual(r["air_displacement_m"]["east"], 40)
        self.assertAlmostEqual(r["air_displacement_m"]["north"], 40)
        self.assertAlmostEqual(r["exit_air_heading_deg"], 90)

    def test_counterclockwise(self):
        r = self.arc(clockwise=False)
        self.assertAlmostEqual(r["ground_displacement_m"]["east"], -40)
        self.assertAlmostEqual(r["ground_displacement_m"]["north"], 40)
        self.assertAlmostEqual(r["exit_air_heading_deg"], 270)
        self.assertLess(r["bank_deg"], 0)

    def test_uniform_wind_drift(self):
        r = self.arc(Wind(5, 270))
        self.assertAlmostEqual(r["ground_displacement_m"]["east"], 40 + 5*r["time_s"])
        self.assertAlmostEqual(r["ground_displacement_m"]["north"], 40)

    def test_calm_power_time_unchanged(self):
        r, old = self.arc(), turn_estimate(self.v, 16, 90, Wind(), radius_m=40)
        self.assertAlmostEqual(r["energy_wh"], old["energy_wh"])
        self.assertAlmostEqual(r["air_dist_m"], old["dist_m"])
        self.assertAlmostEqual(r["time_s"], old["time_s"])

    def test_wind_does_not_change_air_relative_power_time(self):
        a, b = self.arc(), self.arc(Wind(5, 40))
        self.assertEqual(a["energy_wh"], b["energy_wh"])
        self.assertEqual(a["time_s"], b["time_s"])
        self.assertNotEqual(a["ground_displacement_m"], b["ground_displacement_m"])

    def test_full_circle_drifts(self):
        r = self.arc(Wind(3, 270), angle=360, heading=37)
        self.assertAlmostEqual(r["ground_displacement_m"]["east"], 3*r["time_s"])
        self.assertAlmostEqual(r["ground_displacement_m"]["north"], 0)
        self.assertAlmostEqual(r["exit_air_heading_deg"], 37)
        self.assertFalse(r["ground_fixed_orbit"])

    def test_rotated_entry_heading(self):
        r = self.arc(heading=90)
        self.assertAlmostEqual(r["ground_displacement_m"]["east"], 40)
        self.assertAlmostEqual(r["ground_displacement_m"]["north"], -40)
        self.assertAlmostEqual(r["exit_air_heading_deg"], 180)

    def test_zero_sweep(self):
        r = self.arc(Wind(3, 0), angle=0, heading=-20)
        self.assertEqual(r["time_s"], 0)
        self.assertEqual(r["energy_wh"], 0)
        self.assertEqual(r["ground_displacement_m"], {"east": 0, "north": 0})
        self.assertAlmostEqual(r["exit_air_heading_deg"], 340)

    def test_loiter_partial_revolution(self):
        seconds = 40 * math.pi / 2 / 16
        a = self.arc(Wind(4, 80))
        b = wind_loiter_estimate(self.v, 16, seconds, Wind(4, 80), 0, radius_m=40)
        self.assertDeepNear(a, b)

    def test_multiple_loiter_revolutions(self):
        seconds = (4*math.pi + math.pi/2) * 40 / 16
        r = wind_loiter_estimate(self.v, 16, seconds, Wind(2, 270), 0, radius_m=40)
        self.assertAlmostEqual(r["signed_sweep_deg"], 810)
        self.assertAlmostEqual(r["exit_air_heading_deg"], 90)
        self.assertAlmostEqual(r["ground_displacement_m"]["east"], 40 + 2*seconds)

    def test_exit_ground_heading_uses_wind(self):
        r = self.arc(Wind(5, 180))
        self.assertAlmostEqual(r["exit_ground_heading_deg"], math.degrees(math.atan2(16, 5)))
        self.assertAlmostEqual(r["exit_ground_speed_mps"], math.hypot(16, 5))

    def test_stationary_ground_exit_has_no_heading(self):
        r = self.arc(Wind(16, 90))
        self.assertLess(r["exit_ground_speed_mps"], 1e-9)
        self.assertIsNone(r["exit_ground_heading_deg"])

    def test_calibration_once_and_hybrid_fw(self):
        self.assertAlmostEqual(wind_arc_estimate(replace(self.v, calib=1.2), 16, 90,
                               Wind(), 0, radius_m=40)["energy_wh"], self.arc()["energy_wh"]*1.2)
        r = wind_arc_estimate(load_airframe("vtol_example"), 16, 90, Wind(2, 0), 0)
        self.assertEqual(r["mode"], "fw")
        self.assertAlmostEqual(r["energy_wh"], power_w(load_airframe("vtol_example"),
                               16, "fw", r["bank_deg"])*r["time_s"]/3600)

    def test_geometry_and_multirotor_rejection(self):
        for kwargs in [{"radius_m": 1}, {"bank_deg": 0}, {"bank_deg": 80},
                       {"radius_m": 40, "bank_deg": 20}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                wind_arc_estimate(self.v, 16, 90, Wind(), 0, **kwargs)
        with self.assertRaises(ValueError):
            wind_arc_estimate(load_airframe("x500"), 16, 90, Wind(), 0)
        with self.assertRaises(ValueError):
            wind_arc_estimate(self.v, 1, 90, Wind(), 0)

    def test_invalid_numbers_and_direction(self):
        for kw in [{"heading": float("nan")}, {"angle": -1}, {"angle": 361},
                   {"heading": True}, {"clockwise": 1}, {"clockwise": None}]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.arc(**kw)
        for wind in [Wind(-1, 0), Wind(0, float("inf")), Wind(float("nan"), 0)]:
            with self.subTest(wind=wind), self.assertRaises(ValueError):
                self.arc(wind)
        for duration in [-1, 86401, True]:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                wind_loiter_estimate(self.v, 16, duration, Wind(), 0)

    def test_direction_controls_bank_sign(self):
        a = wind_arc_estimate(self.v, 16, 90, Wind(), 0, False, bank_deg=20)
        b = wind_arc_estimate(self.v, 16, 90, Wind(), 0, False, bank_deg=-20)
        self.assertEqual(a, b)
        self.assertLess(a["bank_deg"], 0)

    def test_inputs_unchanged_and_scope_explicit(self):
        wind = Wind(3, 20)
        before = repr(self.v), repr(wind)
        r = self.arc(wind)
        self.assertEqual(before, (repr(self.v), repr(wind)))
        self.assertNotIn("dist_m", r)  # No ground-path length masquerading as an air arc.
        self.assertFalse(r["ground_fixed_orbit"])
        self.assertIn("not_executable_route", r["scope"])

    def test_implicit_route_wind_still_rejected(self):
        pts = [{"lat": 0, "lon": 0, "alt": 60},
               {"lat": .01, "lon": 0, "alt": 60},
               {"lat": .01, "lon": .01, "alt": 60}]
        with self.assertRaisesRegex(ValueError, "calm wind"):
            route_estimate(self.v, pts, 16, Wind(2, 0))


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False, sort_keys=True))
    else:
        unittest.main()
