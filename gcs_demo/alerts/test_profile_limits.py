"""NEW T5b2c1 contracts. Claude owns first execution; no external I/O."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from gcs_demo import energy
from gcs_demo.alerts import energy_api as api
from gcs_demo.alerts.predict import Config, PredictiveAlertEngine, Telemetry


class AlertProfileLimitsTests(unittest.TestCase):
    def engine(self, vehicle, config=None):
        return PredictiveAlertEngine([(300, 0, 40)], (0, 0, 0), vehicle, config)

    def profile_vehicle(self, reserve=31.0, wind=6.0):
        profile = copy.deepcopy(energy.load_airframe("x500").airframe_profile)
        profile["limits"].update(reserve_pct=reserve, wind_limit_mps=wind)
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / "custom.json"
            filename.write_text(json.dumps(profile), encoding="utf-8")
            return api.default_vehicle(filename)

    def telemetry(self, wind=7.0):
        return Telemetry(t=60, pos=(0, 0, 40), vel=(8, 0, 0), soc_pct=70,
                         voltage=16, current_a=8, used_wh=5, cell_count=4,
                         next_wp=0, link_pct=90, wind=api.Wind(wind, 90))

    def test_no_argument_keeps_legacy_demo_parameters(self):
        v = api.default_vehicle()
        self.assertEqual(v.to_dict(), energy.Vehicle(
            vehicle_id="UAV-01", mass_kg=6.0, battery_wh=488.0, usable_frac=1.0,
            p_hover_w=800.0, cda_m2=0.15, eta=0.7, cruise_mps=12.0,
            max_mps=16.0, reserve_pct=20.0).to_dict())
        self.assertIsNone(v.airframe_profile)

    def test_id_loading_is_the_shared_energy_loader(self):
        self.assertEqual(api.default_vehicle("x500").to_dict(),
                         energy.load_airframe("x500").to_dict())

    def test_path_loading_controls_exactly_two_config_fields(self):
        v = self.profile_vehicle()
        cfg = Config(reserve_pct=5, wind_limit_mps=25, link_min_pct=42,
                     cell_r_ohm=0.007, cell_empty_v=3.6, raise_ticks=4,
                     clear_ticks=8, horizon_s=123)
        original = asdict(cfg)
        e = self.engine(v, cfg)
        expected = dict(original, reserve_pct=31.0, wind_limit_mps=6.0)
        self.assertEqual(asdict(e.cfg), expected)
        self.assertEqual(asdict(cfg), original)
        self.assertIsNot(e.cfg, cfg)
        self.assertEqual(v.reserve_pct, e.cfg.reserve_pct)

    def test_profile_limits_used_without_custom_config(self):
        e = self.engine(self.profile_vehicle())
        self.assertEqual((e.cfg.reserve_pct, e.cfg.wind_limit_mps), (31, 6))
        self.assertEqual(e.cfg.link_min_pct, Config().link_min_pct)

    def test_legacy_custom_config_and_vehicle_reserve_stay_unchanged(self):
        v = replace(api.default_vehicle(), reserve_pct=7)
        cfg = Config(reserve_pct=33, wind_limit_mps=9, raise_ticks=5)
        self.assertEqual(asdict(self.engine(v, cfg).cfg), asdict(cfg))
        self.assertEqual(v.reserve_pct, 7)

    def test_profile_limits_are_copied_at_engine_construction(self):
        v = self.profile_vehicle()
        e = self.engine(v)
        v.airframe_profile["limits"]["wind_limit_mps"] = 99
        self.assertEqual(e.cfg.wind_limit_mps, 6)

    def test_calibration_keeps_profile_limits_and_source(self):
        v = self.profile_vehicle()
        original = copy.deepcopy(v.to_dict())
        updated = api.with_calib(v, 1.2)
        self.assertEqual(updated.airframe_profile, v.airframe_profile)
        self.assertEqual(self.engine(updated).cfg.reserve_pct, 31)
        self.assertEqual(updated.calib, 1.2)
        self.assertEqual(v.to_dict(), original)

    def test_profile_leg_uses_shared_energy_without_new_formula(self):
        v, a, b, wind = self.profile_vehicle(), (0, 0, 40), (300, 0, 45), api.Wind(3, 90)
        actual = api.leg_energy(v, a, b, wind)
        expected = energy.leg_estimate(v, api.to_latlon(a), api.to_latlon(b),
                                       a[2], b[2], v.cruise_mps, wind)
        self.assertEqual(actual, expected)

    def test_profile_rtl_uses_shared_energy_without_new_formula(self):
        v, pos, home, wind = self.profile_vehicle(), (300, 0, 40), (0, 0, 0), api.Wind(3, 270)
        lat, lon = api.to_latlon(pos)
        hlat, hlon = api.to_latlon(home)
        expected = energy.rtl_energy({"lat": lat, "lon": lon, "alt": pos[2]},
                                     {"lat": hlat, "lon": hlon}, v, wind)
        self.assertEqual(api.rtl_energy(pos, home, v, wind), expected)

    def test_wind_finding_uses_loaded_limit_in_its_evidence(self):
        e = self.engine(self.profile_vehicle())
        e._wind_hist.extend((i, 7.0) for i in range(59))
        finding = e._wind(self.telemetry())
        self.assertTrue(finding.active)
        self.assertEqual(finding.lead_s, 0)
        self.assertEqual(next(x["value"] for x in finding.evidence if x["id"] == "E3"), "6 m/s")

    def test_reserve_finding_uses_loaded_limit_in_its_evidence(self):
        e = self.engine(self.profile_vehicle())
        findings = e._battery_route(self.telemetry(wind=0), 60.0, "soc", None)
        finding = next(f for f in findings if f.key == "battery_route")
        self.assertEqual(next(x["value"] for x in finding.evidence if x["id"] == "E2"), "31%")

    def test_bad_profile_does_not_fall_back_to_demo(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / "invalid.json"
            filename.write_text('{"limits":{"wind_limit_mps":-1}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                api.default_vehicle(filename)

    def test_missing_profile_does_not_fall_back_to_demo(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                api.default_vehicle(Path(folder) / "missing.json")

    def test_non_mc_alert_engines_reject_before_generating_candidates(self):
        for profile_id in ("fw_example", "vtol_example"):
            with self.subTest(profile=profile_id):
                vehicle = api.default_vehicle(profile_id)
                with self.assertRaisesRegex(NotImplementedError, vehicle.type):
                    self.engine(vehicle)


if __name__ == "__main__":
    unittest.main()
