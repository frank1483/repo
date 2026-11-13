"""python3 -m unittest gcs_demo.alerts.test_alerts"""
import unittest

from . import explain, sim
from .slot_test_helpers import SlotBackend
from .test_v5_explain_fixtures import event, answer
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

EV = event(EV)
EV["evidence"][0].update(option_id="C4", value="40.0%")


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
        # review_0305 第 8 項後，引用必須全部存在：混合 [E1,E9] 改為退回規則（原斷言保留 E1 已作廢）
        # 範本句＋選格：模型選 C4，依據 E1（屬於 C4 的落地電量），句子由程式寫
        r = explain.explain(EV, SlotBackend(lambda cs, user: "C4" if "C4" in cs else cs[0]))
        self.assertEqual(r["source"], "llm", r["fallback_reason"])
        self.assertEqual(r["text"]["choice_id"], "C4")
        self.assertEqual(r["text"]["evidence_ids"], ["E1"])
        self.assertIn("C4 預估落地 40.0%", r["text"]["sentences"][0])
        self.assertFalse(r["text"]["rule_agrees"])
        d = answer(EV, "C4", ["C4 預估落地 40.0%。", "請操作員評估返航。"])
        self.assertIsNotNone(explain.validate(dict(d, evidence_ids=["E1", "E9"]), EV))

    def test_infeasible_choice_falls_back(self):
        d = answer(EV, "C1")
        r = explain.explain(EV, FakeBackend(d))
        self.assertEqual((r["source"], r["text"]["choice_id"]), ("rule", "C3"))

    def test_unknown_id_and_made_up_number_fall_back(self):
        r = explain.explain(EV, SlotBackend(raw='{"value":"C9"}'))   # 不在清單：修正一次仍錯 → 規則
        self.assertEqual(r["source"], "rule")
        self.assertIn("C9", r["fallback_reason"])
        d = answer(EV, "C3", ["C3 落地 63%。", "請注意。"])
        self.assertIn("63", explain.validate(d, EV))

    def test_simplified_or_field_names_fall_back(self):
        d = answer(EV, "C3", ["电量不足以完成原航线，建议返航。", "請注意。"])
        self.assertEqual(explain.validate(d, EV), "說明用了簡體字")
        d["sentences"] = ["建議返航。", "missed_required 為 0"]
        self.assertEqual(explain.validate(d, EV), "說明寫出內部欄位名稱")

    def test_backend_down_still_alerts(self):
        r = explain.explain(EV, FakeBackend(None, ok=False))
        self.assertEqual(r["source"], "rule")
        self.assertIn("飛完 WP13 後返航", r["text"]["summary_zh"])


class PriorityTests(unittest.TestCase):
    def test_rule_keeps_required_targets(self):
        from .predict import PredictiveAlertEngine
        cands = [
            {"id": "C1", "action": "A_CONTINUE", "end_pct": 15, "completion_pct": 100, "feasible": False},
            {"id": "C3", "action": "A_RTL_AFTER_WP", "end_pct": 25, "completion_pct": 80, "missed_required": 1, "feasible": True},
            {"id": "C6", "action": "A_SKIP_OPTIONAL", "end_pct": 23, "completion_pct": 60, "missed_required": 0, "feasible": True},
            {"id": "C4", "action": "A_RTL_NOW", "end_pct": 40, "completion_pct": 20, "missed_required": 2, "feasible": True},
        ]
        self.assertEqual(PredictiveAlertEngine._rule_pick(cands), "C6")

    def test_skip_optional_candidate(self):
        from .predict import PredictiveAlertEngine, Telemetry
        route = [(0, 0, 60), (1500, 0, 60), (3000, 0, 60), (3000, 1500, 60)]
        eng = PredictiveAlertEngine(route, (0, 0, 0), default_vehicle(), priorities=[1, 2, 1, 2])
        tm = Telemetry(t=0, pos=(100, 0, 60), vel=(12, 0, 0), soc_pct=30, voltage=22.0, current_a=40,
                       used_wh=340, cell_count=6, next_wp=1, link_pct=90, wind=Wind(5, 90))
        eng.update(tm)
        cands = eng._candidates(tm, eng._remaining(tm), eng._walk(eng._remaining(tm), eng._vehicle(), tm.wind),
                                146.0, 97.6, None, tm.wind)
        c6 = next(c for c in cands if c["action"] == "A_SKIP_OPTIONAL")
        self.assertEqual(c6["param"], [2])
        self.assertEqual(next(c for c in cands if c["id"] == "C4")["missed_required"], 1)


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ignore = sim.run(policy="ignore")
        cls.follow = sim.run(policy="follow")

    def test_predicts_shortfall_well_ahead(self):
        first = next(e for e in self.ignore["events"] if e["key"] == "battery" and e["type"] == "raise")
        # 落地前 8 分鐘以上就發現，而照飛的結果確實低於保留值
        self.assertGreater(self.ignore["summary"]["flight_s"] - first["t"], 480)
        self.assertLess(self.ignore["summary"]["landed_true_pct_of_nominal"], 20)

    def test_following_advice_keeps_reserve(self):
        self.assertTrue(self.follow["applied"])
        self.assertGreaterEqual(self.follow["summary"]["landed_true_pct_of_nominal"], 20)

    def test_detects_aged_battery(self):
        self.assertTrue(any(frame.get("battery_members", {}).get("P3", {}).get("truth") == "TRUE"
                            for frame in self.ignore["frames"]))

    def test_calm_flight_is_quiet(self):
        r = sim.run(scenario="calm", policy="ignore")
        keys = {e["key"] for e in r["events"]}
        self.assertNotIn("rtl_point", keys)
        # Capacity (P3) can still warn; route-energy members must stay quiet.
        samples = [frame["battery_members"] for frame in r["frames"]
                   if frame.get("battery_members")]
        self.assertTrue(samples)  # do not pass vacuously if instrumentation is lost
        for members in samples:
            for predictor in ("P1", "P2"):
                self.assertIn(predictor, members)
                self.assertNotEqual(members[predictor]["truth"], "TRUE", predictor)
        self.assertGreaterEqual(r["summary"]["landed_true_pct_of_nominal"], 20)
        self.assertNotIn("wind_trend", keys)


if __name__ == "__main__":
    unittest.main()
