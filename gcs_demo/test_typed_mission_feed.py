"""NEW engineering controls. Claude owns first functional execution."""
import copy
import json
import sys
import unittest
from dataclasses import replace

from .energy import load_airframe
from .alerts.typed_mission_feed import TypedMissionSampleFeed

ENTRY = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}
TARGET = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "tolerance_m": 0.001}


def vehicle(name="fw_example"):
    v = load_airframe(name)
    p = copy.deepcopy(v.airframe_profile)
    p["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
    return replace(v, airframe_profile=p)


def arc():
    return {"kind": "arc", "v_air": 16.0, "angle_deg": 180.0, "clockwise": True, "radius_m": 40.0}


def request(version="v1"):
    return {"mission_version": version, "recovery_reference_id": "site:home",
            "p1": {"current_id": "current", "candidates": [{"id": "current", "entry": copy.deepcopy(ENTRY), "events": [arc() for _ in range(4)], "mode": "fw"}]},
            "p2": {"target": copy.deepcopy(TARGET), "probes": [{"id": "A", "outbound_events": [arc()], "return_events": [arc()]}], "mode": "fw"}}


def rec(t=1, pct=100):
    return {**ENTRY, "t_s": t, "battery_pct": pct, "wind_mps": 0, "wind_from": 0, "mode": "fw"}


def kinds(output, code):
    return [e["type"] for e in output["events"] if e["predictor"] == code]


def summary(output):
    o = copy.deepcopy(output)
    del o["predictors"]["P1"]["snapshot"]["comparison"]
    for p in o["predictors"]["P2"]["snapshot"]["probes"]:
        del p["bounds"]
        for s in p["scenarios"]:
            s.pop("reason", None)  # Backend error prose is not a parity contract.
    return o


def vectors():
    traces = []
    for name in ("latch", "version", "gap", "p2_unknown", "p1_unknown", "version_and_gap", "hybrid", "different_reference"):
        f = TypedMissionSampleFeed(vehicle("vtol_example" if name == "hybrid" else "fw_example"), 2, 2, 5)
        rows = [f.tick(1, rec(1, 0), request())]
        if name == "latch" or name == "hybrid":
            for i, pct in enumerate((0, 100, 100), 2):
                rows.append(f.tick(i, rec(i, pct), request()))
        elif name == "version":
            rows.append(f.tick(2, rec(2, 0), request("v2")))
        elif name == "gap":
            rows.append(f.tick(2, rec(7, 0), request()))
        elif name == "version_and_gap":
            rows.append(f.tick(2, rec(7, 0), request("v2")))
        elif name == "different_reference":
            r = request("v2")
            r["recovery_reference_id"] = "site:alternate"
            rows.append(f.tick(2, rec(2, 100), r))
        else:
            rows.append(f.tick(2, rec(2, 0), request()))
            r = request()
            if name == "p2_unknown":
                r["p2"]["probes"][0]["return_events"] = [{"kind": "landing"}]
            else:
                r["p1"]["candidates"][0]["events"][-1] = {"kind": "landing"}
            rows.append(f.tick(3, rec(3, 0), r))
            rows.append(f.tick(4, rec(4, 0), request()))
        traces.append({"name": name, "outputs": [summary(r) for r in rows]})
    return {"contract": "mission_sample_feed_v1", "traces": traces}


class TestTypedMissionFeed(unittest.TestCase):
    def test_safe_initial_is_samples_only(self):
        o = TypedMissionSampleFeed(vehicle()).tick(1, rec(), request())
        self.assertEqual(o["status"], "ok")
        for code in ("P1", "P2"):
            self.assertIs(o["predictors"][code]["active"], False)
            self.assertEqual(kinds(o, code), ["known"])
        self.assertEqual(o["unassessed_predictors"], ["P3", "P4", "P5"])

    def test_independent_raise_and_clear_hysteresis(self):
        rows = vectors()["traces"][0]["outputs"]
        for code in ("P1", "P2"):
            self.assertEqual([r["predictors"][code]["active"] for r in rows], [False, True, True, False])
            self.assertEqual(kinds(rows[1], code), ["raise"])
            self.assertEqual(kinds(rows[2], code), [])
            self.assertEqual(kinds(rows[3], code), ["resolve"])
            self.assertEqual(rows[2]["predictors"][code]["finding"]["value"], "sampled_risk_latched_pending_clear")

    def test_p2_unknown_never_resolves_or_clears_p1(self):
        rows = vectors()["traces"][3]["outputs"]
        self.assertIs(rows[2]["predictors"]["P2"]["active"], None)
        self.assertEqual(kinds(rows[2], "P2"), ["unknown"])
        self.assertIs(rows[2]["predictors"]["P1"]["active"], True)
        self.assertIs(rows[3]["predictors"]["P2"]["active"], False)
        self.assertEqual(rows[3]["predictors"]["P2"]["raise_streak"], 1)
        self.assertEqual(kinds(rows[3], "P2"), ["known"])

    def test_p1_unknown_does_not_hide_p2(self):
        rows = vectors()["traces"][4]["outputs"]
        self.assertEqual(rows[2]["status"], "unknown")
        self.assertIs(rows[2]["predictors"]["P1"]["active"], None)
        self.assertEqual(kinds(rows[2], "P1"), ["unknown"])
        self.assertIs(rows[2]["predictors"]["P2"]["active"], True)

    def test_version_reset_and_gap_reset(self):
        traces = vectors()["traces"]
        for i, reason in ((1, ["mission_version_changed"]), (2, ["telemetry_gap"]), (5, ["mission_version_changed", "telemetry_gap"])):
            o = traces[i]["outputs"][1]
            self.assertEqual(o["reset_reasons"], reason)
            for code in ("P1", "P2"):
                self.assertEqual(kinds(o, code), ["reset", "known"])
                self.assertEqual(o["predictors"][code]["raise_streak"], 1)
                reset = next(e for e in o["events"] if e["predictor"] == code and e["type"] == "reset")
                self.assertIsNone(reset["active"])
                self.assertEqual(reset["evidence"], [])

    def test_gap_equality_retains_streak(self):
        f = TypedMissionSampleFeed(vehicle(), 2, 2, 5)
        f.tick(1, rec(1, 0), request())
        o = f.tick(2, rec(6, 0), request())
        self.assertEqual(o["reset_reasons"], [])
        self.assertIs(o["predictors"]["P2"]["active"], True)

    def test_p2_schema_error_rolls_back_both(self):
        f = TypedMissionSampleFeed(vehicle(), 3, 2)
        f.tick(1, rec(1, 0), request())
        r = request()
        del r["p2"]["target"]["tolerance_m"]
        with self.assertRaises(ValueError):
            f.tick(2, rec(2, 0), r)
        o = f.tick(2, rec(2, 0), request())
        for code in ("P1", "P2"):
            self.assertEqual(o["predictors"][code]["raise_streak"], 2)
            self.assertIs(o["predictors"][code]["active"], False)

    def test_reject_unrelated_outbound(self):
        r = request()
        r["p2"]["probes"][0]["outbound_events"][0]["radius_m"] = 41
        with self.assertRaises(ValueError):
            TypedMissionSampleFeed(vehicle()).tick(1, rec(), r)

    def test_pose_alignment_including_alternatives(self):
        for field, value in (("lat", 24), ("air_heading_deg", 1), ("alt", 81), ("lat", True)):
            r = request()
            other = copy.deepcopy(r["p1"]["candidates"][0])
            other["id"] = "other"
            other["entry"][field] = value
            r["p1"]["candidates"].append(other)
            with self.assertRaises(ValueError):
                TypedMissionSampleFeed(vehicle()).tick(1, rec(), r)

    def test_identity_and_target_changes_require_version(self):
        for variant in ("current", "reference", "target"):
            f = TypedMissionSampleFeed(vehicle())
            f.tick(1, rec(), request())
            r = request()
            if variant == "current":
                r["p1"]["current_id"] = r["p1"]["candidates"][0]["id"] = "other"
            elif variant == "reference":
                r["recovery_reference_id"] = "site:other"
            else:
                r["p2"]["target"]["tolerance_m"] = 20
            with self.assertRaises(ValueError):
                f.tick(2, rec(2), r)
            r["mission_version"] = "v2"
            self.assertEqual(f.tick(2, rec(2), r)["reset_reasons"], ["mission_version_changed"])

    def test_measured_mode_explicit_for_fw_and_hybrid(self):
        self.assertEqual(vectors()["traces"][6]["outputs"][0]["status"], "ok")
        for variant in ("missing", "mc", "p1", "p2"):
            tm, r = rec(), request()
            if variant == "missing":
                del tm["mode"]
            elif variant == "mc":
                tm["mode"] = "mc"
            elif variant == "p1":
                del r["p1"]["candidates"][0]["mode"]
            else:
                r["p2"]["mode"] = "mc"
            with self.assertRaises(ValueError):
                TypedMissionSampleFeed(vehicle()).tick(1, tm, r)

    def test_sequence_and_time_errors_do_not_consume(self):
        f = TypedMissionSampleFeed(vehicle())
        f.tick(1, rec(), request())
        for seq, tm in ((1, rec(2)), (True, rec(2)), (2, rec(1)), (2, rec(0))):
            with self.assertRaises(ValueError):
                f.tick(seq, tm, request())
        self.assertEqual(f.tick(2, rec(2), request())["sequence"], 2)

    def test_finite_measured_values_and_missing_fields(self):
        for field, value in (("battery_pct", True), ("wind_mps", -1), ("lat", 76), ("t_s", float("inf")), ("alt", None)):
            tm = rec()
            tm[field] = value
            with self.assertRaises(ValueError):
                TypedMissionSampleFeed(vehicle()).tick(1, tm, request())
        tm = rec()
        del tm["wind_from"]
        with self.assertRaises(ValueError):
            TypedMissionSampleFeed(vehicle()).tick(1, tm, request())

    def test_constructor_bounds(self):
        for kwargs in ({"raise_ticks": True}, {"clear_ticks": 0}, {"max_gap_s": 0}, {"max_gap_s": float("nan")}):
            with self.assertRaises(ValueError):
                TypedMissionSampleFeed(vehicle(), **kwargs)
        with self.assertRaises(ValueError):
            TypedMissionSampleFeed(load_airframe("x500"))

    def test_detached_vehicle_request_and_result(self):
        v, r, tm = vehicle(), request(), rec(1, 0)
        f = TypedMissionSampleFeed(v, 2, 2)
        before = json.dumps([r, tm], sort_keys=True)
        o = f.tick(1, tm, r)
        self.assertEqual(json.dumps([r, tm], sort_keys=True), before)
        r["p2"]["target"]["tolerance_m"] = 50
        o["predictors"]["P2"]["raise_streak"] = 999
        v.airframe_profile["uncertainty"]["wind_mps"] = 8
        self.assertIs(f.tick(2, rec(2, 0), request())["predictors"]["P2"]["active"], True)

    def test_repeated_unknown_then_known(self):
        f = TypedMissionSampleFeed(vehicle(), 2, 2)
        r = request()
        r["p2"]["probes"][0]["return_events"] = [{"kind": "landing"}]
        self.assertEqual(kinds(f.tick(1, rec(), r), "P2"), ["unknown"])
        o = f.tick(2, rec(2), r)
        self.assertEqual(kinds(o, "P2"), [])
        self.assertIsNone(o["predictors"]["P2"]["active"])
        self.assertEqual(kinds(f.tick(3, rec(3), request()), "P2"), ["known"])

    def test_p2_future_deficit_is_not_immediate_emergency(self):
        o = TypedMissionSampleFeed(vehicle(), 1, 1).tick(1, rec(1, 0), request())
        self.assertEqual(o["predictors"]["P1"]["finding"]["severity"], 2)
        self.assertEqual(o["predictors"]["P2"]["finding"]["severity"], 4)
        self.assertIsNone(o["predictors"]["P2"]["finding"]["lead_s"])

    def test_no_continuous_boundary_or_action_authority(self):
        for o in (TypedMissionSampleFeed(vehicle()).tick(1, rec(), request()), TypedMissionSampleFeed(vehicle(), 1, 1).tick(1, rec(1, 0), request())):
            for k in ("continuous_boundary_known", "return_now_evaluated", "recovery_reference_verified", "telemetry_freshness_verified", "landing_modeled", "feasible", "executable"):
                self.assertIs(o[k], False)
            self.assertIsNone(o["latest_return_deadline_s"])
            self.assertIsNone(o["rule_choice"])
            self.assertEqual(o["candidates"], [])
            for e in o["events"]:
                self.assertIsNone(e["lead_s"])
                self.assertIsNone(e["latest_return_deadline_s"])
                self.assertIs(e["continuous_boundary_known"], False)
                self.assertIs(e["executable"], False)

    def test_request_shapes_reject_unversioned_extras(self):
        for key in ("mission_version", "recovery_reference_id", "p1", "p2"):
            r = request()
            del r[key]
            with self.assertRaises(ValueError):
                TypedMissionSampleFeed(vehicle()).tick(1, rec(), r)
        for value in ("", "bad space", "x\n", True):
            r = request()
            r["mission_version"] = value
            with self.assertRaises(ValueError):
                TypedMissionSampleFeed(vehicle()).tick(1, rec(), r)

    def test_different_reference_is_unverified_after_reset(self):
        o = vectors()["traces"][7]["outputs"][1]
        self.assertEqual(o["recovery_reference_id"], "site:alternate")
        self.assertIs(o["recovery_reference_verified"], False)


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False, sort_keys=True))
    else:
        unittest.main()
