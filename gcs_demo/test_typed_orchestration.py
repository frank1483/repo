"""NEW composition controls. Claude owns first functional execution."""
import copy
import json
import sys
import unittest
from dataclasses import replace

from .energy import load_airframe
from .alerts.typed_orchestration import TypedMissionOrchestrator
from .alerts.typed_mission_feed import TypedMissionSampleFeed
from .alerts.typed_capacity_feed import TypedCapacityFeed


def vehicle(name="fw_example"):
    v = load_airframe(name)
    p = copy.deepcopy(v.airframe_profile)
    p["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
    return replace(v, battery_wh=100, airframe_profile=p)


def options():
    return {"cell_r_ohm": 0.004, "cell_empty_v": 3.55, "min_samples": 3}


def request(version="v1", session="session:one"):
    pose = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}
    arc = {"kind": "arc", "v_air": 16.0, "angle_deg": 180.0, "clockwise": True, "radius_m": 40.0}
    return {"capacity_session_id": session, "mission": {
        "mission_version": version, "recovery_reference_id": "site:home",
        "p1": {"current_id": "current", "candidates": [{"id": "current", "entry": pose,
                "events": [copy.deepcopy(arc) for _ in range(4)], "mode": "fw"}]},
        "p2": {"target": {"lat": 23.0, "lon": 120.0, "alt": 80.0, "tolerance_m": 0.001},
               "probes": [{"id": "A", "outbound_events": [copy.deepcopy(arc)], "return_events": [copy.deepcopy(arc)]}], "mode": "fw"}}}


def measurement(i, pct=90, t=None):
    t = i if t is None else t
    used = 5 * i
    return {"mission": {"t_s": t, "lat": 23.0, "lon": 120.0, "alt": 80.0,
                        "air_heading_deg": 0.0, "battery_pct": pct, "wind_mps": 0, "wind_from": 0, "mode": "fw"},
            "capacity": {"t_s": t, "battery_id": "battery:one", "used_wh": used,
                         "voltage": (4.2 - 0.65 / 80 * used - 5 * 0.004) * 4,
                         "current_a": 5, "cell_count": 4, "battery_pct": pct}}


def feed(name="fw_example"):
    return TypedMissionOrchestrator(vehicle(name), options(), 2, 2, 30, 3)


def summary(out):
    o = copy.deepcopy(out)
    # Full outputs elsewhere are checked against standalone feeds. Cross-
    # language comparison retains new control fields and numerical summaries;
    # legacy verbose backend comparison/scenario prose is excluded explicitly.
    del o["predictors"]["P1"]["snapshot"]["comparison"]
    for probe in o["predictors"]["P2"]["snapshot"]["probes"]:
        del probe["bounds"]
        for scenario in probe["scenarios"]:
            scenario.pop("reason", None)
    return o


def vectors():
    cases = []
    for name in ("warmup_latch", "capacity_reject", "mission_reject", "version_only", "session_and_version", "gap", "time_mismatch", "unknown_geometry", "hybrid"):
        steps = [{"sequence": i, "measurement": measurement(i), "request": request()} for i in range(4)]
        s = {"sequence": 4, "measurement": measurement(4), "request": request()}
        if name == "warmup_latch":
            steps += [{"sequence": i, "measurement": measurement(i, 0), "request": request()} for i in (4, 5)]
        elif name in ("capacity_reject", "mission_reject", "time_mismatch"):
            bad = copy.deepcopy(s)
            if name == "capacity_reject":
                bad["measurement"]["capacity"]["current_a"] = -1
            elif name == "mission_reject":
                bad["request"]["mission"]["p2"]["probes"][0]["outbound_events"] = []
            else:
                bad["measurement"]["capacity"]["t_s"] = 5
            steps += [bad, s]
        elif name == "version_only":
            s["request"] = request("v2")
            steps.append(s)
        elif name == "session_and_version":
            s["request"] = request("v2", "session:two")
            s["measurement"] = measurement(0, t=4)
            s["measurement"]["capacity"]["battery_id"] = "battery:two"
            steps.append(s)
        elif name == "gap":
            s["measurement"] = measurement(4, t=34)
            steps.append(s)
        elif name == "unknown_geometry":
            s["request"]["mission"]["p2"]["probes"][0]["return_events"] = [{"kind": "landing"}]
            steps.append(s)
        else:
            steps.append(s)
        airframe = "vtol_example" if name == "hybrid" else "fw_example"
        f, outputs = feed(airframe), []
        for step in steps:
            try:
                out = f.tick(step["sequence"], step["measurement"], step["request"])
            except ValueError:
                outputs.append({"error": True})
            else:
                outputs.append({"output": summary(out)})
        rejected = [i for i, out in enumerate(outputs) if "error" in out]
        expected = [4] if name in ("capacity_reject", "mission_reject", "time_mismatch") else []
        if rejected != expected:
            raise AssertionError("unexpected vector rejection positions: " + name + " " + str(rejected))
        cases.append({"name": name, "airframe": airframe, "steps": steps, "outputs": outputs})
    return {"contract": "typed_orchestration_P1_P2_P3_v1", "cases": cases}


class TestTypedOrchestration(unittest.TestCase):
    def test_initial_unknown_keeps_each_status(self):
        o = feed().tick(0, measurement(0), request())
        self.assertEqual(o["status"], "unknown")
        self.assertEqual(o["predictors"]["P1"]["status"], "ok")
        self.assertEqual(o["predictors"]["P2"]["status"], "ok")
        self.assertIsNone(o["predictors"]["P3"]["active"])
        self.assertEqual(o["unassessed_predictors"], ["P4", "P5"])

    def test_exact_standalone_outputs_and_order(self):
        f, a, b = feed(), TypedMissionSampleFeed(vehicle(), 2, 2, 30), TypedCapacityFeed(vehicle(), options(), 2, 2, 3)
        for i in range(6):
            m, r = measurement(i, 90 if i < 4 else 0), request()
            o = f.tick(i, m, r)
            ma, ca = a.tick(i, m["mission"], r["mission"]), b.tick(i, m["capacity"], r["capacity_session_id"])
            self.assertEqual(o["predictors"], {"P1": ma["predictors"]["P1"], "P2": ma["predictors"]["P2"], "P3": ca})
            self.assertEqual([e["predictor"] for e in o["events"]], [e["predictor"] for e in ma["events"] + ca["events"]])

    def test_p3_late_reject_rolls_back_p1_p2(self):
        f, clean = feed(), feed()
        for i in range(4):
            f.tick(i, measurement(i), request())
            clean.tick(i, measurement(i), request())
        bad = measurement(4, 0)
        bad["capacity"]["current_a"] = -1
        with self.assertRaises(ValueError):
            f.tick(4, bad, request())
        self.assertEqual(f.tick(4, measurement(4, 0), request()), clean.tick(4, measurement(4, 0), request()))

    def test_p2_reject_does_not_consume_p3(self):
        f, clean = feed(), feed()
        bad = request()
        bad["mission"]["p2"]["probes"][0]["outbound_events"] = []
        with self.assertRaises(ValueError):
            f.tick(0, measurement(0), bad)
        self.assertEqual(f.tick(0, measurement(0), request()), clean.tick(0, measurement(0), request()))

    def test_shared_time_and_soc_are_required(self):
        for k in ("t_s", "battery_pct"):
            f, m = feed(), measurement(0)
            m["capacity"][k] += 1
            with self.assertRaises(ValueError):
                f.tick(0, m, request())
            self.assertEqual(f.tick(0, measurement(0), request())["sequence"], 0)

    def test_session_change_requires_version(self):
        f = feed()
        f.tick(0, measurement(0), request())
        with self.assertRaises(ValueError):
            f.tick(1, measurement(1), request(session="session:two"))
        o = f.tick(1, measurement(1), request("v2", "session:two"))
        self.assertEqual(o["reset_reasons_by_predictor"], {"P1": ["mission_version_changed"], "P2": ["mission_version_changed"], "P3": ["session_changed"]})
        self.assertFalse(any(e["type"] == "resolve" for e in o["events"]))

    def test_version_change_preserves_capacity_history(self):
        f = feed()
        f.tick(0, measurement(0), request())
        o = f.tick(1, measurement(1), request("v2"))
        self.assertEqual(o["predictors"]["P3"]["window_sample_count"], 2)
        self.assertEqual(o["reset_reasons_by_predictor"]["P3"], [])

    def test_new_battery_atomic_failure_then_retry(self):
        f = feed()
        f.tick(0, measurement(0), request())
        m = measurement(1)
        m["capacity"]["battery_id"] = "battery:two"
        with self.assertRaises(ValueError):
            f.tick(1, m, request("v2"))
        o = f.tick(1, m, request("v2", "session:two"))
        self.assertEqual(o["battery_id"], "battery:two")
        self.assertEqual(o["predictors"]["P3"]["window_sample_count"], 1)

    def test_gap_resets_all_without_resolve(self):
        f = feed()
        for i in range(4):
            f.tick(i, measurement(i), request())
        o = f.tick(4, measurement(4, t=34), request())
        self.assertTrue(all(v == ["telemetry_gap"] for v in o["reset_reasons_by_predictor"].values()))
        self.assertEqual(o["predictors"]["P3"]["window_sample_count"], 1)
        self.assertFalse(any(e["type"] == "resolve" for e in o["events"]))

    def test_gap_equality_does_not_reset(self):
        f = feed()
        f.tick(0, measurement(0), request())
        o = f.tick(1, measurement(1, t=30), request())
        self.assertTrue(all(v == [] for v in o["reset_reasons_by_predictor"].values()))

    def test_unknown_geometry_does_not_hide_other_predictors(self):
        f = feed()
        for i in range(3):
            f.tick(i, measurement(i), request())
        r = request()
        r["mission"]["p2"]["probes"][0]["return_events"] = [{"kind": "landing"}]
        o = f.tick(3, measurement(3), r)
        self.assertEqual(o["predictors"]["P2"]["status"], "unknown")
        self.assertEqual(o["predictors"]["P1"]["status"], "ok")
        self.assertEqual(o["predictors"]["P3"]["status"], "ok")
        self.assertFalse(any(e["type"] == "resolve" and e["predictor"] == "P2" for e in o["events"]))

    def test_copy_isolation(self):
        v, cfg = vehicle(), options()
        f = TypedMissionOrchestrator(v, cfg, 2, 2, 30, 3)
        cfg["min_samples"] = 601
        v.airframe_profile["uncertainty"]["power_pct"] = 100
        m, r = measurement(0), request()
        before = copy.deepcopy((m, r))
        o = f.tick(0, m, r)
        self.assertEqual((m, r), before)
        o["predictors"]["P3"]["snapshot"]["assumptions"]["min_samples"] = 601
        r["mission"]["p2"]["target"]["lat"] = 24
        f.tick(1, measurement(1), request())
        self.assertEqual(f.tick(2, measurement(2), request())["predictors"]["P3"]["status"], "ok")

    def test_exact_envelopes_and_sequence_reject(self):
        for m, r in (({**measurement(0), "extra": 1}, request()), (measurement(0), {**request(), "extra": 1}), ({"mission": measurement(0)["mission"]}, request())):
            with self.assertRaises(ValueError):
                feed().tick(0, m, r)
        f = feed()
        f.tick(0, measurement(0), request())
        with self.assertRaises(ValueError):
            f.tick(0, measurement(1), request())
        self.assertEqual(f.tick(1, measurement(1), request())["sequence"], 1)

    def test_event_context_and_limit_flags(self):
        o = feed("vtol_example").tick(0, measurement(0), request())
        for e in o["events"]:
            for key in ("sequence", "mission_version", "recovery_reference_id", "session_id", "battery_id"):
                self.assertEqual(e[key], o[key])
        for key in ("continuous_boundary_known", "return_now_evaluated", "recovery_reference_verified", "telemetry_freshness_verified", "measured_capacity", "sensor_validated", "independent_window_evidence", "energy_correction_applied", "landing_modeled", "feasible", "executable"):
            self.assertIs(o[key], False)
        self.assertIsNone(o["latest_return_deadline_s"])
        self.assertIsNone(o["rule_choice"])
        self.assertEqual(o["candidates"], [])


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False, ensure_ascii=True))
    else:
        unittest.main()
