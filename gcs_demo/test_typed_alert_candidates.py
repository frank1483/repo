"""NEW synthetic contracts. Claude owns first execution; no external models."""
import copy
import json
import sys
import unittest
from dataclasses import replace

from .energy import Wind, load_airframe, typed_alert_speeds, evaluate_typed_alert_candidates
from .alerts import energy_api as api


def candidate(key="C1", distance=.001, speed=16, **extra):
    return {"id": key, "points": [{"id": "start", "lat": 23, "lon": 120, "alt": 80},
                                    {"id": "end", "lat": 23 + distance, "lon": 120, "alt": 80}],
            "ground_mps": speed, **extra}


def summary(result):
    return {"best_energy_id": result["best_energy_id"], "feasible": result["feasible"],
            "executable": result["executable"], "candidates": [
                {"id": r["id"], "status": r["status"], "sampled_energy_feasible": r["sampled_energy_feasible"],
                 "low_pct": r.get("bounds", {}).get("low_pct"),
                 "high_pct": r.get("bounds", {}).get("high_pct")} for r in result["candidates"]]}


def vectors():
    rows = []
    for profile, mode, start in [("fw_example", None, 100), ("fw_example", None, 0),
                                  ("vtol_example", "mc", 90), ("vtol_example", "fw", 85)]:
        v, wind = load_airframe(profile), Wind(1, 0)
        items = [candidate("C1", mode=mode), candidate("C2", distance=.002, mode=mode)]
        result = evaluate_typed_alert_candidates(v, items, wind, start)
        rows.append({"profile": profile, "candidates": items, "wind": {"speed_mps": 1, "from_deg": 0},
                     "start_pct": start, "result": summary(result)})
    return rows


class TypedAlertCandidateTests(unittest.TestCase):
    def setUp(self):
        self.v = load_airframe("fw_example")

    def run_candidates(self, items=None, vehicle=None, start=100, wind=None):
        return evaluate_typed_alert_candidates(vehicle or self.v, [candidate()] if items is None else items,
                                               wind or Wind(), start)

    def test_fw_stall_filter_sorted_deduplicated(self):
        r = typed_alert_speeds(self.v, [16, 4, 16, 35, 36])
        self.assertEqual(r["accepted_mps"], [16, 35])
        self.assertEqual(r["rejected_mps"], [4, 36])
        self.assertIn("not_ground", r["basis"])

    def test_bank_increases_minimum(self):
        self.assertGreater(typed_alert_speeds(self.v, [16], bank_deg=60)["minimum_mps"],
                           typed_alert_speeds(self.v, [16])["minimum_mps"])

    def test_hybrid_requires_mode(self):
        h = load_airframe("vtol_example")
        with self.assertRaises(ValueError):
            typed_alert_speeds(h, [4])
        self.assertEqual(self.run_candidates(vehicle=h)["candidates"][0]["status"], "unsupported")

    def test_hybrid_mc_no_fw_stall(self):
        h = load_airframe("vtol_example")
        self.assertEqual(typed_alert_speeds(h, [0, 4, 16], "mc")["accepted_mps"], [0, 4, 16])
        self.assertEqual(typed_alert_speeds(h, [4, 16], "fw")["accepted_mps"], [16])

    def test_mc_bank_rejected(self):
        with self.assertRaises(ValueError):
            typed_alert_speeds(load_airframe("x500"), [4], bank_deg=5)

    def test_speed_inputs_rejected(self):
        for speeds in ([], [True], [float("nan")], [-1], [1] * 102):
            with self.assertRaises(ValueError):
                typed_alert_speeds(self.v, speeds)
        with self.assertRaises(ValueError):
            typed_alert_speeds(self.v, [16], "mc")

    def test_rank_conservative_energy_only(self):
        r = self.run_candidates([candidate("long", .002), candidate("short")])
        self.assertEqual(r["best_energy_id"], "short")
        self.assertFalse(r["feasible"])
        self.assertFalse(r["executable"])
        self.assertFalse(r["return_inferred"])
        self.assertTrue(all(not x["feasible"] for x in r["candidates"]))

    def test_tie_retains_first(self):
        self.assertEqual(self.run_candidates([candidate("a"), candidate("b")])["best_energy_id"], "a")

    def test_start_zero_keeps_negative_bounds(self):
        r = self.run_candidates(start=0)
        self.assertIsNone(r["best_energy_id"])
        self.assertLess(r["candidates"][0]["bounds"]["low_pct"], 0)

    def test_bounds_share_wind_over_whole_route(self):
        r = self.run_candidates()["candidates"][0]
        self.assertEqual(r["status"], "ok")
        self.assertGreater(len(r["bounds"]["scenarios"]), 1)
        self.assertEqual(r["bounds"]["nominal"]["wind"], {"speed_mps": 0, "from_deg": 0})
        for s in r["bounds"]["scenarios"]:
            self.assertGreaterEqual(s["energy_wh"], 0)

    def test_unsupported_wind_turn_is_visible(self):
        item = candidate()
        item["points"].append({"id": "return", "lat": 23, "lon": 120, "alt": 80})
        # Nominal calm turn works, but positive-wind scenarios cannot model it.
        row = self.run_candidates([item])["candidates"][0]
        self.assertEqual(row["status"], "unsupported")
        self.assertFalse(row["bounds"]["available"])
        self.assertIsNone(row["bounds"]["low_pct"])
        self.assertTrue(any(s["status"] == "unsupported" for s in row["bounds"]["scenarios"]))

    def test_bad_row_does_not_hide_valid_row(self):
        r = self.run_candidates([candidate("slow", speed=1), candidate("valid")])
        self.assertEqual([x["status"] for x in r["candidates"]], ["unsupported", "ok"])
        self.assertEqual(r["best_energy_id"], "valid")

    def test_invalid_batch_ids_and_fields(self):
        for items in ([], [candidate()] * 2, [candidate("",)], [dict(candidate(), action="LAND")], [candidate()] * 17):
            with self.assertRaises(ValueError):
                self.run_candidates(items)

    def test_malformed_route_is_unsupported(self):
        for points in (None, [], [{}, {}]):
            row = self.run_candidates([dict(candidate(), points=points)])["candidates"][0]
            self.assertEqual(row["status"], "unsupported")

    def test_snapshot_and_input_immutability(self):
        items, wind = [candidate()], Wind()
        before = copy.deepcopy((self.v.to_dict(), items, wind))
        r = self.run_candidates(items, wind=wind)
        r["candidates"][0]["estimate"]["bounds_context"]["route"][0]["lat"] = 0
        self.assertEqual((self.v.to_dict(), items, wind), before)

    def test_calibration_scales_once(self):
        a = self.run_candidates()["candidates"][0]["estimate"]["energy_wh"]
        b = self.run_candidates(vehicle=replace(self.v, calib=1.3))["candidates"][0]["estimate"]["energy_wh"]
        self.assertAlmostEqual(b, a * 1.3)

    def test_api_caller_is_same_engine(self):
        items, wind = [candidate()], Wind()
        self.assertEqual(api.evaluate_typed_alert_candidates(self.v, items, wind), self.run_candidates(items))
        self.assertEqual(api.typed_alert_speeds(self.v, [4, 16]), typed_alert_speeds(self.v, [4, 16]))

    def test_legacy_engine_stays_explicitly_unsupported(self):
        from .alerts.predict import PredictiveAlertEngine
        with self.assertRaises(NotImplementedError):
            PredictiveAlertEngine([(0, 1, 80)], (0, 0, 0), self.v)


if __name__ == "__main__":
    if "--vectors" in sys.argv:
        print(json.dumps(vectors(), allow_nan=False))
    else:
        unittest.main()
