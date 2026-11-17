"""ADR-0002 M2 迴圈控制器的假模型案例（迴圈控制器演算法說明 v1 §7）。不接真模型。
首次執行由 Claude 負責，結果與失敗原樣保留。"""
import json
import os
import re
import unittest

from .agent_controller import Controller, Ledger
from .gate_l1 import gate

VEC = os.path.join(os.path.dirname(__file__), "gate_l1_vectors_v1.json")


def allowed_of(call):
    m = re.search(r"只能選：(.*)", call["messages"][1]["content"])
    return [x.split(" ")[0] for x in m.group(1).split("｜")] if m else []


class FakeModel:
    """依策略回固定代碼；kinds 是方向判斷的回覆。"""

    def __init__(self, kinds=None, strategy="work", raw=None):
        self.kinds = kinds
        self.strategy = strategy
        self.raw = raw
        self.calls = 0

    def __call__(self, call):
        self.calls += 1
        content = call["messages"][1]["content"]
        if "可選：" in content and '"kinds"' in content:
            return json.dumps({"kinds": self.kinds}) if self.kinds is not None else "亂碼"
        if self.raw is not None:
            return self.raw(call) if callable(self.raw) else self.raw
        al = allowed_of(call)
        if self.strategy == "finish":
            return '{"value":"FINISH"}'
        if self.strategy == "hold":
            return '{"value":"HOLD"}'
        work = [a for a in al if a not in ("FINISH", "HOLD")]
        return json.dumps({"value": work[0] if work else ("FINISH" if "FINISH" in al else al[0])})


class Tools(dict):
    def __init__(self, area="ONE", verdict="pass", claims=True):
        super().__init__()
        self.count = {}

        def wrap(name, fn):
            def f(*a):
                self.count[name] = self.count.get(name, 0) + 1
                return fn(*a)
            return f
        self["query_area"] = wrap("query_area", lambda t: {"status": area, "candidates": ["北側", "北側二"][:1 if area == "ONE" else 2] if area != "NONE" else []})
        self["gen_coverage"] = wrap("gen_coverage", lambda a: {"status": "OK", "route_ref": "cg-v2:r1"})
        self["verify_preview"] = wrap("verify_preview", lambda r: {"preview_ref": "rp-1", "result": verdict, "est_end_pct": 62.0})
        self["propose_home_route"] = wrap("propose_home_route", lambda p: {"shown_hash": "sh-1"})
        self["qa_lookup"] = wrap("qa_lookup", lambda t: {"claims": [{"text": "x", "src": "manual"}] if claims else [], "ref": "q1"})
        self["report_draft"] = wrap("report_draft", lambda a: {"ref": "rep-1"})


TEXT = "北側巡檢，留 25%，放到首頁"


class Flows(unittest.TestCase):
    def test_ac1_plan_then_ui(self):
        t = Tools()
        r = Controller(t, FakeModel(["plan", "ui"])).request(TEXT)
        acts = [s["action"] for s in r["steps"]]
        self.assertEqual(r["status"], "DONE", r)
        for a in ("QUERY_AREA", "GEN_COVERAGE", "VERIFY_PREVIEW", "PROPOSE_HOME_ROUTE"):
            self.assertIn(a, acts)
        self.assertLess(acts.index("VERIFY_PREVIEW"), acts.index("PROPOSE_HOME_ROUTE"))
        self.assertTrue(all(s == "model" for s in r["sources"]))
        self.assertIn("出處：預覽 rp-1", r["reply_zh"])

    def test_ac2_missing_area_then_drawn(self):
        t = Tools(area="NONE")
        c = Controller(t, FakeModel(["plan", "ui"]))
        r = c.request(TEXT)
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(r["questions"][0]["field"], "boundary")
        self.assertEqual(t.count.get("gen_coverage", 0), 0)
        steps_before = len(r["steps"])
        r2 = c.resume(r["task_id"], [{"field": "boundary", "value": "area-1"}])
        self.assertEqual(r2["status"], "DONE", r2)
        self.assertEqual(t.count["gen_coverage"], 1)
        self.assertGreater(len(r2["steps"]), steps_before)       # 接續，不重設

    def test_ac5_two_candidates_ask_choice(self):
        t = Tools(area="MANY")
        m = FakeModel(["plan", "ui"])
        c = Controller(t, m)
        r = c.request(TEXT)
        self.assertEqual(r["questions"][0]["field"], "area_choice")
        self.assertEqual(len(r["questions"][0]["options"]), 2)
        self.assertEqual(t.count.get("gen_coverage", 0), 0)

    def test_failed_preview_never_proposes(self):
        t = Tools(verdict="fail")
        r = Controller(t, FakeModel(["plan", "ui"])).request(TEXT)
        self.assertEqual(t.count.get("propose_home_route", 0), 0)
        self.assertEqual(r["directions"]["ui"], "INCOMPLETE")
        self.assertNotEqual(r["status"], "DONE")

    def test_first_step_finish_is_not_success(self):
        t = Tools()
        r = Controller(t, FakeModel(["plan", "ui"], strategy="finish")).request(TEXT)
        self.assertEqual(r["directions"]["plan"], "INCOMPLETE")
        self.assertEqual(r["status"], "INCOMPLETE")
        self.assertEqual(sum(t.count.values()), 0)

    def test_hold_is_failed_safe(self):
        t = Tools()
        r = Controller(t, FakeModel(["plan"], strategy="hold")).request(TEXT)
        self.assertEqual(r["status"], "FAILED_SAFE")
        self.assertEqual(sum(t.count.values()), 0)

    def test_k_max_asks_to_split(self):
        r = Controller(Tools(), FakeModel(["plan", "ui", "qa", "report"])).request("巡檢航線放到首頁，順便報告，電池是什麼")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(r["questions"][0]["field"], "task_scope")


class Budget(unittest.TestCase):
    def test_budget_zero_rules_complete(self):
        t = Tools()
        m = FakeModel(["plan", "ui"])
        r = Controller(t, m, ledger_cfg={"per_sentence": 0}).request(TEXT)
        self.assertEqual(m.calls, 0)
        self.assertEqual(r["status"], "DONE")
        self.assertTrue(all(s == "rule" for s in r["sources"]))

    def test_budget_one_only_directions(self):
        m = FakeModel(["plan", "ui"])
        r = Controller(Tools(), m, ledger_cfg={"per_sentence": 1}).request(TEXT)
        self.assertEqual(m.calls, 1)
        self.assertEqual(r["calls_used"], 1)
        self.assertTrue(all(s == "rule" for s in r["sources"]))

    def test_never_exceeds_budget_with_repairs(self):
        m = FakeModel(["plan", "ui"], raw="亂碼")
        r = Controller(Tools(), m, ledger_cfg={"per_sentence": 5}).request(TEXT)
        self.assertLessEqual(m.calls, 5)
        self.assertEqual(r["calls_used"], m.calls)


class ModelFaults(unittest.TestCase):
    def test_garbage_repair_once_then_rule(self):
        # run1（m2_controller_run1）此案例失敗：預設每句 12 次預算在第 6 步用完，測試預期沒算到預算上限。
        # 行為正確（預算被遵守），只修正測試：放寬預算觀察「每步 2 次」，另加預設預算下的上限斷言。
        m = FakeModel(["plan", "ui"], raw="亂碼")
        r = Controller(Tools(), m, ledger_cfg={"per_sentence": 50, "per_task": 50}).request(TEXT)
        self.assertEqual(r["status"], "DONE")
        self.assertTrue(all(s == "rule" for s in r["sources"]))
        self.assertEqual(m.calls, 1 + 2 * len(r["steps"]))      # 方向 1 次＋每步 2 次（原答＋修正）
        m2 = FakeModel(["plan", "ui"], raw="亂碼")
        r2 = Controller(Tools(), m2).request(TEXT)
        self.assertEqual(m2.calls, 12)                          # 預設每句上限
        self.assertEqual(r2["status"], "DONE")

    def test_out_of_list_code_rejected(self):
        m = FakeModel(["plan"], raw='{"value":"TAKEOFF"}')
        r = Controller(Tools(), m).request("北側巡檢")
        self.assertNotIn("TAKEOFF", [s["action"] for s in r["steps"]])

    def test_lenient_prefix_accepted(self):
        def raw(call):
            al = allowed_of(call)
            work = [a for a in al if a not in ("FINISH", "HOLD")]
            return '{"value":"%s 說明文字"}' % (work[0] if work else "FINISH")
        r = Controller(Tools(), FakeModel(["plan"], raw=raw)).request("北側巡檢")
        self.assertEqual(r["status"], "DONE")
        self.assertTrue(all(s == "model" for s in r["sources"]))

    def test_invalid_directions_fall_back_to_keywords(self):
        r = Controller(Tools(), FakeModel(None)).request(TEXT)
        self.assertIn("方向判斷無效，改用關鍵字表", r["notes"])
        self.assertIn("plan", r["directions"])

    def test_repeated_action_stops(self):
        t = Tools(claims=False)
        r = Controller(t, FakeModel(["qa"])).request("電池容量是什麼")
        self.assertEqual(r["directions"]["qa"], "INCOMPLETE")
        self.assertLessEqual(len(r["steps"]), 3)

    def test_steps_max(self):
        r = Controller(Tools(), FakeModel(["plan"]), steps_max=1).request("北側巡檢")
        self.assertEqual(r["directions"]["plan"], "INCOMPLETE")
        self.assertEqual(len(r["steps"]), 1)


class GateAndResume(unittest.TestCase):
    def test_gate_vectors_python(self):
        v = json.load(open(VEC, encoding="utf-8"))
        bad = [c["id"] for c in v["cases"] if (gate(c["text"])["status"] == "HOLD") != c["hold"]]
        self.assertEqual(bad, [])

    def test_mixed_command_never_enters_loop(self):
        t = Tools()
        m = FakeModel(["plan"])
        r = Controller(t, m).request("顯示返航點，然後立即返航")
        self.assertEqual(r["status"], "HOLD")
        self.assertEqual((m.calls, sum(t.count.values())), (0, 0))

    def test_too_long_not_truncated(self):
        r = Controller(Tools(), FakeModel(["plan"])).request("巡" * 201)
        self.assertEqual(r["status"], "TOO_LONG")

    def test_cancel_requires_confirmation(self):
        t = Tools(area="NONE")
        def raw(call):
            if "回覆的意圖" in call["messages"][1]["content"]:
                return '{"value":"CANCEL"}'
            al = allowed_of(call)
            work = [a for a in al if a not in ("FINISH", "HOLD")]
            return json.dumps({"value": work[0] if work else "FINISH"})
        c = Controller(t, FakeModel(["plan"], raw=raw))
        r = c.request("北側巡檢")
        r2 = c.resume_text(r["task_id"], "算了不要了")
        self.assertEqual(r2["status"], "PARKED")
        self.assertEqual(r2["questions"][0]["field"], "cancel_confirm")
        r3 = c.resume(r["task_id"], [{"field": "cancel_confirm", "value": False}])
        self.assertNotEqual(r3["status"], "CANCELLED")
        r2 = c.resume_text(r["task_id"], "不要了")
        r4 = c.resume(r["task_id"], [{"field": "cancel_confirm", "value": True}])
        self.assertEqual(r4["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
