"""NEW synthetic contracts; first execution belongs to Claude, not this CLI."""
import copy
import json
import math
import sys
import unittest
from dataclasses import replace
from unittest.mock import patch

from . import energy
from .alerts import energy_api
from .energy import (Wind, geographic_wind_route_bounds, load_airframe,
                     evaluate_geographic_alert_candidates)

ENTRY = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}
METRES = math.pi * 6371000 / 180


def straight(north=100, entry=None):
    p = ENTRY if entry is None else entry
    return {"kind": "straight", "lat": p["lat"] + north / METRES,
            "lon": p["lon"], "alt": p["alt"], "ground_mps": 16.0}


def arc(angle=90):
    return {"kind": "arc", "v_air": 16.0, "angle_deg": angle,
            "clockwise": True, "radius_m": 40.0}


def candidate(key="C1", north=100, **extra):
    return {"id": key, "entry": copy.deepcopy(ENTRY), "events": [straight(north)], **extra}


def summary(r):
    return {"best_energy_id": r["best_energy_id"], "feasible": r["feasible"],
            "executable": r["executable"], "candidates": [
                {"id": x["id"], "status": x["status"],
                 "sampled_energy_feasible": x["sampled_energy_feasible"],
                 "low_pct": x.get("bounds", {}).get("low_pct"),
                 "high_pct": x.get("bounds", {}).get("high_pct"),
                 "scenarios": [{"status": s["status"], "wind": s["wind"],
                                "end_pct": s.get("end_pct"),
                                "exit_geographic": s.get("base_estimate", {}).get("exit_geographic")}
                               for s in x.get("bounds", {}).get("scenarios", [])]}
                for x in r["candidates"]]}


def vectors():
    rows = []
    curved = candidate("curve")
    curved["events"] = [arc()]
    invalid = candidate("crosswind")
    for profile, items, w, pct in [
            ("fw_example", [candidate()], Wind(0, 0), 100),
            ("fw_example", [curved], Wind(3, 270), 90),
            ("fw_example", [invalid, curved], Wind(0, 270), 100),
            ("vtol_example", [candidate(mode="fw")], Wind(2, 0), 0)]:
        rows.append({"profile": profile, "candidates": items,
                     "wind": {"speed_mps": w.speed_mps, "from_deg": w.from_deg},
                     "start_pct": pct,
                     "result": summary(evaluate_geographic_alert_candidates(load_airframe(profile), items, w, pct))})
    return rows


class TestGeographicAlerts(unittest.TestCase):
    def setUp(self):
        self.v = load_airframe("fw_example")

    def bounds(self, events=None, w=None, v=None, pct=100, mode=None, entry=None):
        return geographic_wind_route_bounds(self.v if v is None else v,
                                             ENTRY if entry is None else entry,
                                             [straight()] if events is None else events,
                                             Wind(0, 0) if w is None else w, pct, mode)

    def run_candidates(self, items=None, w=None, v=None, pct=100):
        return evaluate_geographic_alert_candidates(self.v if v is None else v,
                                                    [candidate()] if items is None else items,
                                                    Wind(0, 0) if w is None else w, pct)

    def test_nominal_and_corner_evidence(self):
        r = self.bounds(w=Wind(3, 0))
        self.assertTrue(r["available"])
        self.assertEqual(len(r["scenarios"]), 13)
        self.assertEqual(r["nominal"]["wind"], {"speed_mps": 3, "from_deg": 0})
        self.assertTrue(all(s["base_estimate"]["projection"]["origin"] == {k: ENTRY[k] for k in ("lat", "lon", "alt")} for s in r["scenarios"]))

    def test_zero_uncertainty_deduplicates(self):
        p = copy.deepcopy(self.v.airframe_profile)
        p["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
        r = self.bounds(v=replace(self.v, airframe_profile=p))
        self.assertEqual(len(r["scenarios"]), 1)
        self.assertEqual(r["low_pct"], r["high_pct"])

    def test_calm_wind_clamp_and_product(self):
        r = self.bounds()
        self.assertEqual(len(r["scenarios"]), 9)
        self.assertEqual({s["wind"]["speed_mps"] for s in r["scenarios"]}, {0, 2})
        self.assertEqual(len({(s["wind"]["speed_mps"], s["power_multiplier"], s["capacity_multiplier"]) for s in r["scenarios"]}), 9)

    def test_scaling_and_extrema(self):
        r = self.bounds(pct=73)
        for s in r["scenarios"]:
            self.assertAlmostEqual(s["energy_wh"], s["base_energy_wh"] * s["power_multiplier"])
            self.assertAlmostEqual(s["end_pct"], 73 - s["energy_wh"] / s["capacity_wh"] * 100)
        self.assertEqual(r["low_pct"], min(s["end_pct"] for s in r["scenarios"]))
        self.assertEqual(r["high_pct"], max(s["end_pct"] for s in r["scenarios"]))

    def test_calibration_once(self):
        a, b = self.bounds(), self.bounds(v=replace(self.v, calib=1.3))
        for x, y in zip(a["scenarios"], b["scenarios"]):
            self.assertAlmostEqual(y["energy_wh"], x["energy_wh"] * 1.3)

    def test_negative_percentages_and_no_authorization(self):
        r = self.bounds(pct=0)
        self.assertLess(r["high_pct"], 0)
        for key in ("feasible", "executable", "return_inferred", "landing_modeled", "common_endpoint_enforced", "wind_direction_varied"):
            self.assertFalse(r[key])

    def test_one_backend_call_per_full_scenario(self):
        events = [straight(100), straight(200)]
        with patch.object(energy, "geographic_wind_route_estimate", wraps=energy.geographic_wind_route_estimate) as spy:
            r = self.bounds(events)
        self.assertEqual(spy.call_count, len(r["scenarios"]))
        for call, s in zip(spy.call_args_list, r["scenarios"]):
            self.assertEqual(call.args[2], events)
            self.assertEqual(call.args[3].speed_mps, s["wind"]["speed_mps"])
            self.assertEqual(len(s["base_estimate"]["legs"]), 2)

    def test_perturbed_tangency_retained(self):
        r = self.bounds(w=Wind(0, 270))
        self.assertEqual(r["nominal"]["status"], "ok")
        self.assertFalse(r["available"])
        self.assertIsNone(r["low_pct"])
        self.assertIsNone(r["high_pct"])
        self.assertTrue(any(s["status"] == "unsupported" and "tangent" in s["reason"] for s in r["scenarios"]))

    def test_nominal_failure_does_not_skip_supported_perturbation(self):
        # This air-heading points north under the +2 m/s easterly drift only.
        e = straight()
        e["lon"] += 12.5 / (METRES * math.cos(math.radians(ENTRY["lat"])))
        e["ground_mps"] = math.hypot(2, 16)
        r = self.bounds([e], Wind(0, 270))
        self.assertEqual(r["nominal"]["status"], "unsupported")
        self.assertTrue(any(s["status"] == "ok" for s in r["scenarios"]))
        self.assertIsNone(r["low_pct"])

    def test_curve_drift_not_common_endpoint(self):
        r = self.bounds([arc()], Wind(3, 270))
        self.assertTrue(r["available"])
        ends = [s["base_estimate"]["exit_geographic"]["lon"] for s in r["scenarios"]]
        self.assertGreater(max(ends), min(ends))
        self.assertFalse(r["common_endpoint_enforced"])

    def test_path_budget_rechecked_per_wind(self):
        loops = [{"kind": "loiter", "v_air": 16, "duration_s": 550,
                  "clockwise": True, "radius_m": 40}]
        r = self.bounds(loops, Wind(1, 270))
        self.assertEqual(r["nominal"]["status"], "ok")
        self.assertFalse(r["available"])
        self.assertTrue(any(s["status"] == "unsupported" and "10 km" in s["reason"] for s in r["scenarios"]))

    def test_inputs_and_evidence_are_detached(self):
        items, w = [candidate()], Wind(0, 0)
        before = copy.deepcopy((self.v.to_dict(), items, vars(w)))
        r = self.run_candidates(items, w)
        b = r["candidates"][0]["bounds"]
        b["nominal"]["base_estimate"]["legs"][0]["exit_geographic"]["lat"] = 0
        self.assertNotEqual(b["scenarios"][0]["base_estimate"]["legs"][0]["exit_geographic"]["lat"], 0)
        self.assertEqual((self.v.to_dict(), items, vars(w)), before)

    def test_hybrid_requires_fw_mode(self):
        h = load_airframe("vtol_example")
        for mode in (None, "mc"):
            with self.assertRaises(ValueError):
                self.bounds(v=h, mode=mode)
        self.assertTrue(self.bounds(v=h, mode="fw")["available"])

    def test_mc_and_missing_profile_rejected(self):
        for v in (load_airframe("x500"), energy_api.default_vehicle()):
            with self.assertRaises(ValueError):
                self.bounds(v=v)

    def test_bad_global_inputs(self):
        for w, pct in [(Wind(-1, 0), 100), (Wind(float("nan"), 0), 100), (Wind(0, 0), True), (Wind(0, 0), 101)]:
            with self.assertRaises(ValueError):
                self.bounds(w=w, pct=pct)
        p = copy.deepcopy(self.v.airframe_profile)
        p["uncertainty"]["capacity_pct"] = 100
        with self.assertRaises(ValueError):
            self.bounds(v=replace(self.v, airframe_profile=p))

    def test_geometry_restrictions_retained(self):
        for ev in ([], [dict(straight(), alt=81)], [dict(straight(), extra=True)], [straight(11000)]):
            r = self.bounds(ev)
            self.assertFalse(r["available"])
            self.assertTrue(all(s["status"] == "unsupported" for s in r["scenarios"]))

    def test_candidates_rank_and_tie_stable(self):
        r = self.run_candidates([candidate("long", 200), candidate("first", 100), candidate("tie", 100)])
        self.assertEqual(r["best_energy_id"], "first")
        self.assertFalse(r["feasible"])
        self.assertFalse(r["executable"])
        self.assertTrue(all(not x["feasible"] for x in r["candidates"]))

    def test_candidates_unsupported_and_deficit_excluded(self):
        bad = candidate("bad")
        bad["events"] = []
        r = self.run_candidates([bad, candidate("ok")])
        self.assertEqual([x["status"] for x in r["candidates"]], ["unsupported", "ok"])
        self.assertEqual(r["best_energy_id"], "ok")
        self.assertIsNone(self.run_candidates(pct=0)["best_energy_id"])

    def test_malformed_batch_schema_rejected(self):
        for items in ([], [candidate(), candidate()], [candidate("")], [candidate("x" * 129)],
                      [candidate(action="RTL")], [candidate()] * 17,
                      [{"id": "x", "points": [], "ground_mps": 16}]):
            with self.assertRaises(ValueError):
                self.run_candidates(items)
        self.assertEqual(self.run_candidates([candidate("😀" * 128)])["candidates"][0]["status"], "ok")

    def test_nonfinite_and_cycles_rejected(self):
        a = candidate()
        a["entry"]["lat"] = float("nan")
        b = candidate()
        b["events"].append(b)
        for x in (a, b):
            with self.assertRaises(ValueError):
                self.run_candidates([x])

    def test_adapter_forwards_without_enu_conversion(self):
        args = (self.v, ENTRY, [straight()], Wind(0, 0), 84, None)
        self.assertEqual(energy_api.geographic_wind_route_bounds(*args), geographic_wind_route_bounds(*args))
        args2 = (self.v, [candidate()], Wind(0, 0), 84)
        self.assertEqual(energy_api.evaluate_geographic_alert_candidates(*args2), evaluate_geographic_alert_candidates(*args2))


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--vectors":
        print(json.dumps(vectors(), allow_nan=False, ensure_ascii=False))
    else:
        unittest.main()
