"""v3.11：手冊檢索只取手冊子句、手冊向量查詢附英文詞、--probe-only 探測。假模型，不呼叫 Ollama。"""
import unittest

from .agent_m4b import M4bController
from .test_m4b import COUNTER, GRAPH, scripted
from .test_round3 import tools3


def mq(text):
    _, T = tools3([])
    return M4bController(T, None, GRAPH, COUNTER).manual_query(text)


class ManualClause(unittest.TestCase):
    def test_g11_drops_battery_question(self):
        self.assertEqual(mq("查 QGC 手冊的羅盤校準，另外現在電量多少？"), ("查 QGC 手冊的羅盤校準", ["現在電量多少？"]))

    def test_single_clause_unchanged(self):
        for t in ("查 QGC 文件：怎麼校正羅盤", "查手冊：電池低電量時 PX4 會怎麼處理", "PX4 手冊裡返航高度的參數是什麼",
                  "PX4 文件中任務模式的航點接受半徑"):
            self.assertEqual(mq(t), (t, []), t)

    def test_both_manual_segments_kept(self):
        t = "QGC 怎麼設定地理圍欄，查一下手冊"
        self.assertEqual(mq(t), (t, []))

    def test_layout_and_plan_segments_dropped(self):
        self.assertEqual(mq("查 PX4 手冊的返航模式，然後隱藏小地圖")[0], "查 PX4 手冊的返航模式")
        self.assertEqual(mq("查 QGC 手冊的地理圍欄，接著規劃南區巡檢航線")[0], "查 QGC 手冊的地理圍欄")

    def test_uncertain_segment_kept(self):
        t = "查 PX4 手冊，電池失效保護參數"
        self.assertEqual(mq(t), (t, []))

    def test_no_manual_segment_returns_original(self):
        t = "現在電量多少？另外隱藏小地圖"
        self.assertEqual(mq(t), (t, []))


class VectorEnglish(unittest.TestCase):
    def test_terms_appended(self):
        from .rag_index import QUERY_GLOSSARY_V3, vector_query_text
        self.assertEqual(vector_query_text("查 QGC 文件：怎麼校正羅盤", QUERY_GLOSSARY_V3),
                         "查 QGC 文件：怎麼校正羅盤 compass calibration calibrate")
        self.assertEqual(vector_query_text("查 QGC 手冊的羅盤校準", QUERY_GLOSSARY_V3),
                         "查 QGC 手冊的羅盤校準 calibration compass calibrate")
        self.assertEqual(vector_query_text("沒有命中", QUERY_GLOSSARY_V3), "沒有命中")

    def test_agent_sends_clause_to_bm25_and_english_to_vector(self):
        seen, emb = {}, []
        m = scripted(['{"directions":["manual","qa"]}', '{"action":"MANUAL_SEARCH","ids":[],"params":{}}'])
        _, T = tools3([])
        T["embed_query"] = lambda text: emb.append(text) or [0.0]
        T["manual_search"] = lambda text, qv, **kw: seen.update(text=text, qv=qv, **kw) or {"results": [], "degraded": False}
        c = M4bController(T, m, GRAPH, COUNTER)
        c.request("查 QGC 手冊的羅盤校準，另外現在電量多少？")
        self.assertEqual(seen["text"], "查 QGC 手冊的羅盤校準")                       # BM25：子句、不附英文詞
        self.assertEqual(emb[-1], "查 QGC 手冊的羅盤校準 calibration compass calibrate")   # 向量：子句＋英文詞
        self.assertEqual(emb[0], "查 QGC 手冊的羅盤校準，另外現在電量多少？")           # 圖譜仍用原句
        self.assertEqual(seen["manual"], "qgc")

    def test_switches_off_restore_v310(self):
        from . import rag_index as RI
        old = dict(RI.RAG_SETTINGS)
        try:
            RI.RAG_SETTINGS.update(manual_clause=False, vector_en=False)
            seen, emb = {}, []
            m = scripted(['{"directions":["manual"]}', '{"action":"MANUAL_SEARCH","ids":[],"params":{}}'])
            _, T = tools3([])
            T["embed_query"] = lambda text: emb.append(text) or [0.0]
            T["manual_search"] = lambda text, qv, **kw: seen.update(text=text) or {"results": [], "degraded": False}
            M4bController(T, m, GRAPH, COUNTER).request("查 QGC 文件：怎麼校正羅盤")
            self.assertEqual(seen["text"], "查 QGC 文件：怎麼校正羅盤")
            self.assertEqual(len(emb), 1)                                              # 沒有額外 embedding
        finally:
            RI.RAG_SETTINGS.clear()
            RI.RAG_SETTINGS.update(old)


class ProbeV311(unittest.TestCase):
    def test_probe_rows_variants_and_cache(self):
        import os
        from . import m4b_runner as R4
        d = r"C:/Users/Administrator/Documents/碩士論文/adr0002_rag_v1/index_v1"
        if not os.path.exists(os.path.join(d, "INDEX_MANIFEST.json")):
            self.skipTest("缺凍結索引")
        R4.R.set_manual_index(R4.R.DEFAULT_INDEX_DIR, "http://127.0.0.1:1", use_vector=False)
        p = R4.retrieval_probe_v311(GRAPH)
        self.assertEqual(len(p["rows"]), 36)                                          # 12 題 × 三種查詢
        g11 = {r["variant"]: r for r in p["rows"] if r["case"] == "G11"}
        self.assertEqual(g11["clause"]["lexical_query"], "查 QGC 手冊的羅盤校準")
        self.assertTrue(g11["clause_en"]["vector_query"].endswith("compass calibrate"))
        self.assertEqual(g11["clause_en"]["lexical_query"], g11["clause"]["lexical_query"])
        f20 = {r["variant"]: r for r in p["rows"] if r["case"] == "F20"}
        self.assertEqual(f20["clause"]["lexical_query"], f20["full"]["lexical_query"])   # 單一子句：與原句相同
        self.assertTrue(R4.probe_blocked(p))                                         # 離線沒有查詢向量 → live 會擋
        self.assertIn("clause_en", p["acceptance"])


if __name__ == "__main__":
    unittest.main()
