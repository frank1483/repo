"""ADR-0002 向量檢索（手冊方向）測試：索引完整性、檢索出處、降級、迴圈接線。不需要 LLM；查詢向量用本機 Ollama 的 EmbeddingGemma 2。
首次執行由 Claude 負責，結果與失敗原樣保留。"""
import json
import os
import shutil
import tempfile
import unittest

from . import rag_index as R
from .agent_controller import Controller
from .test_agent_controller import FakeModel

INDEX = os.environ.get("GCS_MANUAL_INDEX", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "adr0002_rag_v1", "index_v1"))


def setUpModule():
    global IDX
    IDX = R.Index(INDEX)


class IndexIntegrity(unittest.TestCase):
    def test_manifest_fields(self):
        m = IDX.man
        for k in ("corpus", "chunk_policy", "embedding_model_manifest_sha256", "dimension", "prefix_query",
                  "prefix_document", "vector_file_hash", "lexical_index_hash", "n_chunks"):
            self.assertIn(k, m)
        self.assertEqual(m["n_chunks"], len(IDX.chunks))
        self.assertEqual(len(IDX.vec), m["n_chunks"] * m["dimension"])
        self.assertLessEqual(m["n_chunks"], R.MAX_CHUNKS)

    def test_tampered_index_refused(self):
        tmp = tempfile.mkdtemp(prefix="rag_")
        try:
            dst = os.path.join(tmp, "idx")
            shutil.copytree(INDEX, dst)
            with open(os.path.join(dst, "chunks.jsonl"), "a", encoding="utf-8") as f:
                f.write("{}\n")
            with self.assertRaises(SystemExit):
                R.Index(dst)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_query_embedding_deterministic(self):
        a = R.embed([R.PREFIX_QUERY.format(query="return altitude")])[0]
        b = R.embed([R.PREFIX_QUERY.format(query="return altitude")])[0]
        self.assertEqual(len(a), IDX.dim)
        self.assertLess(max(abs(x - y) for x, y in zip(a, b)), 1e-6)


class Search(unittest.TestCase):
    def test_results_have_provenance_and_cap(self):
        r = IDX.search("PX4 return altitude parameter RTL")
        self.assertEqual(r["status"], "OK")
        self.assertLessEqual(len(r["results"]), 5)
        for x in r["results"]:
            for k in ("manual", "path", "version", "heading_path", "chunk_id", "text"):
                self.assertIn(k, x)
        self.assertFalse(r["degraded"])

    def test_return_altitude_hits_rtl_docs(self):
        r = IDX.search("返航高度的參數")
        txt = " ".join((x["path"] + " " + x["text"]).lower() for x in r["results"])
        self.assertTrue("rtl" in txt or "return" in txt, [x["path"] for x in r["results"]])

    def test_geofence_glossary(self):
        r = IDX.search("QGC 怎麼設定地理圍欄")
        txt = " ".join((x["path"] + " " + x["text"]).lower() for x in r["results"])
        self.assertIn("geofence", txt)

    def test_keyword_only_marked_degraded(self):
        r = IDX.search("geofence", use_vector=False)
        self.assertTrue(r["degraded"])

    def test_no_duplicate_chunks(self):
        r = IDX.search("battery failsafe")
        ids = [x["chunk_id"] for x in r["results"]]
        self.assertEqual(len(ids), len(set(ids)))


class LoopWiring(unittest.TestCase):
    def test_manual_direction_done_with_refs(self):
        tools = {"manual_search": lambda text: IDX.search(text)}
        r = Controller(tools, FakeModel(["manual"])).request("PX4 手冊裡返航高度的參數是什麼")
        self.assertEqual(r["status"], "DONE", r)
        self.assertIn("手冊出處：PX4", r["reply_zh"])

    def test_manual_not_loaded_is_not_done(self):
        r = Controller({}, FakeModel(["manual"])).request("PX4 手冊裡返航高度的參數是什麼")
        self.assertNotEqual(r["status"], "DONE")
        self.assertIn("手冊尚未載入", r["reply_zh"])


if __name__ == "__main__":
    unittest.main()
