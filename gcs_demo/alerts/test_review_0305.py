"""Codex 審查 review_0305 的驗收測試（Claude 寫，修正版必須全部通過）。

python3 -m unittest gcs_demo.alerts.test_review_0305
"""
import math
import unittest

from . import explain
from .energy_api import Wind, default_vehicle
from .predict import Config, Finding, PredictiveAlertEngine, Telemetry


def tm(t=0.0, pos=(100.0, 0.0, 60.0), next_wp=1, wind=Wind(3, 90), cells=6, soc=80.0, used=90.0, link=90.0):
    return Telemetry(t=t, pos=pos, vel=(12.0, 0.0, 0.0), soc_pct=soc, voltage=23.0, current_a=40.0,
                     used_wh=used, cell_count=cells, next_wp=next_wp, link_pct=link, wind=wind)


ROUTE5 = [(0, 0, 60), (500, 0, 60), (1000, 0, 60), (1500, 0, 60), (2000, 0, 60)]


class FakeBackend:
    name = "fake"

    def __init__(self, data=None, exc=None):
        self.data, self.exc = data, exc

    def complete_json(self, system, user, schema, timeout_s=60):
        if self.exc:
            raise self.exc
        return {"ok": True, "data": self.data, "raw": str(self.data), "latency_s": 0.01, "error": None}


EV = {
    "title": "電量不足以飛完航線", "value": "預估落地 15%", "lead_s": None, "rule_choice": "C3",
    "rule_decision": "SELECT",
    "evidence": [{"id": "E1", "text": "預估落地", "value": "15.0%"}, {"id": "E2", "text": "保留", "value": "20%"}],
    "candidates": [
        {"id": "C1", "action": "A_CONTINUE", "label": "繼續", "end_pct": 15.0, "completion_pct": 100, "feasible": False},
        {"id": "C3", "action": "A_RTL_AFTER_WP", "label": "飛完 WP13 後返航", "end_pct": 22.0, "completion_pct": 76, "feasible": True},
    ],
}


def ok_answer(**kw):
    d = {"decision": "SELECT", "choice_id": "C3", "reason_zh": "可行且保留最多進度。", "evidence_ids": ["E1"],
         "summary_zh": "建議飛完 WP13 後返航。"}
    d.update(kw)
    return d


class InputRobustness(unittest.TestCase):          # 審查第 1 項
    def test_empty_route_does_not_crash(self):
        eng = PredictiveAlertEngine([], (0, 0, 0), default_vehicle())
        for i in range(5):
            self.assertIsInstance(eng.update(tm(t=i, next_wp=0)), list)

    def test_zero_cells_and_nan_do_not_crash(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        eng.update(tm(cells=0))
        eng.update(tm(t=1, soc=float("nan")))
        eng.update(tm(t=2, wind=Wind(float("nan"), 90)))

    def test_bad_next_wp_does_not_crash(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        eng.update(tm(next_wp=-3))
        eng.update(tm(t=1, next_wp=99))


class WindAlreadyOverLimit(unittest.TestCase):     # 審查第 2 項
    def test_over_limit_raises_without_warmup(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle(), Config(wind_limit_mps=12))
        evs = []
        for i in range(Config().raise_ticks):
            evs += eng.update(tm(t=i, wind=Wind(15, 90)))
        w = [e for e in evs if e["key"] == "wind_trend" and e["type"] == "raise"]
        self.assertTrue(w, "第一筆就超限應在 raise_ticks 內發告警")
        self.assertEqual(w[0]["severity"], 2)
        self.assertGreaterEqual(w[0]["lead_s"], 0)


class ReturnPoint(unittest.TestCase):              # 審查第 3 項
    def _engine_with_walk(self, margins):
        """margins：每個點 avail - cum - rtl - reserve（Wh），用假 walk 注入。"""
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        avail = 200.0
        reserve = eng.cfg.reserve_pct / 100 * eng.v.battery_wh
        walk = []
        for i, m in enumerate(margins):
            cum = 10.0 * i
            walk.append((i, cum, 60.0 * i, avail - cum - reserve - m))
        eng._walk = lambda path, veh, wind, speed=None: walk[:len(path)]
        eng._available_wh = lambda t: (avail, "soc", None)
        return eng

    def test_stops_at_first_unsafe_point(self):
        # 目前位置、WP2 安全，WP3 不安全，WP4 又安全，終點不可行 → 最晚返航點必須是 WP2（原索引 1）
        eng = self._engine_with_walk([5, 5, -5, 5, -50])
        eng.update(tm(next_wp=1))
        self.assertEqual(eng.last_state.get("pnr_wp"), 1)

    def test_no_margin_now_differs_from_at_pnr(self):
        eng = self._engine_with_walk([-5, -5, -5, -5, -50])
        evs = []
        for i in range(3):
            evs += eng.update(tm(t=i, next_wp=1))
        titles = {e["title"] for e in evs if e["key"] == "rtl_point"}
        self.assertTrue(titles)
        self.assertNotIn("已到最晚返航點", titles, "現在就已沒有返航餘裕，要用不同說法")


class FeasibilityContract(unittest.TestCase):      # 審查第 4、6 項
    def test_all_infeasible_gives_hold_and_land_marked_unknown(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        evs = []
        for i in range(3):
            evs += eng.update(tm(t=i, soc=12.0, used=430.0))
        b = [e for e in evs if e["key"] == "battery_route" and e["type"] == "raise"]
        self.assertTrue(b)
        ev = b[0]
        self.assertIn(ev.get("rule_decision"), ("SELECT", "HOLD"))
        if not any(c["feasible"] for c in ev["candidates"]):
            self.assertEqual(ev["rule_decision"], "HOLD")
        land = [c for c in ev["candidates"] if c["action"] == "A_LAND_NOW"]
        self.assertTrue(land and land[0].get("operational_status") == "unknown")
        self.assertFalse(land[0]["feasible"], "地面狀況未知的就地降落不能標成可行")

    def test_feasibility_uses_unrounded_value(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        self.assertFalse(eng._is_feasible(19.96))
        self.assertTrue(eng._is_feasible(20.0))


class CompletionAfterReroute(unittest.TestCase):   # 審查第 5 項
    def test_completion_counts_reached_points(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        eng.update(tm(next_wp=1))                      # 已到原第 0 點
        eng.set_route([ROUTE5[0], ROUTE5[4]], indices=[0, 4])
        eng.update(tm(t=1, next_wp=1))
        path = eng._remaining(tm(t=1, next_wp=1))
        walk = eng._walk(path, eng._vehicle(), Wind(3, 90))
        cands = eng._candidates(tm(t=1, next_wp=1), path, walk, 200.0, 97.6, None, Wind(3, 90))
        rtl = next(c for c in cands if c["action"] == "A_RTL_NOW")
        self.assertEqual(rtl["completion_pct"], 20.0)   # 只到過 1/5 個點
        cont = next(c for c in cands if c["action"] == "A_CONTINUE")
        self.assertEqual(cont["completion_pct"], 40.0)  # 繼續也只會再到原第 4 點


class Hysteresis(unittest.TestCase):               # 審查第 7 項（pending）
    def test_interrupted_choice_change_is_not_accumulated(self):
        eng = PredictiveAlertEngine(ROUTE5, (0, 0, 0), default_vehicle())
        F = lambda c, a=True: Finding("x", active=a, severity=4, title="t", rule_choice=c)
        seq = [F("C1")] * 3 + [F("C2"), F("C2"), F("C2", a=False), F("C2")]
        evs = []
        for i, f in enumerate(seq):
            evs += eng._debounce(float(i), f)
        self.assertEqual([e["type"] for e in evs], ["raise"])


class ExplainContract(unittest.TestCase):          # 審查第 8、9 項
    def fb(self, **kw):
        return explain.explain(EV, FakeBackend(ok_answer(**kw)))

    def test_valid_answer_passes(self):
        self.assertEqual(self.fb()["source"], "llm")

    def test_evidence_must_be_nonempty_and_all_real(self):
        self.assertEqual(self.fb(evidence_ids=[])["source"], "rule")
        self.assertEqual(self.fb(evidence_ids=["E1", "E9"])["source"], "rule")
        self.assertEqual(self.fb(evidence_ids=[["E1"]])["source"], "rule")

    def test_decision_must_be_valid(self):
        self.assertEqual(self.fb(decision="MAYBE")["source"], "rule")
        self.assertEqual(self.fb(decision="HOLD")["source"], "rule")   # 有可行選項時不能 HOLD

    def test_numbers_must_match_exactly(self):
        self.assertEqual(self.fb(summary_zh="預估落地 5%，建議返航。")["source"], "rule")   # 只有 15%
        self.assertEqual(self.fb(reason_zh="可多保 37% 電量。")["source"], "rule")

    def test_backend_exception_falls_back(self):
        r = explain.explain(EV, FakeBackend(exc=TimeoutError("slow")))
        self.assertEqual(r["source"], "rule")
        self.assertIn("TimeoutError", r["fallback_reason"])


class LinkCandidate(unittest.TestCase):            # 審查「另」
    def test_no_negative_waypoint_param(self):
        from . import sim
        r = sim.run(policy="ignore")
        for e in r["events"]:
            for c in e.get("candidates", []):
                p = c.get("param")
                if isinstance(p, int):
                    self.assertGreaterEqual(p, 0)


if __name__ == "__main__":
    unittest.main()
