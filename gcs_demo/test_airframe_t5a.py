"""NEW synthetic T5a checks only. First execution belongs to Claude.

No model, device, archived mission, download, SITL or existing research runner.
"""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from .airframe_profile import (G, RHO, load_factor, prop_efficiency, validate_profile)
from .energy import (Vehicle, Wind, best_speed, estimate_route_energy, leg_estimate,
                     load_airframe, power_w, route_estimate, rtl_energy, speed_range,
                     turn_geometry)


class AirframeT5a(unittest.TestCase):
    def setUp(self):
        self.mc = load_airframe("x500")
        self.fw = load_airframe("fw_example")
        self.vt = load_airframe("vtol_example")

    def test_source_labels_and_no_prop_data(self):
        self.assertEqual(self.mc.airframe_profile["source"], "assumed")
        for v in (self.fw, self.vt):
            self.assertEqual(v.airframe_profile["source"], "placeholder")
        for v in (self.mc, self.fw, self.vt):
            self.assertNotIn("eta_table", v.airframe_profile)
            self.assertTrue(json.dumps(v.to_dict(), allow_nan=False))

    def test_legacy_positional_arguments(self):
        v = Vehicle("old", 3, 100, .8, 210, .14, .8, 9, 16, 22, 1.1)
        self.assertEqual((v.mass_kg, v.calib, v.type), (3, 1.1, "multirotor"))
        self.assertIsNone(v.airframe_profile)

    def test_legacy_serialization_payload_unchanged(self):
        self.assertEqual(set(Vehicle().to_dict()), {
            "vehicle_id", "mass_kg", "battery_wh", "usable_frac", "p_hover_w",
            "cda_m2", "eta", "cruise_mps", "max_mps", "reserve_pct", "calib"})
        self.assertNotIn("airframe_profile", Vehicle().to_dict())

    def test_partial_profile_local_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "partial.json"
            p.write_text('\ufeff{"id":"custom","limits":{"reserve_pct":25}}', encoding="utf-8")
            v = load_airframe(p)
        self.assertEqual((v.vehicle_id, v.reserve_pct, v.p_hover_w), ("custom", 25, 190))

    def test_missing_profile_not_silently_defaulted(self):
        with self.assertRaises(FileNotFoundError):
            load_airframe("missing_t5a_profile")

    def test_normalization_copies_and_preserves_provenance(self):
        p = {"notes": {"kind": "synthetic"}, "power": {"cda_m2": .15}}
        normalized = validate_profile(p)
        normalized["notes"]["kind"] = "changed"
        self.assertEqual(p["notes"]["kind"], "synthetic")
        self.assertNotIn("p_hover_w", p["power"])
        self.assertEqual(normalized["power"]["cda_m2"], .15)

    def test_bad_numeric_profile_fields(self):
        for p in ({"mass_kg": True}, {"mass_kg": float("nan")},
                  {"battery": {"wh": 0}}, {"battery": {"usable_frac": 1.1}},
                  {"battery": {"cell_count": 4.5}}, {"limits": {"reserve_pct": 101}},
                  {"limits": {"cruise_mps": 16}}, {"uncertainty": {"capacity_pct": 100}},
                  {"power": {"eta": 0}}, {"power": {"p_hover_w": "190"}}):
            with self.subTest(p=p), self.assertRaises(ValueError):
                validate_profile(p)

    def test_bad_structure_and_json_values(self):
        for p in ([], {"battery": None}, {"type": "plane"}, {"schema": True},
                  {"schema": 1}, {"source": ""}, {"id": ""},
                  {"note": float("inf")}, {"constructor": 1}):
            with self.subTest(p=p), self.assertRaises(ValueError):
                validate_profile(p)

    def test_missing_fixedwing_data_and_hybrid_transition(self):
        with self.assertRaises(ValueError):
            validate_profile({"type": "fixed_wing"})
        p = copy.deepcopy(self.vt.airframe_profile)
        del p["transition"]["to_mc_wh"]
        with self.assertRaises(ValueError):
            validate_profile(p)

    def test_multirotor_curve_and_exact_default_power(self):
        powers = [power_w(self.mc, s) for s in (0, 4, 8, 15)]
        self.assertEqual(powers[0], 190)
        self.assertEqual(powers, sorted(powers))
        for s in (0, 4, 8, 15):
            self.assertEqual(power_w(self.mc, s), power_w(Vehicle(), s))

    def test_x500_synthetic_route_matches_legacy(self):
        points = [{"id": "a", "lat": 0, "lon": 0, "alt": 0},
                  {"id": "b", "lat": .001, "lon": .002, "alt": 12, "kind": "target"},
                  {"id": "c", "lat": 0, "lon": 0, "alt": 0}]
        for wind in (Wind(), Wind(3, 30)):
            self.assertEqual(route_estimate(self.mc, points, 8, wind),
                             route_estimate(Vehicle(), points, 8, wind))

    def test_speed_ranges_and_stall(self):
        self.assertEqual(speed_range(self.mc), (0, 15))
        self.assertAlmostEqual(speed_range(self.fw)[0], 8.4)
        self.assertAlmostEqual(speed_range(self.vt)[0], 9.6)
        for s in (0, speed_range(self.fw)[0] - 1e-6, 35.01):
            with self.subTest(s=s), self.assertRaises(ValueError):
                power_w(self.fw, s)

    def test_fixedwing_power_is_u_shaped(self):
        self.assertGreater(power_w(self.fw, 8.4), power_w(self.fw, 12))
        self.assertGreater(power_w(self.fw, 35), power_w(self.fw, 12))

    def test_induced_drag_scales_with_squared_load_factor(self):
        p = self.fw.airframe_profile["power"]
        s = 24
        parasite = .5 * RHO * s ** 3 * p["wing_area_m2"] * p["cd0"]
        def induced(bank):
            return (power_w(self.fw, s, bank_deg=bank) - p["p_avionics_w"]) * p["eta_prop"] - parasite
        self.assertAlmostEqual(induced(60) / induced(0), 4)

    def test_bank_raises_stall_limit(self):
        lo = speed_range(self.fw, bank_deg=60)[0]
        self.assertAlmostEqual(lo, 8.4 * math.sqrt(2))
        with self.assertRaises(ValueError):
            power_w(self.fw, lo - 1e-6, bank_deg=60)

    def test_turn_radius_and_bank(self):
        t = turn_geometry(self.fw, 16)
        self.assertAlmostEqual(t["radius_m"], 40)
        self.assertAlmostEqual(t["load_factor"], load_factor(t["bank_deg"]))
        self.assertAlmostEqual(16 ** 2 / (G * math.tan(math.radians(t["bank_deg"]))), 40)
        straight = turn_geometry(self.fw, 16, bank_deg=0)
        self.assertIsNone(straight["radius_m"])
        self.assertEqual(straight["load_factor"], 1)

    def test_turn_invalid_inputs(self):
        for kwargs in ({"radius_m": 10}, {"bank_deg": 90}, {"bank_deg": float("nan")},
                       {"bank_deg": 20, "radius_m": 40}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                turn_geometry(self.fw, 16, **kwargs)
        with self.assertRaises(ValueError):
            turn_geometry(self.mc, 8)

    def test_all_types_share_climb_work(self):
        for v, mode, s, eta in ((self.mc, None, 8, .7), (self.fw, None, 16, .7),
                                (self.vt, "mc", 0, .7), (self.vt, "fw", 16, .7)):
            with self.subTest(kind=v.type, mode=mode):
                base = power_w(v, s, mode=mode)
                self.assertAlmostEqual(power_w(v, s, mode=mode, climb_mps=2) - base,
                                       v.mass_kg * G * 2 / eta)
                self.assertEqual(power_w(v, s, mode=mode, climb_mps=-2), base)

    def test_hybrid_requires_mode_and_has_distinct_curves(self):
        with self.assertRaises(ValueError):
            power_w(self.vt, 16)
        self.assertEqual(power_w(self.vt, 0, mode="mc"), 480)
        self.assertLess(power_w(self.vt, 16, mode="fw"), power_w(self.vt, 16, mode="mc"))
        with self.assertRaises(ValueError):
            power_w(self.fw, 16, mode="mc")
        with self.assertRaises(ValueError):
            power_w(self.mc, 8, bank_deg=10)

    def test_prop_interpolation_and_constant_fallback(self):
        p = copy.deepcopy(self.fw.airframe_profile)
        p.update(prop_model="synthetic-test-only", eta_table=[[0, .4], [1, .8]])
        p = validate_profile(p)
        self.assertEqual(prop_efficiency(p, 16, .7), .7)
        self.assertAlmostEqual(prop_efficiency(p, 16, .7, .5), .6)
        self.assertEqual(prop_efficiency(p, 16, .7, 0), .4)
        self.assertEqual(prop_efficiency(p, 16, .7, 2), .8)
        self.fw.airframe_profile = p
        a = power_w(self.fw, 16, advance_ratio=0) - 10
        b = power_w(self.fw, 16, advance_ratio=1) - 10
        self.assertAlmostEqual(a / b, 2)

    def test_prop_rpm_and_diameter_use_dimensionless_j(self):
        p = copy.deepcopy(self.fw.airframe_profile)
        p.update(prop_model={"id": "synthetic-test-only", "rpm": 6000, "diameter_m": .4},
                 eta_table=[[0, .4], [1, .8]])
        p = validate_profile(p)
        self.assertAlmostEqual(prop_efficiency(p, 16, .7), .56)  # J=16/(100*.4)=.4
        self.assertAlmostEqual(prop_efficiency(p, 16, .7, .5), .6)  # actual J overrides nominal RPM

    def test_invalid_prop_tables(self):
        for table in ([[0, .4]], [[0, .4], [0, .8]], [[1, .4], [0, .8]],
                      [[0, 0], [1, .8]], [[0, .4], [1, 1.1]], [[0, .4], [1, True]]):
            p = copy.deepcopy(self.fw.airframe_profile)
            p.update(prop_model="test", eta_table=table)
            with self.subTest(table=table), self.assertRaises(ValueError):
                validate_profile(p)
        with self.assertRaises(ValueError):
            validate_profile({"eta_table": [[0, .4], [1, .8]]})
        with self.assertRaises(ValueError):
            validate_profile({"prop_model": {"id": "test", "rpm": 6000}})

    def test_new_inputs_reject_nonfinite_and_bool(self):
        for kwargs in ({"bank_deg": True}, {"bank_deg": 90}, {"climb_mps": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                power_w(self.fw, 16, **kwargs)
        for s in (-1, float("nan"), True):
            with self.subTest(s=s), self.assertRaises(ValueError):
                power_w(self.mc, s)

    def test_unimplemented_routes_fail_closed(self):
        points = [{"id": "a", "lat": 0, "lon": 0, "alt": 10},
                  {"id": "b", "lat": .001, "lon": 0, "alt": 0}]
        for v in (self.fw, self.vt):
            calls = [lambda: route_estimate(v, [], 16, Wind()),
                     lambda: estimate_route_energy(points, v, Wind()),
                     ]  # T5b1 opens straight-leg/RTL/search only; full route remains gated.
            for call in calls:
                with self.subTest(kind=v.type), self.assertRaises(NotImplementedError):
                    call()


if __name__ == "__main__":
    unittest.main()
