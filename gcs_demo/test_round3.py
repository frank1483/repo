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
        # 只有第 1 段，沒有問模型選區域（v3.12：追問句的潤飾呼叫另計）
        self.assertEqual([c["purpose"] for c in m.calls if c["purpose"] != "polish"], ["stage1"])

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


class RoundThreeV2(unittest.TestCase):
    def test_query_area_zero_one_many_ids(self):
        c = M4bController({}, None, GRAPH, COUNTER)
        task = {"cands": {"plan": ["A003"]}, "artifacts": {}, "proposals": []}
        for ids, ok in (([], False), (["A003"], True), (["A003", "A001"], False)):
            r = c._parse_step(task, "plan", json.dumps({"action": "QUERY_AREA", "ids": ids, "params": {}}), ["QUERY_AREA"])
            self.assertEqual(r[0], ok, ids)
        shape = c.action_shape(task, "plan", "QUERY_AREA")[0]
        self.assertEqual((shape["minItems"], shape["maxItems"], shape["items"]["enum"]), (1, 1, ["A003"]))
        self.assertEqual(c.action_shape(task, "plan", "GEN_COVERAGE")[0]["maxItems"], 0)

    def test_a_step_schema_is_anyof_per_action(self):
        m = scripted(['{"directions":["plan"]}', '{"action":"QUERY_AREA","ids":["A003"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}'])
        _, T = tools3(["A003"])
        M4bController(T, m, GRAPH, COUNTER).request("南側巡檢")
        shapes = m.calls[1]["schema"]["anyOf"]
        qa = next(x for x in shapes if x["properties"]["action"]["enum"] == ["QUERY_AREA"])
        self.assertEqual(qa["properties"]["ids"]["minItems"], 1)

    def test_b_home_requires_exactly_u100(self):
        base = [st("s1", "plan", "QUERY_AREA", ["A003"]), st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"})]
        empty = plan(*(base + [st("s4", "ui", "PROPOSE_HOME_ROUTE", [], bind={"preview": "s3.route_preview"},
                                  when="s3.route_preview.verdict==pass")]))
        m = scripted(['{"directions":["plan","ui"]}', empty, empty, empty])
        _, T = tools3(["A003", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("南區巡檢航線放首頁")
        self.assertTrue(any("U100" in e.get("reason", "") for e in r["plan_log"]))
        self.assertIn("計畫無效或未呼叫模型，改用規則計畫", r["notes"])

    def test_augmented_directions_before_after_and_to_b(self):
        from .m4b_runner import score
        m = scripted(['{"directions":["ui"]}', '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"PROPOSE_HOME_ROUTE","ids":["U100"],"params":{}}'])
        _, T = tools3(["A001", "U100"])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側巡檢放到首頁，保留 20%")
        self.assertEqual((r["stage1_raw"], r["directions"], r["stage1_augmented"]), (["ui"], ["plan", "ui"], ["plan"]))
        case = {"expect_proposals": [{"action": "PROPOSE_HOME_ROUTE", "ids": ["U100"], "values": []}],
                "expect_artifacts": {}, "expect_status": "DONE", "gold_dirs": ["plan", "ui"]}
        sc = score(case, r)
        self.assertEqual((sc["dirs_raw_match"], sc["dirs_set_match"]), (False, True))
        pre = {"directions": r["directions"], "stage1_calls": 1, "stage1_source": "model", "stage1_raw": ["ui"],
               "stage1_augmented": ["plan"]}
        good = plan(st("s1", "plan", "QUERY_AREA", ["A001"]), st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                    st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                    st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                       when="s3.route_preview.verdict==pass"))
        mb = scripted([good])
        _, TB = tools3(["A001", "U100"])
        rb = PlanBController(TB, mb, GRAPH, COUNTER, preset=pre).request("北側巡檢放到首頁，保留 20%")
        self.assertEqual((rb["stage1_raw"], rb["stage1_augmented"]), (["ui"], ["plan"]))


class RoundThreeV3(unittest.TestCase):
    def test_over_cap_keeps_directions_and_b_terminal_carries_them(self):
        from .m4b_runner import score
        m = scripted(['{"directions":["layout","color","model","ui"]}'])
        _, T = tools3(["A001"])
        r = M4bController(T, m, GRAPH, COUNTER).request("北側巡檢放首頁，文字放大，改深色，改規則模式")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(r["stage1_raw"], ["layout", "color", "model", "ui"])
        self.assertEqual(r["stage1_augmented"], ["plan"])
        self.assertEqual(r["directions"], ["layout", "color", "model", "plan", "ui"])
        self.assertIsNone(r["packing"])
        case = {"expect_proposals": [], "expect_artifacts": {}, "expect_status": "PARKED",
                "gold_dirs": ["plan", "ui", "layout", "color", "model"]}
        sc = score(case, r)
        self.assertEqual((sc["dirs_raw_match"], sc["dirs_set_match"]), (False, True))
        pre = {"directions": r["directions"], "stage1_calls": 1, "stage1_source": "model", "stage1_raw": r["stage1_raw"],
               "stage1_augmented": r["stage1_augmented"],
               "terminal": {"status": "PARKED", "reply_zh": r["reply_zh"], "reason": "方向超過上限"}}
        rb = PlanBController({}, scripted([]), GRAPH, COUNTER, preset=pre).request("x")
        for k in ("directions", "stage1_raw", "stage1_augmented"):
            self.assertEqual(rb[k], r[k], k)

    def test_runner_terminal_detection_and_match(self):
        from . import planb_runner as PR
        a_rep = {"status": "PARKED", "directions": ["layout", "color", "model", "plan", "ui"], "packing": None,
                 "stage1_raw": ["layout", "color", "model", "ui"], "stage1_augmented": ["plan"], "traces": [
                     {"purpose": "stage1", "replies": [{"raw": "x"}]}], "notes": ["超限"], "reply_zh": "請分批"}
        import os
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "cases", "A-s6-b30", "C99"))
        with open(os.path.join(d, "results.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"cond": "A-s6-b30", "case": "C99", "error": None}) + "\n")
        with open(os.path.join(d, "cases", "A-s6-b30", "C99", "full.json"), "w", encoding="utf-8") as f:
            json.dump({"reply": a_rep}, f, ensure_ascii=False)
        old = PR._SHARED["dir"]
        try:
            PR._SHARED["dir"] = d
            _, preset, _ = PR.a_record("A-s6-b30", "C99")
        finally:
            PR._SHARED["dir"] = old
        self.assertIn("terminal", preset)
        self.assertEqual(preset["stage1_raw"], a_rep["stage1_raw"])


class RoundThreeV371(unittest.TestCase):
    def test_f20_requires_qgc_compass_section(self):
        from .m4b_runner import score
        cases = {c["id"]: c for c in json.load(open(__import__("os").path.join(__import__("os").path.dirname(__file__),
                                                                            "m4b_cases_eval_v2.json"), encoding="utf-8"))["cases"]}
        case = dict(cases["F20"], expect_status="DONE")

        def run(ref):
            return score(case, {"status": "DONE", "artifacts": {"manual_claims": {"verdict": "ok", "refs": [ref]}}})["correct"]
        px4 = "docs/en/qgc-user-guide/setup_view/sensors_px4.md"
        ardu = "docs/en/qgc-user-guide/setup_view/sensors_ardupilot.md"
        self.assertTrue(run({"manual": "qgc", "path": px4, "heading_path": "Sensor setup (PX4) > Compass {#compass}"}))
        self.assertTrue(run({"manual": "qgc", "path": ardu, "heading_path": "Sensor Setup (ArduPilot) > Compass {#compass} > Sub"}))
        self.assertFalse(run({"manual": "qgc", "path": px4, "heading_path": "Sensor setup (PX4) > Compasses"}))          # 0424 負例
        self.assertFalse(run({"manual": "qgc", "path": ardu, "heading_path": "Sensor Setup (ArduPilot) > CompassMot (Optional)"}))
        self.assertFalse(run({"manual": "px4", "path": "docs/en/config/compass.md", "heading_path": "Compass {#compass}"}))

    def test_scope_common_rate(self):
        from .m4b_runner import summarize
        recs = [{"cond": "A", "case": "F23", "prop_case": True, "correct": False, "scope": "both_not_supported", "shared_input_match": True},
                {"cond": "A", "case": "F09", "prop_case": True, "correct": True, "shared_input_match": True}]
        out = summarize(recs)["A"]
        self.assertEqual(out["correct_prop_rate"], 0.5)
        self.assertEqual(out["correct_prop_rate_common_scope"], "1/1")

    def test_shared_field_difference_marks_mismatch(self):
        from . import planb_runner as PR
        a_rep = {"directions": ["plan", "ui"], "stage1_raw": ["ui"], "stage1_augmented": ["plan"], "packing": {"batches": []}}
        b_rep = dict(a_rep, stage1_raw=["plan", "ui"], stage1_augmented=None)
        orig_run, orig_rec = PR._run_case, PR.a_record
        try:
            PR._run_case = lambda *a: ({"correct": True}, {"reply": b_rep})
            PR.a_record = lambda c, k: (a_rep, {"directions": a_rep["directions"], "stage1_calls": 1}, [])
            rec, _ = PR.run_case({"id": "X", "expect_proposals": [], "expect_artifacts": {}, "expect_status": "DONE",
                                  "gold_dirs": []}, {"id": "A-s6-b30"}, None, None, None, None)
        finally:
            PR._run_case, PR.a_record = orig_run, orig_rec
        self.assertFalse(rec["shared_input_match"])


if __name__ == "__main__":
    unittest.main()
