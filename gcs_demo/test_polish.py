"""v3.12 回覆潤飾（演算法說明 v3.12 §9）：規則版、假模型，不呼叫 Ollama。"""
import inspect
import json
import re
import unittest

from . import reply_polish as RP
from .agent_m4b import FLIGHT_NOTICE, M4bController
from .agent_planb import PlanBController
from .test_m4b import COUNTER, GRAPH, tools

SLOT = re.compile(r"⟦[A-Z]+[1-9][0-9]*⟧")


def echo_model(prefix="好的，", sep="；", calls=None):
    """除了潤飾，其他呼叫都回不合法（走關鍵字表與規則腳本）；潤飾時把事實裡的佔位符逐一照抄成一句。"""
    def model(call):
        if calls is not None:
            calls.append(call["purpose"])
        if call["purpose"] != "polish":
            return "not json"
        slots = SLOT.findall(call["messages"][1]["content"])
        return json.dumps({"reply": prefix + sep.join(slots) + "。"}, ensure_ascii=False)
    return model


def facts_one():
    f = RP.Facts()
    lock = "預估落地電量 61.5%（出處：預覽 PV1）"
    f.add("number", "預覽驗算合格，" + f.slot("number", lock), "預覽驗算合格，" + lock)
    f.add("source", "手冊出處：" + f.slot("source", "QGC a/b.md（Compass）"), "手冊出處：QGC a/b.md（Compass）")
    return f


class CheckRules(unittest.TestCase):
    def setUp(self):
        self.f = facts_one()
        self.t = self.f.template()

    def chk(self, reply, obj=None):
        return RP.check(json.dumps(obj if obj is not None else {"reply": reply}, ensure_ascii=False), self.f, self.t)

    def test_accepts_and_restores_verbatim(self):
        ok, final, why = self.chk("預覽驗算合格，⟦N1⟧。可參考⟦S1⟧。")
        self.assertEqual((ok, why), (True, ""))
        self.assertIn("預估落地電量 61.5%（出處：預覽 PV1）", final)
        self.assertIn("QGC a/b.md（Compass）", final)

    def test_each_rule_has_a_counterexample(self):
        cases = {
            "format": [None, {"reply": "⟦N1⟧⟦S1⟧", "x": 1}, {"reply": ""}, {"text": "⟦N1⟧⟦S1⟧"}],
            "slots": ["⟦N1⟧", "⟦N1⟧⟦S1⟧⟦S1⟧", "⟦N1⟧⟦S1⟧⟦P9⟧", "⟦N1⟧ ⟦S1 ⟧"],
            "own_number": ["⟦N1⟧，⟦S1⟧，大約42", "⟦N1⟧⟦S1⟧，還剩四十二%", "⟦N1⟧⟦S1⟧百分之六十", "⟦N1⟧⟦S1⟧，４２"],
            "forbidden_claim": ["已幫你套用：⟦N1⟧⟦S1⟧", "⟦N1⟧⟦S1⟧，已寫入首頁", "⟦N1⟧⟦S1⟧已確認"],
            "too_long": ["⟦N1⟧⟦S1⟧" + "好" * 400],
            "charset": ["⟦N1⟧⟦S1⟧😀"],
        }
        for why, rs in cases.items():
            for r in rs:
                if isinstance(r, dict):
                    ok, final, got = self.chk(None, r)
                elif r is None:
                    ok, final, got = RP.check("not json", self.f, self.t)
                else:
                    ok, final, got = self.chk(r)
                self.assertEqual((ok, final, got), (False, None, why), r)


class ControllerPolish(unittest.TestCase):
    def test_polished_reply_keeps_numbers_and_sources_verbatim(self):
        calls = []
        _, T = tools(["A001"])
        r = M4bController(T, echo_model(calls=calls), GRAPH, COUNTER).request("規劃A區巡檢")
        self.assertEqual(r["reply_source"], "polished", r.get("polish"))
        self.assertIn("預覽驗算合格，預估落地電量 61.5%（出處：預覽 PV1）", r["reply_zh"])      # 合格與否也鎖住
        self.assertIn("預覽驗算合格，預估落地電量 61.5%（出處：預覽 PV1）", r["reply_template"])   # 模板與 v3.11 逐字相同
        self.assertEqual(calls.count("polish"), 1)
        self.assertEqual(r["polish"]["calls"], 1)

    def test_flight_notice_fixed_tail_not_given_to_model(self):
        seen = []

        def model(call):
            if call["purpose"] == "polish":
                seen.append(call["messages"][1]["content"])
            return echo_model()(call)
        _, T = tools(["A001"])
        r = M4bController(T, model, GRAPH, COUNTER).request("規劃A區巡檢然後起飛")
        self.assertEqual(r["reply_source"], "polished")
        self.assertTrue(r["reply_zh"].endswith(FLIGHT_NOTICE))
        self.assertNotIn(FLIGHT_NOTICE, seen[0])

    def test_proposal_slot_carries_not_written(self):
        _, T = tools(["A001", "U100"])
        r = M4bController(T, echo_model(), GRAPH, COUNTER).request("規劃北側巡檢放到首頁")
        self.assertEqual(r["reply_source"], "polished")
        self.assertIn("（尚未寫入，請在確認視窗確認）", r["reply_zh"])
        self.assertIn("已開確認視窗（尚未寫入）：", r["reply_template"])

    def test_bad_polish_falls_back_to_template_once(self):
        n = []

        def model(call):
            n.append(call["purpose"])
            return '{"reply":"已幫你套用，電量 61.5%"}' if call["purpose"] == "polish" else "not json"
        _, T = tools(["A001"])
        r = M4bController(T, model, GRAPH, COUNTER).request("規劃A區巡檢")
        self.assertEqual(r["reply_source"], "fallback:slots")
        self.assertEqual(r["reply_zh"], r["reply_template"])
        self.assertEqual(n.count("polish"), 1)                   # R2：不重試

    def test_timeout_falls_back(self):
        ticks = iter([0.0, RP.POLISH_DEADLINE_S + 0.5])
        f = facts_one()
        out = RP.polish(echo_model(), f, f.template(), "x", clock=lambda: next(ticks))
        self.assertEqual(out[1], "fallback:timeout")
        self.assertEqual(out[0], f.template())

    def test_model_exception_falls_back(self):
        def boom(call):
            raise RuntimeError("gateway 504")
        f = facts_one()
        self.assertEqual(RP.polish(boom, f, f.template(), "x")[1], "fallback:model_error")

    def test_ask_is_polished_too_numbers_locked(self):            # R3
        _, T = tools([])

        def model(call):
            if call["purpose"] == "stage1":
                return '{"directions":["layout","color","model","manual"]}'
            return echo_model(prefix="抱歉，", sep="、")(call)
        r = M4bController(T, model, GRAPH, COUNTER).request("文字放大改深色切規則模式查手冊")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(r["reply_source"], "polished", r.get("polish"))
        self.assertIn("4", r["reply_zh"])
        self.assertTrue(r["reply_template"].startswith("這句話包含 4 件事"))

    def test_alert_active_yields_zero_calls(self):
        calls = []
        _, T = tools(["A001"])
        r = M4bController(T, echo_model(calls=calls), GRAPH, COUNTER, alert_active=lambda: True).request("規劃A區巡檢")
        self.assertEqual((r["reply_source"], r["polish"]["calls"]), ("fallback:alert_active", 0))
        self.assertNotIn("polish", calls)
        self.assertEqual(r["reply_zh"], r["reply_template"])

    def test_gate_blocked_no_polish(self):
        calls = []
        c = M4bController({}, echo_model(calls=calls), GRAPH, COUNTER)
        self.assertEqual(c.request("   ")["status"], "INVALID_INPUT")
        self.assertEqual(calls, [])

    def test_no_switch_parameter(self):                           # 使用者 15:45：不需要開關
        for C in (M4bController, PlanBController):
            params = set(inspect.signature(C.__init__).parameters)
            self.assertFalse(params & {"summary_llm", "polish", "polish_enabled", "use_polish"}, C)
        with self.assertRaises(TypeError):
            M4bController({}, None, GRAPH, COUNTER, summary_llm=False)

    def test_a_and_b_share_the_same_polish_step(self):
        self.assertIs(PlanBController._facts, M4bController._facts)
        self.assertIs(PlanBController._template, M4bController._template)
        _, T = tools(["A001"])
        ra = M4bController(T, echo_model(), GRAPH, COUNTER).request("規劃A區巡檢")
        _, T = tools(["A001"])
        rb = PlanBController(T, echo_model(), GRAPH, COUNTER).request("規劃A區巡檢")
        self.assertEqual((ra["reply_source"], rb["reply_source"]), ("polished", "polished"))
        f = facts_one()
        self.assertEqual(RP.polish(echo_model(), f, f.template(), "x")[0],
                         RP.polish(echo_model(), f, f.template(), "x")[0])


if __name__ == "__main__":
    unittest.main()
