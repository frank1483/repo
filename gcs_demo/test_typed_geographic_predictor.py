"""NEW synthetic controls; Claude owns first execution, including --vectors."""
import copy
import json
import math
import sys
import unittest

from .energy import Wind, load_airframe, geographic_energy_alert_snapshot
from .alerts.energy_api import GeographicEnergyAlertPredictor

ENTRY = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}
METRES = math.pi * 6371000 / 180


def candidate(key="current", north=100):
    return {"id": key, "entry": copy.deepcopy(ENTRY), "events": [
        {"kind": "straight", "lat": ENTRY["lat"] + north / METRES,
         "lon": ENTRY["lon"], "alt": 80.0, "ground_mps": 16.0}]}


def vehicle(key="fw_example"):
    v = load_airframe(key)
    v.airframe_profile["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
    return v


def summary(r):
    keys = ("status", "current_id", "sampled_energy_risk", "nominal_end_pct", "low_pct", "high_pct",
            "reserve_pct", "feasible", "executable", "rule_choice")
    out = {k: r[k] for k in keys}
    if "sequence" in r:
        out.update({k: r[k] for k in ("sequence", "active", "raise_streak", "clear_streak")})
        out["severity"] = r["finding"]["severity"] if r["finding"] else None
    return out


def vectors():
    v = vehicle()
    p = GeographicEnergyAlertPredictor(v, 2, 2)
    unsupported = candidate()
    unsupported["events"][0]["lon"] += 0.001
    rows = [summary(geographic_energy_alert_snapshot(v, [candidate()], "current", Wind(0, 0), 100))]
    for seq, pct, item in ((0, 0, candidate()), (1, 0, candidate()), (2, 100, unsupported)):
        rows.append(summary(p.tick(seq, [item], "current", Wind(0, 0), pct)))
    return rows


class TypedGeographicPredictorTests(unittest.TestCase):
    def setUp(self):
        self.v = vehicle()

    def snap(self, pct=100, items=None, key="current", v=None):
        return geographic_energy_alert_snapshot(self.v if v is None else v,
                                               [candidate()] if items is None else items,
                                               key, Wind(0, 0), pct)

    def test_shared_public_entry(self):
        from .alerts.energy_api import geographic_energy_alert_snapshot as adapter
        self.assertEqual(adapter(self.v, [candidate()], "current", Wind(0, 0)), self.snap())

    def test_safe_snapshot_and_evidence(self):
        r = self.snap()
        self.assertEqual(r["status"], "ok")
        self.assertFalse(r["sampled_energy_risk"])
        self.assertEqual(r["comparison"]["candidates"][0]["bounds"]["low_pct"], r["low_pct"])

    def test_risk_uses_current_not_best_alternative(self):
        r = self.snap(20.1, [candidate("current", 1000), candidate("alternative", 1)])
        self.assertTrue(r["sampled_energy_risk"])
        self.assertEqual(r["comparison"]["best_energy_id"], "alternative")
        self.assertIsNone(r["rule_choice"])

    def test_unknown_geometry_is_not_clear(self):
        c = candidate()
        c["events"][0]["lon"] += 0.001
        r = self.snap(items=[c])
        self.assertEqual(r["status"], "unsupported")
        for k in ("sampled_energy_risk", "low_pct", "high_pct"):
            self.assertIsNone(r[k])

    def test_current_id_required_and_unique(self):
        for items, key in (([candidate()], "absent"), ([candidate(), candidate()], "current"), ([candidate()], True)):
            with self.assertRaises(ValueError):
                self.snap(items=items, key=key)

    def test_same_pose_required(self):
        for key in ENTRY:
            other = candidate("other")
            other["entry"][key] += 0.001
            with self.assertRaisesRegex(ValueError, "identical entry"):
                self.snap(items=[candidate(), other])

    def test_entry_schema_and_boolean_rejected(self):
        for pose in (None, {}, {**ENTRY, "extra": 1}, {**ENTRY, "alt": True}):
            c = candidate()
            c["entry"] = pose
            with self.assertRaises(ValueError):
                self.snap(items=[c])

    def test_hybrid_requires_explicit_fw(self):
        h = vehicle("vtol_example")
        with self.assertRaises(ValueError):
            self.snap(v=h)
        c = candidate()
        c["mode"] = "fw"
        self.assertEqual(self.snap(items=[c], v=h)["status"], "ok")
        other = candidate("other")
        other["mode"] = "mc"
        with self.assertRaises(ValueError):
            self.snap(items=[c, other], v=h)

    def test_raise_clear_and_saturated_streaks(self):
        p = GeographicEnergyAlertPredictor(self.v, 2, 2)
        rows = [p.tick(i, [candidate()], "current", Wind(0, 0), pct)
                for i, pct in enumerate((20, 20, 20, 100, 100, 100))]
        self.assertEqual([x["active"] for x in rows], [False, True, True, True, False, False])
        self.assertEqual(rows[2]["raise_streak"], 2)
        self.assertEqual(rows[-1]["clear_streak"], 2)

    def test_nonconsecutive_risk_resets_raise(self):
        p = GeographicEnergyAlertPredictor(self.v, 2, 2)
        rows = [p.tick(i, [candidate()], "current", Wind(0, 0), pct)
                for i, pct in enumerate((20, 100, 20))]
        self.assertFalse(rows[-1]["active"])
        self.assertEqual(rows[-1]["raise_streak"], 1)

    def test_unsupported_resets_and_consumes_sequence(self):
        p = GeographicEnergyAlertPredictor(self.v, 1, 1)
        self.assertTrue(p.tick(0, [candidate()], "current", Wind(0, 0), 0)["active"])
        c = candidate()
        c["events"][0]["lon"] += 0.001
        r = p.tick(1, [c], "current", Wind(0, 0))
        self.assertIsNone(r["active"])
        self.assertIsNone(r["finding"])
        self.assertEqual(r["raise_streak"], 0)
        with self.assertRaises(ValueError):
            p.tick(1, [candidate()], "current", Wind(0, 0))

    def test_schema_failure_consumes_no_state(self):
        p = GeographicEnergyAlertPredictor(self.v, 2, 2)
        p.tick(0, [candidate()], "current", Wind(0, 0), 20)
        with self.assertRaises(ValueError):
            p.tick(1, [candidate()], "absent", Wind(0, 0), 20)
        self.assertTrue(p.tick(1, [candidate()], "current", Wind(0, 0), 20)["active"])

    def test_sequence_types_order_and_bounds(self):
        p = GeographicEnergyAlertPredictor(self.v)
        for seq in (True, -1, 0.5, 9007199254740992):
            with self.assertRaises(ValueError):
                p.tick(seq, [candidate()], "current", Wind(0, 0))
        p.tick(0, [candidate()], "current", Wind(0, 0))
        with self.assertRaises(ValueError):
            p.tick(0, [candidate()], "current", Wind(0, 0))

    def test_tick_limits(self):
        for n in (True, 0, -1, 1.5, 10001):
            with self.assertRaises(ValueError):
                GeographicEnergyAlertPredictor(self.v, n, 1)
            with self.assertRaises(ValueError):
                GeographicEnergyAlertPredictor(self.v, 1, n)

    def test_severity_and_no_action_authority(self):
        p = GeographicEnergyAlertPredictor(self.v, 1, 1)
        for seq, pct, severity in ((0, 100, 5), (1, 20, 4), (2, 0, 2)):
            r = p.tick(seq, [candidate()], "current", Wind(0, 0), pct)
            self.assertEqual(r["finding"]["severity"], severity)
            self.assertEqual(r["finding"]["candidates"], [])
            self.assertIsNone(r["finding"]["rule_choice"])
            for k in ("feasible", "executable", "return_inferred", "landing_modeled"):
                self.assertFalse(r[k])

    def test_inputs_and_result_detached(self):
        items = [candidate()]
        before = copy.deepcopy(items)
        r = self.snap(items=items)
        r["entry"]["lat"] = 0
        r["comparison"]["candidates"][0]["bounds"]["low_pct"] = 0
        self.assertEqual(items, before)
        self.assertNotEqual(self.snap()["low_pct"], 0)

    def test_predictor_vehicle_snapshot(self):
        p = GeographicEnergyAlertPredictor(self.v, 1, 1)
        self.v.reserve_pct = 99
        r = p.tick(0, [candidate()], "current", Wind(0, 0), 50)
        self.assertEqual(r["reserve_pct"], 20)
        self.assertFalse(r["active"])

    def test_finite_json_and_start_percentage(self):
        for pct in (True, -1, 101, float("nan")):
            with self.assertRaises(ValueError):
                self.snap(pct)
        c = candidate()
        c["events"][0]["lat"] = float("nan")
        with self.assertRaises(ValueError):
            self.snap(items=[c])


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False))
    else:
        unittest.main()
