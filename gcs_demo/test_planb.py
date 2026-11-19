"""方案 B 單元測試（假模型、one-hot 假向量；不呼叫 Ollama）。"""
import json
import unittest

from .agent_planb import PlanBController
from .test_m4b import COUNTER, GRAPH, scripted, tools


def plan(*steps):
    return json.dumps({"steps": list(steps)}, ensure_ascii=False)


def st(i, d, a, ids=(), params=None, after=(), bind=None, when=None, require=None):
    return {"id": i, "direction": d, "action": a, "ids": list(ids), "params": params or {}, "after": list(after),
            "bind": bind or {}, "when": when, "require": require or {}}


PLAN_UI = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
               st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
               st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
               st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                  when="s3.route_preview.verdict==pass"))


class PlanBTests(unittest.TestCase):
    def test_one_plan_call_then_execute(self):
        m = scripted(['{"directions":["plan","ui"]}', PLAN_UI, '{"reply":"已開確認視窗"}'])
        log, T = tools(["A001", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢放到首頁")
        self.assertEqual([t["purpose"] for t in r["traces"]], ["stage1", "plan", "summary"])
        self.assertEqual([s["state"] for s in r["plan"]], ["OK", "OK", "OK", "PROPOSED"])
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["calls_used"], 3)

    def test_when_false_skipped_not_failure(self):
        m = scripted(['{"directions":["plan","ui"]}', PLAN_UI])
        log, T = tools(["A001", "U100"])
        T["verify_preview"] = lambda ref: {"result": "fail", "preview_ref": "PV", "est_end_pct": 10.0}
        r = PlanBController(T, m, GRAPH, COUNTER, summary_llm=False).request("規劃北側巡檢放到首頁")
        self.assertEqual(r["plan"][3]["state"], "SKIPPED")
        self.assertEqual(r["proposals"], [])
        self.assertEqual(r["replans"], 0)

    def test_invalid_plan_correction_uses_quota(self):
        bad = plan(st("s1", "plan", "TAKEOFF"))
        m = scripted(['{"directions":["color"]}', bad, plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]))])
        _, T = tools(["T001"])
        r = PlanBController(T, m, GRAPH, COUNTER, summary_llm=False).request("改成深色主題")
        self.assertEqual(r["replans"], 1)
        self.assertEqual(r["proposals"][0]["ids"], ["T001"])

    def test_quota_exhausted_falls_back_to_rule_plan(self):
        bad = plan(st("s1", "color", "UI_THEME_PROPOSE", ["T999"]))
        m = scripted(['{"directions":["color"]}', bad, bad, bad, bad])
        _, T = tools(["T001"])
        r = PlanBController(T, m, GRAPH, COUNTER, summary_llm=False).request("改成深色主題")
        self.assertEqual(r["replans"], 2)
        self.assertEqual(r["calls_used"], 4)                     # 第 1 段＋初始規劃＋2 次修正
        self.assertTrue(any(e["event"] == "replan_quota_exhausted" for e in r["plan_log"]))
        self.assertEqual(r["proposals"][0]["ids"], ["T001"])      # 規則計畫

    def test_bind_type_mismatch_rejected(self):
        wrong = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                     st("s2", "plan", "VERIFY_PREVIEW", bind={"route": "s1.area_record"}))
        m = scripted(['{"directions":["plan"]}', wrong, PLAN_UI.replace(',{"id": "s4"', ']}') if False else
                      plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                           st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                           st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}))])
        _, T = tools(["A001"])
        r = PlanBController(T, m, GRAPH, COUNTER, summary_llm=False).request("規劃北側巡檢")
        self.assertEqual(r["replans"], 1)
        self.assertEqual(r["status"], "DONE")

    def test_failure_replans_only_affected(self):
        # s2 缺 bind → GEN_COVERAGE 仍可執行；改成讓 GEN 失敗：區域不存在時 BLOCKED
        p1 = plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]),
                  st("s2", "plan", "GEN_COVERAGE"),
                  st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}))
        p2 = plan(st("s4", "plan", "QUERY_AREA", ["A001"]),
                  st("s5", "plan", "GEN_COVERAGE", bind={"area": "s4.area_record"}),
                  st("s6", "plan", "VERIFY_PREVIEW", bind={"route": "s5.coverage_route"}))
        m = scripted(['{"directions":["plan","color"]}', p1, p2])
        _, T = tools(["A001", "T001"])
        r = PlanBController(T, m, GRAPH, COUNTER, summary_llm=False).request("規劃北側巡檢，改成深色主題")
        states = {s["id"]: s["state"] for s in r["plan"]}
        self.assertEqual(states["s1"], "PROPOSED")               # 獨立步驟不受影響
        self.assertEqual((states["s2"], states["s3"]), ("REPLACED", "REPLACED"))
        self.assertEqual((states["s4"], states["s5"], states["s6"]), ("OK", "OK", "OK"))
        self.assertEqual(r["replans"], 1)
        self.assertEqual(r["status"], "DONE")

    def test_require_waits_for_applied(self):
        p = plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]),
                 st("s2", "model", "MODEL_SWITCH_PROPOSE", ["M003"], require={"s1": "APPLIED"}))
        m = scripted(['{"directions":["color","model"]}', p])
        _, T = tools(["T001", "M003"])
        r = PlanBController(T, m, GRAPH, COUNTER, summary_llm=False).request("改成深色主題後改用規則模式")
        self.assertEqual(r["plan"][1]["state"], "WAITING")
        self.assertEqual(len(r["proposals"]), 1)

    def test_cross_batch_reference(self):
        big = lambda text: 1100 if "｜" in text and "說明" not in text else 1
        p1 = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C014", "P002"], {"value": "放大"}),
                  st("s2", "color", "UI_THEME_PROPOSE", ["T001"]))
        p2 = plan(st("s3", "model", "MODEL_SWITCH_PROPOSE", ["M003"], after=["s1"]))
        m = scripted(['{"directions":["layout","color","model"]}', p1, p2])
        _, T = tools(["C014", "P002", "T001", "M003"])
        r = PlanBController(T, m, GRAPH, big, summary_llm=False).request("風速計放大，改成深色主題，改用規則模式")
        self.assertEqual([t["purpose"] for t in r["traces"]], ["stage1", "plan", "plan"])
        self.assertEqual(len(r["proposals"]), 3)
        self.assertEqual(r["replans"], 0)

    def test_rule_plan_without_model(self):
        log, T = tools(["A001", "U100"])
        r = PlanBController(T, None, GRAPH, COUNTER).request("規劃北側巡檢放到首頁")
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])
        self.assertEqual(r["status"], "DONE")


if __name__ == "__main__":
    unittest.main()
