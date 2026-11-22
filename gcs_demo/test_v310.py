"""v3.10 第一批（G03、G02、G19）離線回歸。假模型，不呼叫 Ollama。"""
import unittest

from .agent_m4b import M4bController
from .test_fourcase import corr
from .test_m4b import COUNTER, GRAPH, scripted
from .test_round3 import tools3

BIG_C005 = '{"action":"UI_LAYOUT_PROPOSE","ids":["C005","P002"],"params":{"value":"放大"}}'
BIG_C012 = '{"action":"UI_LAYOUT_PROPOSE","ids":["C012","P002"],"params":{"value":"放大"}}'


class NoC012:
    """包住測試圖：檢索結果拿掉 C012，其他照舊。"""
    def __getattr__(self, k):
        return getattr(GRAPH, k)

    def retrieve(self, d, qv):
        r = GRAPH.retrieve(d, qv)
        return dict(r, candidates=[x for x in r["candidates"] if (x if isinstance(x, str) else x.get("id")) != "C012"])


class SharedClassification(unittest.TestCase):
    def test_g03_home_only_layout_becomes_plan_ui(self):
        out, fix = corr("把南側巡檢航線放到首頁", ["layout"])
        self.assertEqual(out, ["ui"])
        self.assertEqual([(f["op"], f["dir"]) for f in fix], [("add", "ui"), ("remove", "layout")])
        m = scripted(['{"directions":["layout"]}'])
        _, T = tools3([])
        c = M4bController(T, m, GRAPH, COUNTER)
        t = {"text": "把南側巡檢航線放到首頁", "notes": [], "traces": [], "artifacts": {}, "rules": "",
             "ledger": __import__("gcs_demo.agent_m4b", fromlist=["Ledger"]).Ledger()}
        self.assertEqual(c._directions(t), ["plan", "ui"])        # 缺預覽 → 既有 plan 前置補上

    def test_g02_layout_only_drops_plan_and_chat(self):
        self.assertEqual(corr("風速計收起來", ["plan"])[0], ["layout"])
        self.assertEqual(corr("風速計收起來", ["chat"])[0], ["layout"])

    def test_mixed_sentence_keeps_plan(self):
        out, _ = corr("南區規劃航線，然後隱藏風速計", ["plan"])
        self.assertEqual(set(out), {"plan", "layout"})
        out, _ = corr("南區規劃航線，然後放大高度顯示", ["plan", "layout"])
        self.assertEqual(out, ["plan", "layout"])

    def test_chat_kept_without_operation(self):
        self.assertEqual(corr("你好", ["chat"])[0], ["chat"])
        self.assertEqual(corr("不要隱藏小地圖", ["chat"])[0], ["chat"])

    def test_g02_rule_group_done_a_and_b(self):
        from .agent_planb import PlanBController
        for C in (M4bController, PlanBController):
            _, T = tools3(["C008", "P004"])
            r = C(T, None, GRAPH, COUNTER).request("風速計收起來")
            self.assertEqual(r["directions"], ["layout"], C.__name__)
            self.assertEqual((r["status"], len(r["proposals"])), ("DONE", 1), C.__name__)


class HomeClause(unittest.TestCase):
    """v3.10 反例 1：只有明確要求把成果放到首頁才補 ui。"""
    def test_question_and_manual_do_not_add_ui(self):
        for t, d in [("北側巡檢航線是否已顯示在首頁？", ["qa"]), ("北側巡檢航線已經顯示在首頁了嗎", ["qa"]),
                     ("查 QGC 手冊：首頁的航線顯示功能", ["manual"]), ("PX4 文件裡首頁顯示航線的設定", ["manual"]),
                     ("首頁的北側巡檢航線有沒有更新", ["qa"])]:
            self.assertNotIn("ui", corr(t, d)[0], t)

    def test_positive_home_kept(self):
        self.assertEqual(corr("把南側巡檢航線放到首頁", ["layout"])[0], ["ui"])          # G03
        self.assertEqual(corr("規劃北側二航線並顯示在首頁", ["plan", "ui"]), (["plan", "ui"], None))   # C13
        self.assertEqual(corr("規劃北側二航線並顯示在首頁", ["plan"])[0], ["plan", "ui"])


class G19Candidates(unittest.TestCase):
    def test_named_component_reserved_and_wrong_rejected(self):
        m = scripted(['{"directions":["layout"]}', BIG_C005, BIG_C005, BIG_C005, BIG_C005])
        _, T = tools3(["C005", "P002"])
        c = M4bController(T, m, NoC012(), COUNTER)              # 檢索候選拿掉 C012（重現 G19）
        r = c.request("放大高度顯示")
        self.assertEqual([(p["ids"], p["params"]) for p in r["proposals"]], [(["C012", "P002"], {"value": "放大"})])
        self.assertEqual(r["status"], "DONE")
        self.assertTrue(any("列為必要候選" in n for n in r["notes"]))

    def test_must_candidate_counted_in_budget(self):
        """v3.10 反例 2：點名元件要在分批時就列為必要候選，送出的內容與預算紀錄一致、不超過上限。"""
        from .id_graph import BUDGET_DIR
        m = scripted(['{"directions":["layout"]}', BIG_C012])
        _, T = tools3(["C005", "P002"])
        c = M4bController(T, m, NoC012(), lambda text: len(text) * 4)   # 很貴的計數器：可選資料一定會被修剪
        r = c.request("放大高度顯示")
        pd = r["packing"]["batches"][0]["per_dir"]["layout"]
        self.assertIn("C012", pd["items"])
        self.assertLessEqual(pd["tokens"], pd["cap"])
        self.assertTrue(r["packing"]["batches"][0]["log"]["trimmed"].get("layout"))
        self.assertEqual(r["packing"]["batches"][0]["log"]["must"], {"layout": ["C012"]})
        self.assertEqual(r["proposals"][0]["ids"], ["C012", "P002"])
        self.assertGreaterEqual(BUDGET_DIR, 1)

    def test_model_can_pick_reserved(self):
        m = scripted(['{"directions":["layout"]}', BIG_C012])
        _, T = tools3(["C005", "P002"])
        r = M4bController(T, m, NoC012(), COUNTER).request("放大高度顯示")
        self.assertEqual([p["by"] for p in r["proposals"]], ["model"])
        self.assertEqual(r["proposals"][0]["ids"], ["C012", "P002"])

    def test_mismatch_and_dedupe(self):
        _, T = tools3([])
        c = M4bController(T, None, GRAPH, COUNTER)
        t = {"layout_items": [("C012", "P002", "放大")], "proposals": []}
        self.assertIn("不符合", c._layout_mismatch(t, "C005", "P002", "放大"))
        self.assertIn("不符合", c._layout_mismatch(t, "C012", "P002", "縮小"))
        self.assertEqual(c._layout_mismatch(t, "C012", "P002", "放大"), "")
        t["proposals"] = [{"direction": "layout", "ids": ["C012", "P002"], "params": {"value": "放大"}}]
        self.assertIn("已經開過", c._layout_mismatch(t, "C012", "P002", "放大"))
        self.assertEqual(c._layout_mismatch({"proposals": []}, "C005", "P002", "放大"), "")   # 沒有明確項目：沿用舊判定

    def test_b_rejects_wrong_and_duplicate_plan(self):
        from .agent_planb import PlanBController
        from .test_planb import plan, st
        wrong = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C005", "P002"], {"value": "放大"}),
                     st("s2", "layout", "UI_LAYOUT_PROPOSE", ["C012", "P002"], {"value": "放大"}))
        dup = plan(st("s1", "layout", "UI_LAYOUT_PROPOSE", ["C012", "P002"], {"value": "放大"}),
                   st("s2", "layout", "UI_LAYOUT_PROPOSE", ["C012", "P002"], {"value": "放大"}))
        m = scripted(['{"directions":["layout"]}', wrong, dup, dup])
        _, T = tools3(["C005", "P002"])
        r = PlanBController(T, m, NoC012(), COUNTER).request("放大高度顯示")
        self.assertEqual([(p["ids"], p["params"]) for p in r["proposals"]], [(["C012", "P002"], {"value": "放大"})])
        self.assertEqual(r["status"], "DONE")
        reasons = " ".join(e.get("reason", "") for e in r["plan_log"])
        self.assertIn("不符合", reasons)


if __name__ == "__main__":
    unittest.main()
