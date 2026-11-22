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


if __name__ == "__main__":
    unittest.main()
