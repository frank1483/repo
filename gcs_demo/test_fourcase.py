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


if __name__ == "__main__":
    unittest.main()
