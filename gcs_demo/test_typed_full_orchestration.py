"""NEW P4/P5 composition controls; Claude owns first Python execution.

The prior test module supplies fixtures only; its old tests are not selected.
"""
import copy
import unittest
from unittest.mock import patch

from .alerts import typed_full_orchestration as full
from .alerts.typed_link import TypedLinkDistancePredictor
from .alerts.typed_orchestration import TypedMissionOrchestrator
from .alerts.typed_wind import TypedWindTrendPredictor
from .test_typed_orchestration import vehicle, options, request, measurement


LINK_OPTIONS = {"min_samples": 3, "min_distance_span_m": 100}
WIND_OPTIONS = {"min_samples": 3, "min_span_s": 2}


def full_request(version="v1", session="session:one"):
    return {**request(version, session), "link": {"reference_id": "radio:home",
            "probes": [{"id": "probe:A", "distance_m": 200, "eta_s": 10}]}}


def full_measurement(i):
    m = measurement(i)
    m["mission"]["wind_mps"] = i
    m["link"] = {"t_s": i, "distance_m": i * 100, "link_pct": 90 - i * 10}
    m["wind"] = {"t_s": i, "wind_mps": i}
    return m


def feed():
    return full.TypedFullMissionOrchestrator(
        vehicle(), options(), "radio:home", LINK_OPTIONS, WIND_OPTIONS, 2, 2, 30, 3)


class FullOrchestrationTests(unittest.TestCase):
    def paired(self):
        f, control = feed(), feed()
        for i in range(3):
            self.assertEqual(f.tick(i, full_measurement(i), full_request()),
                             control.tick(i, full_measurement(i), full_request()))
        return f, control

    def check_retry(self, f, control):
        self.assertEqual(f.tick(3, full_measurement(3), full_request()),
                         control.tick(3, full_measurement(3), full_request()))

    def test_matches_all_standalone_predictors(self):
        f = feed()
        old = TypedMissionOrchestrator(vehicle(), options(), 2, 2, 30, 3)
        link = TypedLinkDistancePredictor(vehicle(), "radio:home", LINK_OPTIONS, 2, 2)
        wind = TypedWindTrendPredictor(vehicle(), WIND_OPTIONS, 2, 2)
        for i in range(4):
            m, r = full_measurement(i), full_request()
            out = f.tick(i, m, r)
            a = old.tick(i, {k: m[k] for k in ("mission", "capacity")},
                         {k: r[k] for k in ("mission", "capacity_session_id")})
            for key in ("P1", "P2", "P3"):
                self.assertEqual(out["predictors"][key], a["predictors"][key])
            self.assertEqual(out["predictors"]["P4"], link.tick(i, m["link"], r["link"]["probes"], "v1"))
            self.assertEqual(out["predictors"]["P5"], wind.tick(i, m["wind"], "v1"))
            self.assertEqual(out["evaluated_predictors"], ["P1", "P2", "P3", "P4", "P5"])
            self.assertEqual(out["unassessed_predictors"], [])
            self.assertFalse(out["feasible"] or out["executable"] or out["energy_correction_applied"])
            self.assertEqual(out["candidates"], [])

    def test_late_p4_rejection_is_atomic(self):
        f, c = self.paired()
        m = full_measurement(3)
        m["link"]["link_pct"] = 101
        with self.assertRaises(ValueError):
            f.tick(3, m, full_request())
        self.check_retry(f, c)

    def test_late_p5_rejection_is_atomic(self):
        f, c = self.paired()
        with patch.object(TypedWindTrendPredictor, "tick", side_effect=ValueError("P5 injected")):
            with self.assertRaisesRegex(ValueError, "P5 injected"):
                f.tick(3, full_measurement(3), full_request())
        self.check_retry(f, c)

    def test_final_snapshot_rejection_is_atomic(self):
        f, c = self.paired()
        original = full._snapshot
        def reject_output(value):
            if value.get("caller_scope") == "atomic_measured_P1_P2_P3_P4_P5_only":
                raise ValueError("serialization injected")
            return original(value)
        with patch.object(full, "_snapshot", side_effect=reject_output):
            with self.assertRaisesRegex(ValueError, "serialization injected"):
                f.tick(3, full_measurement(3), full_request())
        self.check_retry(f, c)

    def test_common_time_rejection_is_atomic(self):
        f, c = self.paired()
        m = full_measurement(3)
        m["wind"]["t_s"] = 4
        with self.assertRaisesRegex(ValueError, "identical measured t_s"):
            f.tick(3, m, full_request())
        self.check_retry(f, c)

    def test_common_wind_rejection_is_atomic(self):
        f, c = self.paired()
        m = full_measurement(3)
        m["wind"]["wind_mps"] = 4
        with self.assertRaisesRegex(ValueError, "identical measured wind_mps"):
            f.tick(3, m, full_request())
        self.check_retry(f, c)

    def test_reference_change_rejected_without_consuming_tick(self):
        f, c = self.paired()
        r = full_request()
        r["link"]["reference_id"] = "radio:other"
        with self.assertRaisesRegex(ValueError, "new caller"):
            f.tick(3, full_measurement(3), r)
        self.check_retry(f, c)

    def test_battery_session_still_requires_new_mission_version(self):
        f, c = self.paired()
        with self.assertRaisesRegex(ValueError, "new mission_version"):
            f.tick(3, full_measurement(3), full_request(session="session:two"))
        self.check_retry(f, c)

    def test_mission_version_resets_p4_and_p5(self):
        f, _ = self.paired()
        out = f.tick(3, full_measurement(3), full_request("v2"))
        for key in ("P4", "P5"):
            self.assertEqual(out["reset_reasons_by_predictor"][key], ["mission_version_changed"])
            self.assertIsNone(out["predictors"][key]["active"])
            self.assertTrue(all(e["mission_version"] == "v2" for e in out["predictors"][key]["events"]))

    def test_output_and_input_are_detached(self):
        f, c = feed(), feed()
        m, r = full_measurement(0), full_request()
        before = copy.deepcopy((m, r))
        out = f.tick(0, m, r)
        c.tick(0, full_measurement(0), full_request())
        self.assertEqual((m, r), before)
        out["predictors"]["P4"]["events"].clear()
        m["link"]["distance_m"] = 9999
        r["link"]["probes"].clear()
        self.assertEqual(f.tick(1, full_measurement(1), full_request()), c.tick(1, full_measurement(1), full_request()))

    def test_unsupported_probe_is_unknown_not_clearance(self):
        f, _ = self.paired()
        r = full_request()
        r["link"]["probes"][0]["distance_m"] = 9999
        out = f.tick(3, full_measurement(3), r)
        self.assertEqual(out["predictors"]["P4"]["status"], "unknown")
        self.assertIsNone(out["predictors"]["P4"]["active"])
        self.assertFalse(out["executable"])
        self.assertFalse(any(e["type"] == "resolve" for e in out["predictors"]["P4"]["events"]))

    def test_warmup_preserves_unknown(self):
        out = feed().tick(0, full_measurement(0), full_request())
        self.assertEqual(out["status"], "unknown")
        for key in ("P3", "P4", "P5"):
            self.assertEqual(out["predictors"][key]["status"], "unknown")
        self.assertIsNone(out["latest_return_deadline_s"])
        self.assertFalse(out["continuous_boundary_known"])


if __name__ == "__main__":
    unittest.main()
