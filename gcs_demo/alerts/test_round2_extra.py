"""Claude 的新增離線驗收草稿；Codex 未執行。以交付三檔覆蓋來源複本後執行。

python -m unittest discover -s <round2>/verification -p test_round2_extra.py
不呼叫模型；不改原 13/16 項測試。舊混合引用斷言衝突見 review_0309.md。
"""
import unittest
from unittest.mock import patch

from gcs_demo.alerts import explain, sim
from gcs_demo.alerts.energy_api import Wind, default_vehicle
from gcs_demo.alerts.predict import Config, Finding, PredictiveAlertEngine, Telemetry

ROUTE = [(i * 500.0, 0.0, 60.0) for i in range(5)]


def telemetry(t=0.0, next_wp=1, used=90.0, wind=3.0):
    return Telemetry(t, (100.0, 0.0, 60.0), (12.0, 0.0, 0.0), 80.0, 23.0, 40.0,
                     used, 6, next_wp, 90.0, Wind(wind, 90.0))


def engine(route=ROUTE, config=None):
    return PredictiveAlertEngine(route, (0, 0, 0), default_vehicle(), config)


class Round2Extra(unittest.TestCase):
    def test_empty_route_still_reports_wind(self):
        eng = engine([])
        evs = sum((eng.update(telemetry(t=i, next_wp=0, wind=15)) for i in range(3)), [])
        self.assertTrue(any(e["key"] == "wind_trend" and e["type"] == "raise" for e in evs))
        self.assertFalse(any(e["key"] in ("battery_route", "rtl_point") for e in evs))

    def test_predictor_exception_isolated_and_recorded(self):
        eng = engine()
        with patch.object(eng, "_battery_route", side_effect=RuntimeError("injected")):
            evs = sum((eng.update(telemetry(t=i, wind=15)) for i in range(3)), [])
        self.assertEqual(eng.last_state["predictor_errors"]["battery_route"], "RuntimeError")
        self.assertEqual(eng.last_state["data_status"], "partial")
        self.assertTrue(any(e["key"] == "wind_trend" for e in evs))

    def test_invalid_input_does_not_resolve_existing_alert(self):
        eng = engine()
        for i in range(3):
            eng.update(telemetry(t=i, wind=15))
        bad = telemetry(t=4)
        bad.cell_count = 0
        self.assertEqual(eng.update(bad), [])
        self.assertIn("wind_trend", eng.active())
        self.assertEqual(eng.last_state["data_status"], "insufficient")

    def test_real_candidate_rounding_and_active_threshold(self):
        eng = engine()
        tm = telemetry()
        path = eng._remaining(tm)
        walk = [(i, 0.0, 0.0, 0.0) for i in range(len(path))]
        cands = eng._candidates(tm, path, walk, eng.v.battery_wh * 0.1996, 97.6, None, tm.wind)
        rtl = next(c for c in cands if c["action"] == "A_RTL_NOW")
        self.assertEqual(rtl["end_pct"], 20.0)
        self.assertFalse(rtl["energy_feasible"])
        eng._active["battery_route"] = Finding("battery_route", active=True)
        self.assertFalse(eng._is_feasible(21.96))
        self.assertTrue(eng._is_feasible(22.0))

    def test_voltage_reset_and_time_window(self):
        eng = engine()
        eng._available_wh(telemetry(t=1, used=100))
        eng._available_wh(telemetry(t=2, used=99))
        self.assertEqual(len(eng._cell_hist), 1)
        eng._available_wh(telemetry(t=603, used=101))
        self.assertEqual(len(eng._cell_hist), 1)
        self.assertEqual(eng._cell_hist[0][0], 603)

    def test_sparse_reordered_route_counts_unique_original_ids(self):
        eng = engine()
        eng.update(telemetry(next_wp=2))
        eng.set_route([ROUTE[4], ROUTE[0], ROUTE[4]], indices=[4, 0, 4])
        eng.update(telemetry(t=1, next_wp=0))
        self.assertEqual(eng._reached, {0, 1})
        self.assertEqual(eng._completion(eng.route_idx), 60.0)

    def test_emergency_rtl_threshold_is_configurable(self):
        cands = [{"id": "R", "action": "A_RTL_NOW", "end_pct": 12, "feasible": False},
                 {"id": "L", "action": "A_LAND_NOW", "end_pct": 15, "feasible": False}]
        eng = engine(config=Config(emergency_rtl_min_pct=13))
        self.assertEqual(eng._rule_pick(cands, eng.cfg.emergency_rtl_min_pct), "L")
        self.assertEqual(eng._rule_pick(cands, 11), "R")

    def test_link_previous_original_id_and_no_previous_case(self):
        eng = engine()
        eng.set_route([ROUTE[0], ROUTE[4]], indices=[0, 4])
        eng._link_hist.extend((d, 100 - 0.1 * d) for d in range(0, 600, 10))
        f = eng._link(telemetry(next_wp=1))
        prev = next(c for c in f.candidates if c["action"] == "A_RTL_AFTER_WP")
        self.assertEqual((prev["param"], prev["param_pos"]), (0, 0))
        eng.set_route([ROUTE[4]], indices=[4])
        f = eng._link(telemetry(next_wp=0))
        self.assertEqual({c["action"] for c in f.candidates}, {"A_CONTINUE_MONITOR", "A_RTL_NOW"})

    def test_sim_never_applies_hold_or_infeasible_choice(self):
        c = {"id": "C4", "action": "A_RTL_NOW", "label": "立即返航", "feasible": True}
        ev = {"rule_decision": "HOLD", "rule_choice": "C4", "key": "battery_route", "candidates": [c]}
        self.assertIsNone(sim._apply(ev, 0, ROUTE, ROUTE, 1))
        ev["rule_decision"] = "SELECT"
        c["feasible"] = False
        self.assertIsNone(sim._apply(ev, 0, ROUTE, ROUTE, 1))


EV = {"title": "電量告警", "value": "預估落地 15%", "rule_choice": "C1",
      "evidence": [{"id": "E1", "text": "落地", "value": "15.0%"}],
      "candidates": [{"id": "C1", "label": "飛完 WP13 後返航", "end_pct": 22.0, "feasible": True}]}


class ExplainExtra(unittest.TestCase):
    def answer(self, **kw):
        return {"decision": "SELECT", "choice_id": "C1", "summary_zh": "建議飛完 WP13 後返航。",
                "reason_zh": "保留進度。", "evidence_ids": ["E1"], **kw}

    def test_fraction_signed_and_reason_numbers_are_exact(self):
        self.assertIsNone(explain.validate(self.answer(), EV))
        for text in ("落地 5%", "落地 .5%", "落地 −5%", "落地 37%"):
            self.assertIsNotNone(explain.validate(self.answer(reason_zh=text), EV))

    def test_all_infeasible_rule_and_model_must_hold(self):
        ev = {**EV, "candidates": [{**EV["candidates"][0], "feasible": False}]}
        self.assertEqual(explain.rule_text(ev)["decision"], "HOLD")
        self.assertIn("請人工判斷", explain.rule_text(ev)["summary_zh"])
        self.assertIsNotNone(explain.validate(self.answer(), ev))
        self.assertIsNone(explain.validate(self.answer(decision="HOLD"), ev))

    def test_backend_construction_and_malformed_result_fall_back(self):
        with patch.object(explain, "get_backend", side_effect=RuntimeError("injected")):
            result = explain.explain(EV)
        self.assertEqual(result["source"], "rule")
        self.assertIn("RuntimeError", result["fallback_reason"])
        backend = type("BadBackend", (), {"complete_json": lambda *a, **k: {"ok": True}})()
        result = explain.explain(EV, backend)
        self.assertEqual(result["source"], "rule")
        self.assertIn("KeyError", result["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
