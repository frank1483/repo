"""New synthetic integration controls. Claude owns first execution."""
import copy
import json
import math
import sys
import unittest

from .energy import load_airframe
from .alerts.typed_feed import TypedGeographicAlertFeed
from .alert_bridge import AlertFeed

ENTRY = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}
METRES = math.pi * 6371000 / 180


def vehicle(key="fw_example"):
    v = load_airframe(key)
    v.airframe_profile["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
    return v


def candidate(key="current", bad=False):
    return {"id": key, "entry": copy.deepcopy(ENTRY), "events": [
        {"kind": "straight", "lat": 23.0 + 100 / METRES,
         "lon": 120.001 if bad else 120.0, "alt": 80.0, "ground_mps": 16.0}]}


def record(seq=0, pct=100):
    return {**ENTRY, "t_s": float(seq), "battery_pct": pct, "wind_mps": 0.0, "wind_from": 0.0}


def tick(feed, seq, pct=100, bad=False, version="v1"):
    return feed.tick(seq, record(seq, pct), [candidate(bad=bad)], "current", version)


def summary(r):
    return {**{k: r[k] for k in ("sequence", "t_s", "mission_version", "status", "active",
                                 "raise_streak", "clear_streak", "nominal_end_pct", "low_pct",
                                 "high_pct", "unassessed_predictors", "feasible", "executable")},
            "event_types": [e["type"] for e in r["events"]],
            "event_active": [e["active"] for e in r["events"]],
            "event_severity": [e["severity"] for e in r["events"]]}


def vectors():
    f = TypedGeographicAlertFeed(vehicle(), 2, 2)
    args = [(100, False, "v1"), (20, False, "v1"), (20, False, "v1"),
            (100, True, "v1"), (100, False, "v1"), (20, False, "v1"),
            (20, False, "v2"), (20, False, "v2")]
    return [summary(tick(f, i, *a)) for i, a in enumerate(args)]


class TypedFeedTests(unittest.TestCase):
    def feed(self, r=2, c=2):
        return TypedGeographicAlertFeed(vehicle(), r, c)

    def test_first_known_without_synthetic_power(self):
        r = tick(self.feed(), 0)
        self.assertEqual([x["type"] for x in r["events"]], ["known"])
        self.assertFalse(r["active"])

    def test_raise_resolve_hysteresis(self):
        f = self.feed()
        rows = [tick(f, i, pct) for i, pct in enumerate((20, 20, 100, 100))]
        self.assertEqual([[e["type"] for e in r["events"]] for r in rows],
                         [["known"], ["raise"], [], ["resolve"]])
        self.assertFalse(rows[-1]["events"][0]["active"])

    def test_unknown_does_not_resolve(self):
        f = self.feed(1, 1)
        tick(f, 0, 20)
        r = tick(f, 1, 100, True)
        self.assertEqual([e["type"] for e in r["events"]], ["unknown"])
        self.assertIsNone(r["active"])
        self.assertIsNone(r["events"][0]["active"])

    def test_repeated_unknown_and_recovery(self):
        f = self.feed()
        self.assertEqual(tick(f, 0, bad=True)["events"][0]["type"], "unknown")
        self.assertEqual(tick(f, 1, bad=True)["events"], [])
        self.assertEqual(tick(f, 2)["events"][0]["type"], "known")

    def test_version_change_resets_streak(self):
        f = self.feed()
        tick(f, 0, 20)
        r = tick(f, 1, 20, version="v2")
        self.assertFalse(r["active"])
        self.assertEqual(r["raise_streak"], 1)
        self.assertEqual([e["type"] for e in r["events"]], ["reset", "known"])
        self.assertTrue(tick(f, 2, 20, version="v2")["active"])

    def test_version_change_keeps_global_order(self):
        f = self.feed()
        tick(f, 2)
        with self.assertRaisesRegex(ValueError, "sequence"):
            tick(f, 1, version="v2")
        self.assertEqual(tick(f, 3, version="v2")["sequence"], 3)

    def test_missing_measured_field_consumes_no_state(self):
        f = self.feed()
        for key in record():
            rec = record()
            del rec[key]
            with self.assertRaises(ValueError):
                f.tick(0, rec, [candidate()], "current", "v1")
        self.assertEqual(tick(f, 0)["sequence"], 0)

    def test_candidate_pose_must_match_measurement(self):
        f = self.feed()
        for key in ENTRY:
            c = candidate()
            c["entry"][key] += 0.001
            with self.assertRaisesRegex(ValueError, "measured geographic pose"):
                f.tick(0, record(), [c], "current", "v1")
        self.assertEqual(tick(f, 0)["status"], "ok")

    def test_time_order_and_schema_errors_are_transactional(self):
        f = self.feed()
        tick(f, 0, 20)
        with self.assertRaises(ValueError):
            f.tick(1, record(0, 20), [candidate()], "current", "v1")
        with self.assertRaises(ValueError):
            f.tick(1, record(1, 20), [candidate()], "absent", "v1")
        self.assertTrue(tick(f, 1, 20)["active"])

    def test_bad_replacement_preserves_old_predictor(self):
        f = self.feed()
        tick(f, 0, 20)
        with self.assertRaises(ValueError):
            f.tick(1, record(1, 20), [candidate()], "absent", "v2")
        self.assertTrue(tick(f, 1, 20)["active"])

    def test_current_change_requires_new_version(self):
        f = self.feed()
        tick(f, 0)
        with self.assertRaises(ValueError):
            f.tick(1, record(1), [candidate("other")], "other", "v1")
        r = f.tick(1, record(1), [candidate("other")], "other", "v2")
        self.assertEqual(r["current_id"], "other")

    def test_nonfinite_boolean_and_ranges(self):
        for key in record():
            for value in (True, float("nan"), float("inf")):
                rec = record()
                rec[key] = value
                with self.assertRaises(ValueError):
                    self.feed().tick(0, rec, [candidate()], "current", "v1")
        for key, value in (("lat", 76), ("lon", 181), ("alt", -1), ("wind_mps", -1),
                           ("battery_pct", -1), ("battery_pct", 101), ("t_s", -1)):
            rec = record()
            rec[key] = value
            with self.assertRaises(ValueError):
                self.feed().tick(0, rec, [candidate()], "current", "v1")

    def test_versions_and_sequence_contract(self):
        for v in (None, True, "", "x" * 129, "版本", "v1\n"):
            with self.assertRaises(ValueError):
                tick(self.feed(), 0, version=v)
        for seq in (True, -1, 0.5, 9007199254740992):
            with self.assertRaises(ValueError):
                tick(self.feed(), seq)

    def test_hybrid_requires_explicit_fw_mode(self):
        f = TypedGeographicAlertFeed(vehicle("vtol_example"))
        with self.assertRaises(ValueError):
            tick(f, 0)
        c = candidate()
        c["mode"] = "fw"
        self.assertEqual(f.tick(0, record(), [c], "current", "v1")["status"], "ok")

    def test_mc_rejected_and_thresholds_checked(self):
        with self.assertRaises(ValueError):
            TypedGeographicAlertFeed(vehicle("x500"))
        for n in (True, 0, -1, 1.5, 10001):
            with self.assertRaises(ValueError):
                self.feed(n, 1)
            with self.assertRaises(ValueError):
                self.feed(1, n)

    def test_inputs_outputs_and_vehicle_detached(self):
        v = vehicle()
        f = TypedGeographicAlertFeed(v, 1, 1)
        v.reserve_pct = 99
        rec, items = record(0, 50), [candidate()]
        original = copy.deepcopy((rec, items))
        r = f.tick(0, rec, items, "current", "v1")
        r["events"][0]["type"] = "edited"
        self.assertEqual((rec, items), original)
        self.assertEqual(tick(f, 1, 50)["reserve_pct"], 20)

    def test_no_action_authority_or_unassessed_clear(self):
        r = tick(self.feed(), 0)
        self.assertEqual(r["unassessed_predictors"], ["P2", "P3", "P4", "P5"])
        for k in ("feasible", "executable", "return_inferred", "landing_modeled"):
            self.assertFalse(r[k])
        self.assertIsNone(r["rule_choice"])

    def test_alertfeed_opt_in_no_enu_or_model(self):
        from .alerts import energy_api
        before = energy_api.REF_LAT, energy_api.REF_LON
        calls = []
        f = AlertFeed(None, None, vehicle(), explain_fn=lambda e: calls.append(e),
                      typed_geographic=True, typed_raise_ticks=1, typed_clear_ticks=1)
        req = {"sequence": 0, "candidates": [candidate()], "current_id": "current", "mission_version": "v1"}
        ev = f.tick(record(0, 20), None, req)
        self.assertIsNone(f.engine)
        self.assertEqual(calls, [])
        self.assertEqual((energy_api.REF_LAT, energy_api.REF_LON), before)
        self.assertEqual(ev[0]["type"], "raise")
        ev[0]["type"] = "edited"
        self.assertEqual(f.events[0]["type"], "raise")
        self.assertEqual(f.latest["events"][0]["type"], "raise")

    def test_alertfeed_typed_request_and_set_path_guards(self):
        f = AlertFeed(None, None, vehicle(), typed_geographic=True)
        for req in (None, {}, {"sequence": 0}, {"sequence": 0, "candidates": [candidate()],
                    "current_id": "current", "mission_version": "v1", "extra": 1}):
            with self.assertRaises(ValueError):
                f.tick(record(), None, req)
        with self.assertRaises(ValueError):
            f.set_path([])
        req = {"sequence": 0, "candidates": [candidate()], "current_id": "current", "mission_version": "v1"}
        with self.assertRaises(ValueError):
            f.tick(record(), 0, req)
        self.assertEqual(f.tick(record(), None, req)[0]["type"], "known")

    def test_legacy_rejects_typed_request_and_ambiguous_optin(self):
        home = {"lat": 23.0, "lon": 120.0}
        f = AlertFeed(home, [home, {**home, "lat": 23.001}, home], vehicle("x500"), explain_fn=None)
        with self.assertRaises(ValueError):
            f.tick({}, 0, {})
        with self.assertRaises(ValueError):
            AlertFeed(home, [], vehicle(), typed_geographic=True)
        with self.assertRaises(ValueError):
            AlertFeed(None, None, vehicle(), typed_geographic=1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False))
    else:
        unittest.main()
