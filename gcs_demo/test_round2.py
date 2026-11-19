"""第二輪（演算法說明 v3.6）回歸：C11 型（每步合法但任務未完成）與 C31 型（照抄範例）。假模型，不呼叫 Ollama。"""
import json
import unittest

from . import outcomes as OC
from .agent_m4b import M4bController
from .agent_planb import PlanBController
from .test_m4b import COUNTER, GRAPH, scripted, tools
from .test_planb import plan, st


class OutcomeTests(unittest.TestCase):
    def test_executable_excludes_done(self):
        have = {"area_record": "A001"}
        self.assertEqual(OC.executable("plan", ["QUERY_AREA", "GEN_COVERAGE", "VERIFY_PREVIEW"], have), ["GEN_COVERAGE"])
        self.assertEqual(OC.missing("plan", have), ["coverage_route", "route_preview"])

    def test_fail_preview_is_legit_skip_for_ui(self):
        have = {"area_record": "x", "coverage_route": "R", "route_preview": "不合格"}
        self.assertEqual(OC.missing("ui", have), [])
        self.assertIn("合法略過", OC.summary(["ui"], have))


class RoundTwoA(unittest.TestCase):
    def test_c11_model_cannot_repeat_query(self):
        # 模型每步都想再查區域：查完之後 QUERY_AREA 不在可選清單 → 退回 → 規則補上下一步
        rep = '{"action":"QUERY_AREA","ids":["A001"],"params":{}}'
        m = scripted(['{"directions":["plan","ui"]}'] + [rep] * 12)
        _, T = tools(["A001", "U100"])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側巡檢，留 25%，放到首頁")
        acts = [s["action"] for s in r["steps"]]
        self.assertEqual(acts.count("QUERY_AREA"), 1)
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["stage1_source"], "model")
        self.assertIn("現在能做的動作", m.calls[2]["messages"][1]["content"])
        self.assertIn("已有：區域紀錄", m.calls[2]["messages"][1]["content"])

    def test_c11_model_follows_progress(self):
        m = scripted(['{"directions":["plan","ui"]}', '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"PROPOSE_HOME_ROUTE","ids":["U100"],"params":{}}'])
        _, T = tools(["A001", "U100"])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側巡檢，留 25%，放到首頁")
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["proposals"][0]["by"], "model")
        self.assertEqual(r["calls_used"], 5)                 # 第 1 段＋4 步；成果齊了不再問 FINISH

    def test_stage1_rejects_labels(self):
        m = scripted(['{"directions":["plan 任務規劃"]}', '{"directions":["color"]}'])
        _, T = tools(["T001"])
        r = M4bController(T, m, GRAPH, COUNTER).request("換成深色主題")
        self.assertEqual(r["directions"], ["color"])
        self.assertIn("只能填這些代碼", m.calls[1]["messages"][1]["content"])
        self.assertIn("schema", m.calls[0])


class RoundTwoB(unittest.TestCase):
    def test_c11_incomplete_plan_rejected(self):
        one = plan(st("s1", "plan", "QUERY_AREA", ["A001"]))
        full = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                    st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                    st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                    st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                       when="s3.route_preview.verdict==pass"))
        m = scripted(['{"directions":["plan","ui"]}', one, full])
        _, T = tools(["A001", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("北側巡檢，留 25%，放到首頁")
        self.assertEqual(r["replans"], 1)
        self.assertTrue(any("計畫不完整" in e.get("reason", "") for e in r["plan_log"]))
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["proposals"][0]["by"], "model")

    def test_c31_dynamic_example_and_specific_error(self):
        wrong = plan(st("s1", "plan", "QUERY_AREA", ["T001"]))
        right = plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]))
        m = scripted(['{"directions":["color"]}', wrong, right])
        _, T = tools(["T001"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("換成深色主題")
        p1 = m.calls[1]["messages"][1]["content"]
        self.assertNotIn('"direction": "plan"', p1)
        self.assertIn('"direction": "color"', p1)
        self.assertIn("color 的 action 只能是 UI_THEME_PROPOSE", m.calls[2]["messages"][1]["content"])
        self.assertEqual(r["proposals"][0]["by"], "model")
        self.assertIn("schema", m.calls[1])

    def test_continue_after_execution(self):
        # 計畫通過驗證（模擬可達），但執行時生成航點失敗 → 由重規劃處理；另一情境：執行後仍缺 → 補計畫
        p1 = plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]))
        m = scripted(['{"directions":["color","model"]}', p1, plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]),
                                                                    st("s2", "model", "MODEL_SWITCH_PROPOSE", ["M003"]))])
        _, T = tools(["T001", "M003"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("改成深色主題，改用規則模式")
        self.assertEqual(r["replans"], 1)                      # 第一份缺 model → 執行前就退回
        self.assertEqual(sorted(p["action"] for p in r["proposals"]), ["MODEL_SWITCH_PROPOSE", "UI_THEME_PROPOSE"])

    def test_accept_fills_gap_after_execution(self):
        # 預覽合格才放首頁；模擬時假設合格分支可達 → 計畫通過；實際執行後首頁已開 → 不需補
        # 這裡造一個「計畫內步驟被 NEEDS_USER 以外原因略過」的缺口：when 指向 fail 分支
        p1 = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                  st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                  st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                  st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                     when="s3.route_preview.verdict==fail"))
        p2 = plan(st("s5", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"}))
        m = scripted(['{"directions":["plan","ui"]}', p1, p2])
        _, T = tools(["A001", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("北側巡檢放到首頁")
        self.assertTrue(any(e["event"] == "continue" for e in r["plan_log"]))
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])
        self.assertEqual(r["status"], "DONE")


if __name__ == "__main__":
    unittest.main()
