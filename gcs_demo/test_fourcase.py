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


if __name__ == "__main__":
    unittest.main()
