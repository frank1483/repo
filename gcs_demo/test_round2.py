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

    def test_contradictory_when_rejected_before_execution(self):
        # v2（CODEX-APP-0413 第 1 點）：首頁要 s3 合格，卻限定 s3 不合格才做 → 永遠不成立 → 執行前退回
        bad = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                   st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                   st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                   st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                      when="s3.route_preview.verdict==fail"))
        good = bad.replace("verdict==fail", "verdict==pass")
        m = scripted(['{"directions":["plan","ui"]}', bad, good])
        _, T = tools(["A001", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("北側巡檢放到首頁")
        self.assertTrue(any("永遠不會成立" in e.get("reason", "") for e in r["plan_log"]))
        self.assertFalse(any(e["event"] == "continue" for e in r["plan_log"]))
        self.assertEqual(r["replans"], 1)
        self.assertEqual(r["status"], "DONE")

    def test_accept_fills_gap_only_known_at_runtime(self):
        # 模擬時兩份預覽都可能合格 → 計畫通過；實際 s6 不合格 → s7 依條件略過 → 首頁仍缺（s3 合格，不是合法略過）→ 補計畫
        p1 = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                  st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                  st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                  st("s6", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}, after=["s3"]),
                  st("s7", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                     when="s6.route_preview.verdict==pass"))
        p2 = plan(st("s8", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"}))
        m = scripted(['{"directions":["plan","ui"]}', p1, p2])
        _, T = tools(["A001", "U100"])
        n = {"v": 0}

        def verify(ref):
            n["v"] += 1
            return {"result": "pass" if n["v"] == 1 else "fail", "preview_ref": f"PV{n['v']}", "est_end_pct": 50.0}
        T["verify_preview"] = verify
        r = PlanBController(T, m, GRAPH, COUNTER).request("北側巡檢放到首頁")
        self.assertTrue(any(e["event"] == "continue" for e in r["plan_log"]))
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])
        self.assertEqual(r["proposals"][0]["source"]["preview_ref"], "PV1")
        self.assertEqual(r["status"], "DONE")


class RoundTwoDedupe(unittest.TestCase):
    def test_same_signature_rejected_new_target_allowed(self):
        a = M4bController({}, None, GRAPH, COUNTER)
        task = {"artifacts": {"area_record": {"id": "A001", "ref": "AREA-N1"}}, "proposals": [], "cands": {"plan": ["A001", "A003"]},
                "sigs": set()}
        have = a.have(task)
        task["sigs"].add(a._sig({"action": "QUERY_AREA", "ids": ["A001"], "params": {}}, have))
        ok, _, err = a._parse_step(task, "plan", '{"action":"QUERY_AREA","ids":["A001"],"params":{}}', ["QUERY_AREA", "FINISH"])
        self.assertFalse(ok)
        self.assertIn("已經做過", err)
        ok, _, _ = a._parse_step(task, "plan", '{"action":"QUERY_AREA","ids":["A003"],"params":{}}', ["QUERY_AREA", "FINISH"])
        self.assertTrue(ok)                                   # 換目標可以重做

    def test_input_change_allows_redo(self):
        a = M4bController({}, None, GRAPH, COUNTER)
        t1 = {"artifacts": {"area_record": {"id": "A001", "ref": "AREA-N1"}}, "proposals": []}
        t2 = {"artifacts": {"area_record": {"id": "A003", "ref": "AREA-S1"}}, "proposals": []}
        st_ = {"action": "GEN_COVERAGE", "ids": [], "params": {}}
        self.assertNotEqual(a._sig(st_, a.have(t1)), a._sig(st_, a.have(t2)))


class RetryCount(unittest.TestCase):
    def test_new_actions_are_not_retries(self):
        from .m4b_runner import _sum_timing
        calls = [{"purpose": "step:plan", "attempt": 0, "decision": 1, "status": 200, "latency_s": 1},
                 {"purpose": "step:plan", "attempt": 0, "decision": 2, "status": 200, "latency_s": 1},
                 {"purpose": "step:plan", "attempt": 1, "decision": 2, "status": 200, "latency_s": 2}]
        t = _sum_timing(calls)
        self.assertEqual((t["retries"], t["retry_wall_s"], t["decisions"]), (1, 2.0, 2))


class RoundTwoV3(unittest.TestCase):
    def test_branch_conditions_propagate(self):
        # CODEX-APP-0414 第 1 點的反例：s4 只在 s3 不合格時查區，s5 只在 s3 合格時用 s4 → 沒有共同分支
        steps = [st("s1", "plan", "QUERY_AREA", ["A001"]), st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                 st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                 st("s4", "plan", "QUERY_AREA", ["A003"], after=["s3"], when="s3.route_preview.verdict==fail"),
                 st("s5", "plan", "GEN_COVERAGE", bind={"area": "s4.area_record"}, when="s3.route_preview.verdict==pass"),
                 st("s6", "plan", "VERIFY_PREVIEW", bind={"route": "s5.coverage_route"}),
                 st("s7", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s6.route_preview"})]
        prod, bad = OC.simulate_steps(steps, {}, {})
        self.assertEqual([b[0] for b in bad], ["s5", "s6", "s7"])

    def test_known_verdict_used(self):
        steps = [st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"})]
        outs = {"s3": {"route_preview": {"ref": "PV1", "verdict": "fail"}}}
        _, bad = OC.simulate_steps(steps, outs, {})
        self.assertEqual(len(bad), 1)
        steps = [st("s4", "plan", "QUERY_AREA", ["A003"], when="s3.route_preview.verdict==pass")]
        _, bad = OC.simulate_steps(steps, outs, {})
        self.assertIn("不會成立", bad[0][1])

    def test_area_change_invalidates_downstream(self):
        # A 正常入口：查 A001 → 生成 → 換查 A003 → 預覽：不可驗到 A001 的舊航線
        m = scripted(['{"directions":["plan"]}', '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"QUERY_AREA","ids":["A003"],"params":{}}',
                      '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}', '{"action":"GEN_COVERAGE","ids":[],"params":{}}',
                      '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}'])
        log, T = tools(["A001", "A003"])
        r = M4bController(T, m, GRAPH, COUNTER).request("規劃北側巡檢")
        gens = [x for x in log if x[0] == "gen"]
        self.assertEqual([g[1] for g in gens], ["AREA-N1", "AREA-S1"])
        self.assertEqual(r["artifacts"]["coverage_route"]["area_id"], "A003")
        self.assertTrue(any("coverage_route" in x for x in r.get("artifacts", {}) and [r["artifacts"]]))
        acts = [s["action"] for s in r["steps"]]
        self.assertEqual(acts, ["QUERY_AREA", "GEN_COVERAGE", "QUERY_AREA", "GEN_COVERAGE", "VERIFY_PREVIEW"])


class RoundTwoV4(unittest.TestCase):
    BASE = [st("s1", "plan", "QUERY_AREA", ["A001"]), st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
            st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
            st("s4", "plan", "QUERY_AREA", ["A003"], after=["s3"], when="s3.route_preview.verdict==fail")]

    def test_pure_after_does_not_propagate(self):
        # 0415 反例 1：s5 只 after s4（s4 只在 s3 不合格才做），s5 自己在 s3 合格時做首頁 → 合法
        s5 = st("s5", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"}, after=["s4"],
                when="s3.route_preview.verdict==pass")
        _, bad = OC.simulate_steps(self.BASE + [s5], {}, {})
        self.assertEqual(bad, [])

    def test_pure_after_end_to_end(self):
        s5 = st("s5", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"}, after=["s4"],
                when="s3.route_preview.verdict==pass")
        m = scripted(['{"directions":["plan","ui"]}', plan(*(self.BASE + [s5]))])
        _, T = tools(["A001", "A003", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("北側巡檢放到首頁")
        states = {x["id"]: x["state"] for x in r["plan"]}
        self.assertEqual((states["s4"], states["s5"]), ("SKIPPED", "PROPOSED"))
        self.assertEqual(r["replans"], 0)

    def test_require_propagates(self):
        # 0415 反例 2：s4 只在 s3 不合格才開主題提案；s5 在 s3 合格時做、且 require s4 APPLIED → 沒有共同分支
        s4 = st("s4", "color", "UI_THEME_PROPOSE", ["T001"], after=["s3"], when="s3.route_preview.verdict==fail")
        s5 = st("s5", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                when="s3.route_preview.verdict==pass", require={"s4": "APPLIED"})
        _, bad = OC.simulate_steps(self.BASE[:3] + [s4, s5], {}, {})
        self.assertEqual([b[0] for b in bad], ["s5"])


if __name__ == "__main__":
    unittest.main()
