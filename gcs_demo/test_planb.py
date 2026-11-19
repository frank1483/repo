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
        self.assertEqual([t["purpose"] for t in r["traces"]], ["stage1", "plan"])     # v3：回覆固定模板
        self.assertEqual([s["state"] for s in r["plan"]], ["OK", "OK", "OK", "PROPOSED"])
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(r["calls_used"], 2)

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
        # 第一次生成覆蓋航點失敗（工具回非 OK）→ 只重規劃 s3、s4；獨立的 s1（主題）與已完成的 s2 不動
        p1 = plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]),
                  st("s2", "plan", "QUERY_AREA", ["A001"]),
                  st("s3", "plan", "GEN_COVERAGE", bind={"area": "s2.area_record"}),
                  st("s4", "plan", "VERIFY_PREVIEW", bind={"route": "s3.coverage_route"}))
        p2 = plan(st("s5", "plan", "GEN_COVERAGE", bind={"area": "s2.area_record"}),
                  st("s6", "plan", "VERIFY_PREVIEW", bind={"route": "s5.coverage_route"}))
        m = scripted(['{"directions":["plan","color"]}', p1, p2])
        _, T = tools(["A001", "T001"])
        n = {"gen": 0}

        def gen(ref):
            n["gen"] += 1
            return {"status": "OK", "route_ref": "R2"} if n["gen"] > 1 else {"status": "NO_ROUTE"}
        T["gen_coverage"] = gen
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢，改成深色主題")
        states = {s["id"]: s["state"] for s in r["plan"]}
        self.assertEqual(states["s1"], "PROPOSED")
        self.assertEqual(states["s2"], "OK")
        self.assertEqual((states["s3"], states["s4"]), ("REPLACED", "REPLACED"))
        self.assertEqual((states["s5"], states["s6"]), ("OK", "OK"))
        self.assertEqual(r["replans"], 1)
        self.assertEqual(r["status"], "DONE")

    def test_replan_cannot_redo_completed_step(self):
        p1 = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                  st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                  st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}))
        redo = plan(st("s4", "plan", "QUERY_AREA", ["A001"]),
                    st("s5", "plan", "GEN_COVERAGE", bind={"area": "s4.area_record"}))
        m = scripted(['{"directions":["plan"]}', p1, redo, redo])
        _, T = tools(["A001"])
        T["gen_coverage"] = lambda ref: {"status": "NO_ROUTE"}
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢")
        self.assertEqual(r["replans"], 2)                       # 重規劃 1 次＋修正 1 次，額度用完
        self.assertFalse(any(s["id"] == "s4" for s in r["plan"]))
        self.assertNotEqual(r["status"], "DONE")

    def test_bind_reads_source_step_not_global(self):
        # s3 合格、s6 不合格；s7 的 when 引用 s3 → 應執行（若讀全域最新的 s6 會誤判 SKIPPED）
        p = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                 st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                 st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                 st("s4", "plan", "QUERY_AREA", ["A003"], after=["s3"]),
                 st("s5", "plan", "GEN_COVERAGE", bind={"area": "s4.area_record"}),
                 st("s6", "plan", "VERIFY_PREVIEW", bind={"route": "s5.coverage_route"}),
                 st("s7", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                    when="s3.route_preview.verdict==pass", after=["s6"]))
        m = scripted(['{"directions":["plan","ui"]}', p])
        _, T = tools(["A001", "A003", "U100"])
        n = {"v": 0}

        def verify(ref):
            n["v"] += 1
            return {"result": "pass" if n["v"] == 1 else "fail", "preview_ref": f"PV{n['v']}", "est_end_pct": 50.0}
        T["verify_preview"] = verify
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側和南側巡檢，北側放到首頁")
        s7 = next(s for s in r["plan"] if s["id"] == "s7")
        self.assertEqual(s7["state"], "PROPOSED")
        self.assertEqual(r["proposals"][0]["source"], {"preview_ref": "PV1", "verdict": "pass"})

    def test_missing_required_bind_rejected(self):
        noind = plan(st("s1", "plan", "QUERY_AREA", ["A001"]), st("s2", "plan", "GEN_COVERAGE", after=["s1"]))
        m = scripted(['{"directions":["plan"]}', noind, noind, noind])
        _, T = tools(["A001"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢")
        self.assertEqual(r["replans"], 2)
        self.assertIn("計畫無效或未呼叫模型，改用規則計畫", r["notes"])

    def test_weird_types_plan_does_not_crash(self):
        bad = plan(dict(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]), after=[[]]))
        m = scripted(['{"directions":["color"]}', bad, plan(st("s1", "color", "UI_THEME_PROPOSE", ["T001"]))])
        _, T = tools(["T001"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("改成深色主題")
        self.assertEqual(r["replans"], 1)
        self.assertEqual(len(r["proposals"]), 1)

    def test_preset_directions_shared_from_a(self):
        m = scripted([PLAN_UI])
        _, T = tools(["A001", "U100"])
        r = PlanBController(T, m, GRAPH, COUNTER, preset={"directions": ["plan", "ui"], "stage1_calls": 1}).request(
            "規劃北側巡檢放到首頁")
        self.assertEqual([t["purpose"] for t in r["traces"]], ["stage1_shared", "plan"])
        self.assertEqual(r["calls_used"], 2)
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

    # ---- v4（CODEX-APP-0408）----
    def test_missing_bound_result_triggers_replan(self):
        p1 = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                  st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                  st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                  st("s4", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}, when="s3.route_preview.verdict==fail"),
                  st("s5", "plan", "VERIFY_PREVIEW", bind={"route": "s4.coverage_route"}))
        dup = plan(st("s6", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}))   # 和 s3 完全相同 → 不合格
        m = scripted(['{"directions":["plan"]}', p1, dup, '{"steps":[]}'])
        _, T = tools(["A001"])
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢")
        states = {x["id"]: x["state"] for x in r["plan"]}
        self.assertEqual(states["s4"], "SKIPPED")               # 合法略過的來源保留
        self.assertEqual(states["s5"], "REPLACED")               # 重規劃決定不再需要 s5
        self.assertNotIn("s6", states)
        self.assertEqual(r["replans"], 2)
        self.assertEqual(r["status"], "DONE")

    def test_terminal_preset_does_not_reask_stage1(self):
        m = scripted([])
        _, T = tools([])
        pre = {"directions": [], "stage1_calls": 1,
               "terminal": {"status": "PARKED", "reply_zh": "請先選最多 3 件", "reason": "方向 4 個超過上限 3"}}
        r = PlanBController(T, m, GRAPH, COUNTER, preset=pre).request("文字放大改深色切規則模式查手冊")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(m.calls, [])
        self.assertEqual(r["calls_used"], 1)

    def test_runner_rescores_by_step_source(self):
        from . import planb_runner as PR
        case = {"id": "X", "expect_proposals": [{"action": "PROPOSE_HOME_ROUTE", "ids": ["U100"], "values": []}],
                "expect_artifacts": {"route_preview": "pass"}, "expect_status": "DONE", "gold_dirs": ["plan", "ui"],
                "expect_dependency": {"PROPOSE_HOME_ROUTE": "pass_preview"}}
        prop = {"action": "PROPOSE_HOME_ROUTE", "ids": ["U100"], "params": {}, "state": "PROPOSED", "t_ready_s": 1.0,
                "source": {"preview_ref": "PV1", "verdict": "pass"}}
        reply = {"status": "DONE", "proposals": [prop], "artifacts": {"route_preview": {"ref": "PV2", "verdict": "pass"}},
                 "result_preview": {"ref": "PV1", "verdict": "pass"},
                 "plan": [{"id": "s3", "action": "VERIFY_PREVIEW", "state": "OK", "out": {"route_preview": {"ref": "PV1", "verdict": "pass"}}},
                          {"id": "s6", "action": "VERIFY_PREVIEW", "state": "OK", "out": {"route_preview": {"ref": "PV2", "verdict": "pass"}}}]}
        self.assertFalse(PR.R4.score(case, reply)["correct"])    # 只看全域最新預覽會誤判
        orig_run, orig_rec = PR._run_case, PR.a_record
        try:
            PR._run_case = lambda *a: ({"correct": False}, {"reply": reply})
            PR.a_record = lambda c, k: ({"directions": ["plan", "ui"]}, {"directions": ["plan", "ui"], "stage1_calls": 1}, [])
            rec, _ = PR.run_case(case, {"id": "A-s6-b30"}, None, None, None, None)
        finally:
            PR._run_case, PR.a_record = orig_run, orig_rec
        self.assertTrue(rec["correct"])
        self.assertTrue(rec["rescored_by_step_source"])

    # ---- v5（CODEX-APP-0409）----
    def test_earlier_pass_later_fail_scored_by_bound_preview(self):
        from . import planb_runner as PR
        case = {"id": "X", "expect_proposals": [{"action": "PROPOSE_HOME_ROUTE", "ids": ["U100"], "values": []}],
                "expect_artifacts": {"route_preview": "pass"}, "expect_status": "DONE", "gold_dirs": ["plan", "ui"],
                "expect_dependency": {"PROPOSE_HOME_ROUTE": "pass_preview"}}
        p = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                 st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                 st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                 st("s4", "ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": "s3.route_preview"},
                    when="s3.route_preview.verdict==pass"),
                 st("s5", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}, after=["s4"]))
        m = scripted(['{"directions":["plan","ui"]}', p])
        _, T = tools(["A001", "U100"])
        n = {"v": 0}

        def verify(ref):
            n["v"] += 1
            return {"result": "pass" if n["v"] == 1 else "fail", "preview_ref": f"PV{n['v']}", "est_end_pct": 50.0}
        T["verify_preview"] = verify
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢放到首頁")
        self.assertEqual(r["artifacts"]["route_preview"]["verdict"], "fail")    # 全域最新是不合格
        self.assertEqual(r["status"], "DONE")                                   # 終態看實際綁定的合格預覽
        orig_run, orig_rec = PR._run_case, PR.a_record
        try:
            PR._run_case = lambda *a: ({"correct": False}, {"reply": r})
            PR.a_record = lambda c, k: ({"directions": r["directions"]},
                                        {"directions": r["directions"], "stage1_calls": 1}, [])
            rec, _ = PR.run_case(case, {"id": "A-s6-b30"}, None, None, None, None)
        finally:
            PR._run_case, PR.a_record = orig_run, orig_rec
        self.assertTrue(rec["correct"])

    def test_a_exception_row_isolated(self):
        import os
        import tempfile
        from . import planb_runner as PR
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "cases", "A-s6-b30", "C01"))
        open(os.path.join(d, "results.jsonl"), "w", encoding="utf-8").write(
            json.dumps({"cond": "A-s6-b30", "case": "C01", "error": "RuntimeError('x')"}) + "\n")
        json.dump({"reply": {}}, open(os.path.join(d, "cases", "A-s6-b30", "C01", "full.json"), "w", encoding="utf-8"))
        old = PR._SHARED["dir"]
        try:
            PR._SHARED["dir"] = d
            rep, preset, batches = PR.a_record("A-s6-b30", "C01")
        finally:
            PR._SHARED["dir"] = old
        self.assertTrue(preset["invalid_a"])
        self.assertIsNone(batches)

    # ---- v6（CODEX-APP-0410）----
    def test_plan_only_pass_then_fail_consistent(self):
        from . import planb_runner as PR
        case = {"id": "C01", "expect_proposals": [], "expect_artifacts": {"route_preview": "pass"},
                "expect_status": "DONE", "gold_dirs": ["plan"]}
        p = plan(st("s1", "plan", "QUERY_AREA", ["A001"]),
                 st("s2", "plan", "GEN_COVERAGE", bind={"area": "s1.area_record"}),
                 st("s3", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}),
                 st("s4", "plan", "VERIFY_PREVIEW", bind={"route": "s2.coverage_route"}, after=["s3"]))
        m = scripted(['{"directions":["plan"]}', p])
        _, T = tools(["A001"])
        n = {"v": 0}

        def verify(ref):
            n["v"] += 1
            return {"result": "pass" if n["v"] == 1 else "fail", "preview_ref": f"PV{n['v']}", "est_end_pct": 50.0}
        T["verify_preview"] = verify
        r = PlanBController(T, m, GRAPH, COUNTER).request("規劃北側巡檢")
        self.assertEqual(r["result_preview"]["ref"], "PV2")     # 沒有首頁綁定 → 最後完成的那份
        self.assertNotEqual(r["status"], "DONE")                 # 終態與計分一致：都看 PV2（不合格）
        orig_run, orig_rec = PR._run_case, PR.a_record
        try:
            PR._run_case = lambda *a: ({"correct": False}, {"reply": r})
            PR.a_record = lambda c, k: ({"directions": r["directions"]},
                                        {"directions": r["directions"], "stage1_calls": 1}, [])
            rec, _ = PR.run_case(case, {"id": "A-s6-b30"}, None, None, None, None)
        finally:
            PR._run_case, PR.a_record = orig_run, orig_rec
        self.assertFalse(rec["correct"])
        self.assertFalse(rec["claimed_done_wrong"])


if __name__ == "__main__":
    unittest.main()
