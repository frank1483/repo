"""python3 -m unittest gcs_demo.alerts.test_alerts"""
import unittest

from . import explain, sim
from .energy_api import Wind, default_vehicle, leg_energy, rtl_energy
from .predict import linfit


class FakeBackend:
    name = "fake"

    def __init__(self, data, ok=True):
        self.data, self.ok = data, ok

    def complete_json(self, system, user, schema, timeout_s=60):
        return {"ok": self.ok, "data": self.data, "raw": str(self.data), "latency_s": 0.01,
                "error": None if self.ok else "boom"}


EV = {
    "title": "電量不足以飛完航線", "value": "預估落地 5%", "lead_s": None, "rule_choice": "C3",
    "evidence": [{"id": "E1", "text": "預估落地", "value": "5.0%"}, {"id": "E2", "text": "保留", "value": "20%"}],
    "candidates": [
        {"id": "C1", "action": "A_CONTINUE", "label": "繼續", "end_pct": 5.0, "completion_pct": 100, "feasible": False},
        {"id": "C3", "action": "A_RTL_AFTER_WP", "label": "飛完 WP13 後返航", "end_pct": 22.0, "completion_pct": 76, "feasible": True},
        {"id": "C4", "action": "A_RTL_NOW", "label": "立即返航", "end_pct": 40.0, "completion_pct": 30, "feasible": True},
    ],
}


class EnergyTests(unittest.TestCase):
    def test_headwind_costs_more(self):
        v = default_vehicle()
        tail = leg_energy(v, (0, 0, 60), (2000, 0, 60), Wind(8, 270))   # 西風 → 往東順風
        head = leg_energy(v, (0, 0, 60), (2000, 0, 60), Wind(8, 90))
        self.assertLess(tail["energy_wh"], head["energy_wh"])
        self.assertGreater(rtl_energy((2000, 0, 60), (0, 0, 0), v, Wind(8, 270))["energy_wh"],
                           rtl_energy((2000, 0, 60), (0, 0, 0), v, Wind(8, 90))["energy_wh"])

    def test_linfit(self):
        b, a, r2 = linfit([0, 1, 2, 3], [1, 3, 5, 7])
        self.assertAlmostEqual(b, 2)
        self.assertAlmostEqual(a, 1)
        self.assertAlmostEqual(r2, 1)


class ExplainTests(unittest.TestCase):
    def test_valid_llm_choice_kept(self):
        d = {"decision": "SELECT", "choice_id": "C4", "reason_zh": "x", "evidence_ids": ["E1", "E9"],
             "summary_zh": "預估落地 5%，建議返航。"}
        r = explain.explain(EV, FakeBackend(d))
        self.assertEqual(r["source"], "llm")
        self.assertEqual(r["text"]["choice_id"], "C4")
        self.assertEqual(r["text"]["evidence_ids"], ["E1"])
        self.assertFalse(r["text"]["rule_agrees"])

    def test_infeasible_choice_falls_back(self):
        d = {"decision": "SELECT", "choice_id": "C1", "reason_zh": "x", "evidence_ids": ["E1"], "summary_zh": "繼續"}
        r = explain.explain(EV, FakeBackend(d))
        self.assertEqual((r["source"], r["text"]["choice_id"]), ("rule", "C3"))

    def test_unknown_id_and_made_up_number_fall_back(self):
        d = {"decision": "SELECT", "choice_id": "C9", "reason_zh": "x", "evidence_ids": [], "summary_zh": "a"}
        self.assertEqual(explain.explain(EV, FakeBackend(d))["source"], "rule")
        d = {"decision": "SELECT", "choice_id": "C3", "reason_zh": "x", "evidence_ids": ["E1"], "summary_zh": "剩 63%"}
        self.assertIn("63", explain.explain(EV, FakeBackend(d))["fallback_reason"])

    def test_backend_down_still_alerts(self):
        r = explain.explain(EV, FakeBackend(None, ok=False))
        self.assertEqual(r["source"], "rule")
        self.assertIn("飛完 WP13 後返航", r["text"]["summary_zh"])


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ignore = sim.run(policy="ignore")
        cls.follow = sim.run(policy="follow")

    def test_predicts_shortfall_well_ahead(self):
        first = next(e for e in self.ignore["events"] if e["key"] == "battery_route" and e["type"] == "raise")
        # 落地前 8 分鐘以上就發現，而照飛的結果確實低於保留值
        self.assertGreater(self.ignore["summary"]["flight_s"] - first["t"], 480)
        self.assertLess(self.ignore["summary"]["landed_true_pct_of_nominal"], 20)

    def test_following_advice_keeps_reserve(self):
        self.assertTrue(self.follow["applied"])
        self.assertGreaterEqual(self.follow["summary"]["landed_true_pct_of_nominal"], 20)

    def test_detects_aged_battery(self):
        self.assertTrue(any(e["key"] == "battery_capacity" for e in self.ignore["events"]))

    def test_calm_flight_is_quiet(self):
        r = sim.run(scenario="calm", policy="ignore")
        keys = {e["key"] for e in r["events"]}
        self.assertNotIn("rtl_point", keys)
        self.assertNotIn("battery_route", keys)          # 電夠的任務不誤報
        self.assertGreaterEqual(r["summary"]["landed_true_pct_of_nominal"], 20)
        self.assertNotIn("wind_trend", keys)


if __name__ == "__main__":
    unittest.main()
