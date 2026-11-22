"""v3.9 四題修正的離線回歸（F13／C14、F20、F23）。假模型，不呼叫 Ollama。"""
import json
import unittest

from .agent_m4b import M4bController
from .test_m4b import COUNTER, GRAPH, scripted
from .test_round3 import tools3


def corr(text, ds):
    _, T = tools3([])
    c = M4bController(T, None, GRAPH, COUNTER)
    t = {"text": text, "notes": []}
    return c._correct_directions(t, list(ds)), t.get("stage1_corrections")


class DirectionCorrection(unittest.TestCase):
    def test_f13_show_component_is_layout(self):
        out, fix = corr("顯示任務進度", ["ui"])
        self.assertEqual(out, ["layout"])
        self.assertEqual([f["op"] for f in fix], ["add", "remove"])

    def test_c14_home_only_drops_layout(self):
        out, _ = corr("北側巡檢放到首頁，保留 20%", ["plan", "ui", "layout"])
        self.assertEqual(out, ["plan", "ui"])

    def test_c13_show_on_home_stays_ui(self):
        out, fix = corr("規劃北側二航線並顯示在首頁", ["plan", "ui"])
        self.assertEqual((out, fix), (["plan", "ui"], None))

    def test_both_operations_kept(self):
        out, _ = corr("把北側巡檢結果放到首頁，另外隱藏小地圖", ["plan", "ui"])
        self.assertEqual(set(out), {"plan", "ui", "layout"})

    def test_negation_and_question_do_not_trigger(self):
        self.assertEqual(corr("不要隱藏小地圖", ["chat"])[0], ["chat"])
        self.assertEqual(corr("小地圖怎麼隱藏？", ["qa"])[0], ["qa"])

    def test_preview_only_unchanged(self):
        self.assertEqual(corr("北側巡檢先預覽", ["plan"]), (["plan"], None))

    def test_end_to_end_f13(self):
        m = scripted(['{"directions":["ui"]}', '{"action":"UI_LAYOUT_PROPOSE","ids":["C007","P004"],"params":{"value":"顯示"}}'])
        _, T = tools3(["C007", "P004"])
        r = M4bController(T, m, GRAPH, COUNTER).request("顯示任務進度")
        self.assertEqual(r["stage1_raw"], ["ui"])
        self.assertEqual(r["directions"], ["layout"])
        self.assertEqual([(p["ids"], p["params"]) for p in r["proposals"]], [(["C007", "P004"], {"value": "顯示"})])


class ManualSearch(unittest.TestCase):
    def test_f20_direction_manual_only(self):
        self.assertEqual(corr("查 QGC 文件：怎麼校正羅盤", ["manual", "qa"])[0], ["manual"])

    def test_manual_plus_separate_question_keeps_qa(self):
        out, _ = corr("查 QGC 文件的羅盤校正，另外現在電量多少？", ["manual", "qa"])
        self.assertEqual(set(out), {"manual", "qa"})

    def test_source_and_glossary_passed(self):
        seen = {}
        m = scripted(['{"directions":["manual"]}', '{"action":"MANUAL_SEARCH","ids":[],"params":{}}'])
        _, T = tools3([])
        T["manual_search"] = lambda text, qv, **kw: seen.update(kw) or {"results": [], "degraded": False}
        r = M4bController(T, m, GRAPH, COUNTER).request("查 QGC 文件：怎麼校正羅盤")
        self.assertEqual(seen["manual"], "qgc")
        self.assertEqual(seen["extra"]["羅盤"], ["compass"])
        self.assertTrue(any("查無可用出處" in n for n in r["notes"]))

    def test_unspecified_source_is_none(self):
        self.assertIsNone(M4bController._manual_source(None, "手冊裡怎麼設定任務航點"))
        self.assertEqual(M4bController._manual_source(None, "PX4 手冊的參數"), "px4")

    def test_real_index_filter_and_glossary_unchanged(self):
        import os
        from . import rag_index as RI
        d = r"C:/Users/Administrator/Documents/碩士論文/adr0002_rag_v1/index_v1"
        if not os.path.exists(os.path.join(d, "INDEX_MANIFEST.json")):
            self.skipTest("缺凍結索引")
        idx = RI.Index(d)
        r = idx.search("查 QGC 文件：怎麼校正羅盤", k=10, use_vector=False, manual="qgc", extra=RI.QUERY_GLOSSARY_V2)
        self.assertTrue(r["results"] and all(x["manual"] == "qgc" for x in r["results"]))
        man = json.load(open(os.path.join(d, "INDEX_MANIFEST.json"), encoding="utf-8"))
        self.assertEqual(man["glossary_hash"], RI.sha(json.dumps(RI.GLOSSARY, sort_keys=True)))   # 既有詞表沒動


HIDE = '{"action":"UI_LAYOUT_PROPOSE","ids":["C016","P004"],"params":{"value":"隱藏"}}'
BIG = '{"action":"UI_LAYOUT_PROPOSE","ids":["P001"],"params":{"value":"大"}}'
F23 = "隱藏小地圖並把字體調大"


class MultiLayoutA(unittest.TestCase):
    def run_a(self, replies, text=F23):
        m = scripted(['{"directions":["layout"]}'] + replies)
        _, T = tools3(["C016", "P004", "P001"])
        return M4bController(T, m, GRAPH, COUNTER).request(text)

    def test_parse_items(self):
        _, T = tools3([])
        c = M4bController(T, None, GRAPH, COUNTER)
        self.assertEqual(c.parse_layout_items(F23), [("C016", "P004", "隱藏"), (None, "P001", "大")])
        self.assertEqual(c.parse_layout_items("把高度顯示縮小"), [("C012", "P002", "縮小")])
        self.assertEqual(c.parse_layout_items("隱藏小地圖，隱藏小地圖"), [("C016", "P004", "隱藏")])

    def test_both_items_done(self):
        r = self.run_a([HIDE, BIG])
        self.assertEqual(r["status"], "DONE")
        self.assertEqual(len(r["proposals"]), 2)

    def test_reversed_order_done(self):
        r = self.run_a([BIG, HIDE])
        self.assertEqual(r["status"], "DONE")

    def test_only_one_then_finish_is_partial(self):
        r = self.run_a([HIDE, '{"action":"FINISH","ids":[],"params":{}}'])
        self.assertEqual(r["status"], "PARTIAL")
        self.assertEqual(len(r["proposals"]), 1)
        self.assertTrue(any("版面還缺" in n and "P001" in n for n in r["notes"]))

    def test_repeat_same_change_rejected_then_rule_fills(self):
        r = self.run_a([HIDE, HIDE, HIDE])
        self.assertEqual(sorted(tuple(p["ids"]) for p in r["proposals"]), [("C016", "P004"), ("P001",)])
        self.assertEqual(r["status"], "DONE")

    def test_single_item_exactly_one(self):
        m = scripted(['{"directions":["layout"]}', HIDE, HIDE])
        _, T = tools3(["C016", "P004"])
        r = M4bController(T, m, GRAPH, COUNTER).request("隱藏小地圖")
        self.assertEqual((r["status"], len(r["proposals"])), ("DONE", 1))

    def test_rule_fallback_opens_both(self):
        _, T = tools3(["C016", "P004", "P001"])
        r = M4bController(T, None, GRAPH, COUNTER).request(F23)
        self.assertEqual((r["status"], len(r["proposals"])), ("DONE", 2))


class MultiLayoutB(unittest.TestCase):
    def test_plan_missing_one_item_rejected(self):
        from .agent_planb import PlanBController
        from .test_planb import plan, st
        one = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "隱藏"}))
        two = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "隱藏"}),
                   st("s2", "layout", "UI_LAYOUT_PROPOSE", ["P001"], {"value": "大"}))
        m = scripted(['{"directions":["layout"]}', one, two])
        _, T = tools3(["C016", "P004", "P001"])
        r = PlanBController(T, m, GRAPH, COUNTER).request(F23)
        self.assertTrue(any("版面還缺" in e.get("reason", "") for e in r["plan_log"]))
        self.assertEqual((r["status"], len(r["proposals"])), ("DONE", 2))

    def test_rule_plan_builds_each_missing_item(self):
        from .agent_planb import PlanBController
        _, T = tools3(["C016", "P004", "P001"])
        r = PlanBController(T, None, GRAPH, COUNTER).request(F23)
        self.assertEqual((r["status"], len(r["proposals"])), ("DONE", 2))


class CounterExamples(unittest.TestCase):
    """使用者 2026-11-22 18:16 額外測試發現的反例。A、B 都走正常入口 request。"""

    def both(self, text, replies_a, plan_b, cands):
        from .agent_planb import PlanBController
        _, T = tools3(cands)
        ra = M4bController(T, scripted(replies_a), GRAPH, COUNTER).request(text)
        _, T2 = tools3(cands)
        rb = PlanBController(T2, scripted([replies_a[0], plan_b, plan_b, plan_b]), GRAPH, COUNTER).request(text)
        return ra, rb

    def test_negated_hide_opens_nothing(self):
        from .test_planb import plan, st
        ra, rb = self.both("不要隱藏小地圖", ['{"directions":["layout"]}', HIDE, HIDE],
                           plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "隱藏"})), ["C016", "P004"])
        for r in (ra, rb):
            self.assertEqual(r["proposals"], [])
            self.assertNotIn("layout", r["directions"])

    def test_negated_clause_blocks_opposite_proposal(self):
        m = scripted(['{"directions":["layout"]}', HIDE, BIG])
        _, T = tools3(["C016", "P004", "P001"])
        r = M4bController(T, m, GRAPH, COUNTER).request("不要隱藏小地圖，把字體調大")
        self.assertEqual([tuple(p["ids"]) for p in r["proposals"]], [("P001",)])

    def test_missing_position_not_done(self):
        from .test_planb import plan, st
        mv = '{"action":"UI_LAYOUT_PROPOSE","ids":["C014","P003"],"params":{"value":"左上"}}'
        ra, rb = self.both("隱藏小地圖，然後把風速計移動", ['{"directions":["layout"]}', HIDE, mv, mv],
                           plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "隱藏"}),
                                st("s2", "layout", "UI_LAYOUT_PROPOSE", ["C014", "P003"], {"value": "左上"})),
                           ["C016", "P004", "C014", "P003"])
        for r in (ra, rb):
            self.assertNotEqual(r["status"], "DONE")
            self.assertEqual(r["dir_status"]["layout"], "NEEDS_USER")
            self.assertNotIn(["C014", "P003"], [p["ids"] for p in r["proposals"]])   # 不替使用者猜位置
            self.assertIn("要調成什麼", r["reply_zh"])

    def test_conflicting_changes_open_neither(self):
        from .test_planb import plan, st
        show = '{"action":"UI_LAYOUT_PROPOSE","ids":["C016","P004"],"params":{"value":"顯示"}}'
        ra, rb = self.both("隱藏小地圖，然後顯示小地圖", ['{"directions":["layout"]}', HIDE, show, show],
                           plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "隱藏"}),
                                st("s2", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "顯示"})),
                           ["C016", "P004"])
        for r in (ra, rb):
            self.assertEqual(r["proposals"], [])
            self.assertEqual(r["status"], "PARKED")
            self.assertIn("要了不同的值", r["reply_zh"])

    def test_partial_missing_item_in_reply(self):
        m = scripted(['{"directions":["layout"]}', HIDE, '{"action":"FINISH","ids":[],"params":{}}'])
        _, T = tools3(["C016", "P004", "P001"])
        r = M4bController(T, m, GRAPH, COUNTER).request(F23)
        self.assertEqual(r["status"], "PARTIAL")
        self.assertIn("版面還缺（尚未開窗）", r["reply_zh"])


class Review0429(unittest.TestCase):
    """CODEX-APP-0429 的四個阻擋。"""

    def test_question_with_wrong_layout_direction_opens_nothing(self):
        from .agent_planb import PlanBController
        from .test_planb import plan, st
        q = "小地圖怎麼隱藏？"
        self.assertEqual(corr(q, ["layout"])[0], [])
        _, T = tools3(["C016", "P004"])
        c = M4bController(T, None, GRAPH, COUNTER)
        self.assertEqual(c.parse_layout_items(q, negated=True), [("C016", "P004", "隱藏")])
        ra = M4bController(T, scripted(['{"directions":["layout"]}', HIDE, HIDE]), GRAPH, COUNTER).request(q)
        _, T2 = tools3(["C016", "P004"])
        bad = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C016", "P004"], {"value": "隱藏"}))
        rb = PlanBController(T2, scripted(['{"directions":["layout"]}', bad, bad, bad]), GRAPH, COUNTER).request(q)
        for r in (ra, rb):
            self.assertEqual(r["proposals"], [])

    def test_question_plus_positive_operation_keeps_positive(self):
        m = scripted(['{"directions":["layout"]}', HIDE, BIG])
        _, T = tools3(["C016", "P004", "P001"])
        r = M4bController(T, m, GRAPH, COUNTER).request("小地圖怎麼隱藏？先把字體調大")
        self.assertEqual([tuple(p["ids"]) for p in r["proposals"]], [("P001",)])

    def test_manual_source_by_document_phrase(self):
        src = M4bController._manual_source
        self.assertEqual(src(None, "查 QGC 手冊中怎麼連 PX4"), "qgc")
        self.assertEqual(src(None, "PX4 的文件裡怎麼用 QGC 校正"), "px4")
        self.assertEqual(src(None, "不要查 QGC 手冊，查 PX4 手冊的返航參數"), "px4")

    def test_manual_negation(self):
        self.assertNotIn("manual", corr("不要查 QGC 手冊", ["chat"])[0])
        self.assertIn("manual", corr("不要查 QGC 手冊，查 PX4 手冊的返航參數", ["chat"])[0])

    def test_probe_gate(self):
        from .m4b_runner import probe_blocked
        ok = {"rows": [{"mode": "rrf", "degraded": False}] * 8}
        self.assertFalse(probe_blocked(ok))
        self.assertTrue(probe_blocked({"rows": ok["rows"][:7] + [{"mode": "lexical_only", "degraded": True}]}))

    def test_b_does_not_rerun_probe(self):
        from . import planb_runner  # noqa: F401  匯入即設定
        from . import m4b_runner as R4m
        self.assertFalse(R4m.RUN_PROBE)
        R4m.RUN_PROBE = True

    def test_new_a_entry_uses_strict_params(self):
        import tempfile
        from . import m4b_runner as R4m
        seen = []

        def factory(log):
            def model(call):
                seen.append(call.get("schema"))
                return '{"directions":["color"]}' if call.get("purpose") == "stage1" else                     '{"action":"UI_THEME_PROPOSE","ids":["T001"],"params":{}}'
            return model
        case = {"id": "X", "text": "換成深色主題", "gold_dirs": ["color"], "expect_status": "DONE",
                "expect_proposals": [], "expect_artifacts": {}}
        cond = {"id": "A-s6-b30", "group": "A", "steps": 6, "budget": 30}
        import sys
        from . import agent_m4b
        pb = sys.modules.get("gcs_demo.planb_runner")       # 其他測試匯入 planb_runner 會改寫執行器；這裡用 A 的原始入口
        run = getattr(pb, "_run_case", R4m.run_case) if pb else R4m.run_case
        saved = R4m.M4bController
        R4m.M4bController = agent_m4b.M4bController
        try:
            run(case, cond, factory, GRAPH, COUNTER, tempfile.mkdtemp())
        finally:
            R4m.M4bController = saved
        steps = [sc for sc in seen if sc and "anyOf" in sc]
        self.assertTrue(steps)
        p = steps[0]["anyOf"][0]["properties"]["params"]
        self.assertEqual((p.get("properties"), p.get("additionalProperties")), ({}, False))

    def test_b_terminal_carries_corrections(self):
        from .agent_planb import PlanBController
        pre = {"directions": ["layout"], "stage1_calls": 1, "stage1_raw": ["ui"], "stage1_augmented": None,
               "stage1_corrections": [{"op": "add", "dir": "layout"}], "stage1_source": "model",
               "terminal": {"status": "PARKED", "reply_zh": "x", "reason": "y"}}
        rb = PlanBController({}, scripted([]), GRAPH, COUNTER, preset=pre).request("x")
        self.assertEqual(rb["stage1_corrections"], pre["stage1_corrections"])


if __name__ == "__main__":
    unittest.main()
