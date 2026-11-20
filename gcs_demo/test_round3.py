"""第三輪（演算法說明 v3.7）離線回歸：E05／E06／C11 區域、E07 不合格預覽、C12／C14 補前置規劃、B 的計畫輸出。"""
import json
import unittest

from .agent_m4b import M4bController
from .agent_planb import PlanBController
from .agent_tools import load_areas, match_areas
from .test_m4b import COUNTER, GRAPH, scripted, tools
from .test_planb import plan, st

AREAS = load_areas()


def tools3(targets):
    log, T = tools(targets)

    def qa(text):
        hits = match_areas(text, AREAS)
        if len(hits) == 1:
            return {"status": "ONE", "candidates": [hits[0]["id"]]}
        return {"status": "MANY" if hits else "NONE", "candidates": [h["id"] for h in hits]}
    T["query_area"] = qa
    return log, T


THREE = '{"action":"QUERY_AREA","ids":["A003","A002","A001"],"params":{}}'


class AreaTests(unittest.TestCase):
    def test_e05_three_ids_is_format_error_not_parked(self):
        m = scripted(['{"directions":["plan","ui"]}', THREE, THREE,
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"PROPOSE_HOME_ROUTE","ids":["U100"],"params":{}}'])
        log, T = tools3(["A003", "U100"])
        r = M4bController(T, m, GRAPH, COUNTER).request("南區巡檢航線放首頁")
        self.assertEqual(r["area_status"], "ONE")
        self.assertEqual(r["area_fixed"], "A003")
        self.assertEqual(r["steps"][0]["source"], "rule")            # 兩次都是 3 個 ID → 修正後走規則備援
        self.assertEqual(r["steps"][0]["ids"], ["A003"])
        self.assertEqual(r["status"], "DONE")
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])

    def test_c11_area_fixed_and_model_one_id(self):
        m = scripted(['{"directions":["plan","ui"]}', '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"PROPOSE_HOME_ROUTE","ids":["U100"],"params":{}}'])
        _, T = tools3(["A001", "U100"])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側巡檢，留 25%，放到首頁")
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["proposals"][0]["by"], "model")
        self.assertIn("schema", m.calls[1])

    def test_many_areas_asks_user_without_model(self):
        m = scripted(['{"directions":["plan"]}'])
        _, T = tools3([])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側和南側巡檢")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(len(m.calls), 1)                              # 只有第 1 段，沒有問模型選區域

    def test_e07_fail_preview_skips_home(self):
        _, T = tools3(["A001", "U100"])
        T["verify_preview"] = lambda ref: {"result": "fail", "preview_ref": "PV1", "est_end_pct": 3.0}
        r = M4bController(T, None, GRAPH, COUNTER).request("北側巡檢留 95% 放到首頁")
        self.assertEqual(r["proposals"], [])
        self.assertEqual(r["status"], "INCOMPLETE")


class DirectionTests(unittest.TestCase):
    def test_c12_ui_without_plan_is_augmented(self):
        m = scripted(['{"directions":["ui"]}'])
        _, T = tools3(["A003", "U100"])
        c = M4bController(T, m, GRAPH, COUNTER)
        task = {"text": "南側巡檢航線放到首頁", "artifacts": {}, "traces": [], "notes": [], "ledger": __import__(
            "gcs_demo.agent_m4b", fromlist=["Ledger"]).Ledger(), "rules": ""}
        ds = c._directions(task)
        self.assertEqual(ds, ["plan", "ui"])
        self.assertEqual(task["stage1_augmented"], ["plan"])

    def test_c14_end_to_end(self):
        m = scripted(['{"directions":["ui"]}', '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"PROPOSE_HOME_ROUTE","ids":["U100"],"params":{}}'])
        _, T = tools3(["A001", "U100"])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側巡檢放到首頁，保留 20%")
        self.assertEqual(r["directions"], ["plan", "ui"])
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])


class PlanBOutputTests(unittest.TestCase):
    def test_schema_is_per_action_and_example_is_full_chain(self):
        good = plan(st("s1", "plan", "QUERY_AREA", ["A003"]),
                    st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                    st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                    st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                       when="s3.route_preview.verdict==pass"))
        m = scripted(['{"directions":["plan","ui"]}', good])
        _, T = tools3(["A003", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("南區巡檢航線放首頁")
        call = m.calls[1]
        shapes = call["schema"]["properties"]["steps"]["items"]["anyOf"]
        qa = next(x for x in shapes if x["properties"]["action"]["enum"] == ["QUERY_AREA"])
        self.assertEqual(qa["properties"]["ids"]["items"]["enum"], ["A003"])
        self.assertEqual((qa["properties"]["ids"]["minItems"], qa["properties"]["ids"]["maxItems"]), (1, 1))
        prompt = call["messages"][1]["content"]
        for a in ("QUERY_AREA", "GEN_COVERAGE", "VERIFY_PREVIEW", "PROPOSE_HOME_ROUTE"):
            self.assertIn(f'"action": "{a}"', prompt)
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["proposals"][0]["by"], "model")

    def test_layout_missing_p_message_lists_options(self):
        bad = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C014"], {"value": "放大"}))
        good = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C014", "P002"], {"value": "放大"}))
        m = scripted(['{"directions":["layout"]}', bad, good])
        _, T = tools3(["C014", "P002"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("把風速計放大")
        self.assertIn("可用參數 P", m.calls[2]["messages"][1]["content"])
        self.assertEqual(r["proposals"][0]["ids"], ["C014", "P002"])

    def test_bind_error_lists_referable_steps(self):
        bad = plan(st("s1", "plan", "QUERY_AREA", ["A003"]),
                   st("s2", "plan", "GEN_COVERAGE", bind={"area": "s9.area_record"}))
        m = scripted(['{"directions":["plan"]}', bad])
        _, T = tools3(["A003"])
        PlanBController(T, m, GRAPH, COUNTER).request("南側巡檢")
        self.assertIn("可以引用：s1（QUERY_AREA，產生 area_record）", m.calls[2]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
