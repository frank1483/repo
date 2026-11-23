"""ADR-0002 G1（範圍 B，使用者 2026-11-23 11:51「g1選b」）的關鍵缺口案例：F-1 確定重讀、F-4 舊預覽重驗。規則版。"""
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from . import commit_layer as cl
from .preview_api import PreviewServer, PreviewService, SessionFeeder
from .test_commit_layer import Base as CLBase
from .test_commit_layer import PTS
from .test_preview_api import TOKEN, FakeSession
from .test_preview_api import Base as PVBase


class F1DeterministicReread(CLBase):
    def test_snapshot_discarded_when_seq_changes_during_read(self):
        """用確定的觸發（不是壓力迴圈）：第一次讀取期間 safety_seq 改變一次 → 第一份快照捨棄，重讀後成功。"""
        ing = self.c.ingest
        real_read = self.c.word.read
        calls = {"n": 0}

        def read():
            calls["n"] += 1
            g, s = real_read()
            if calls["n"] == 2:                         # 第一輪的第二次讀（s1）→ 讓它和 s0 不同
                return g, s + 1
            return g, s
        with mock.patch.object(self.c.word, "read", side_effect=read):
            seq, S = ing.snapshot(timeout_ms=500)
        self.assertGreaterEqual(calls["n"], 4)          # 至少兩輪（捨棄一次、重讀一次）
        self.assertEqual(S["policy"], {"v": 1})

    def test_hard_margin_blocks_without_event_zero_publish(self):
        """F-1 hard_margin_blocks_without_event：沒有任何安全事件，只因硬性餘裕不足就 BLOCK，且零發布。"""
        g0 = self.c.word.root_gen
        r = self.c.route_apply("t-m", "home", "r-m", PTS, "d1", 1,
                               lambda S: {"action": "BLOCK", "reasons": ["JOINT_MARGIN_BATTERY"]})
        self.assertEqual((r["action"], r["reasons"]), ("BLOCK", ["JOINT_MARGIN_BATTERY"]))
        self.assertEqual(self.c.word.root_gen, g0)
        self.assertIsNone(self.c.word.current().route("home"))


class F4OldPreviewRevalidation(PVBase):
    def _second_service(self, epoch):
        """模擬重啟：新的 boot_epoch、同一份證據儲存（上一世代的預覽仍在檔案裡）。"""
        self.srv.shutdown()
        self.srv.server_close()
        self.svc = PreviewService(self.coord, self.feeder, os.path.join(self.tmp, "ev", "p.jsonl"), boot_epoch=epoch)
        self.srv = PreviewServer(("127.0.0.1", 0), self.svc, TOKEN)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.ep = 0

    def call_e(self, path, body, epoch, expect=200):
        self.ep += 1
        b = dict({"boot_epoch": epoch, "request_epoch": self.ep}, **body)
        if path != "/api/session/open":
            b.setdefault("session_id", self.sid)
        st, js, _ = self.raw("POST", path, b)
        self.assertEqual(st, expect, js)
        return js

    def test_old_generation_preview_readonly_and_reverify_gets_new_id(self):
        p_old = self.preview()                                         # 世代 7
        self._second_service(8)
        self.sid = self.call_e("/api/session/open", {}, 8)["data"]["session_id"]
        got = self.call_e("/api/preview/get", {"artifact_id": p_old["preview_ref"]}, 8)["data"]["preview"]
        self.assertEqual(got["artifact_id"], p_old["preview_ref"])     # 舊世代預覽可唯讀查看
        js = self.call_e("/api/preview/apply_check", {"preview_ref": p_old["preview_ref"], "draft_id": "d1", "draft_rev": 1,
                                                      "target_slot_id": "home",
                                                      "target_generation": self.coord.word.current().root_gen}, 8, expect=404)
        self.assertEqual(js["error"]["code"], "NOT_FOUND")             # 不能直接套用舊物件
        a = self.call_e("/api/area/submit", {"polygon": __import__("gcs_demo.test_preview_api", fromlist=["SQUARE"]).SQUARE}, 8)["data"]["area_ref"]
        r = self.call_e("/api/preview/generate", {"area_ref": a, "spacing_m": 20}, 8)["data"]["route_ref"]
        p_new = self.call_e("/api/preview/verify", {"route_ref": r, "reserve_req_pct": 25}, 8)["data"]
        self.assertNotEqual(p_new["preview_ref"], p_old["preview_ref"])  # 目前世代重驗 → 新 ID
        self.assertEqual(p_new["preview_version"], p_old["preview_version"])   # 內容雜湊相同（AC-9 可重算）
        self.call_e("/api/preview/apply_check", {"preview_ref": p_new["preview_ref"], "draft_id": "d1", "draft_rev": 1,
                                                 "target_slot_id": "home",
                                                 "target_generation": self.coord.word.current().root_gen}, 8)


class RF08ManifestGate(unittest.TestCase):
    """RF-08：manifest 雜湊、gate_id、依賴、來源或配置任一不符 → 不執行任何測試、結果 NOT_RELEASED、無放行副作用。"""

    def _manifest(self, tmp, **over):
        from . import g1_runner as G
        src_rel = os.path.relpath(os.path.join(tmp, "src.txt"), G.BASE).replace(os.sep, "/")
        with open(os.path.join(tmp, "src.txt"), "wb") as f:
            f.write(b"abc")
        man = {"schema_version": "GateManifest/1", "gate_id": "ADR-0002:G1",
               "scope": {"platform": "desktop-windows-pc", "backend": "python-reference", "feature_ids": [],
                         "trial_ids": ["gcs_demo.test_g0g"]},
               "sources": [{"role": "doc", "relative_path": src_rel, "sha256": G.sha(b"abc"), "bytes": 3}],
               "dependencies": [{"gate_id": "ADR-0002:G0", "result_sha256": "0" * 64}],
               "stop_profile_ref": {"id": "x", "version": "v1", "sha256": "0" * 64},
               "evidence_requirements": [], "permitted_actions": [], "authoritative_decision_refs": []}
        man.update(over)
        b = G.canonical(man)
        p = os.path.join(tmp, "m.json")
        with open(p, "wb") as f:
            f.write(b)
        return p, G.sha(b)

    def test_tampered_or_wrong_gate_not_released_and_no_tests_run(self):
        from . import g1_runner as G
        tmp = tempfile.mkdtemp(prefix="rf08_", dir=os.path.dirname(os.path.abspath(__file__)))
        try:
            p, h = self._manifest(tmp)
            ok, reasons, _ = G.verify(p, "f" * 64)
            self.assertFalse(ok)
            self.assertIn("manifest_hash_mismatch", reasons)
            self.assertIn("dependency_unverified:ADR-0002:G0", reasons)       # 依賴結果不可核證
            self.assertIn("code_inventory_missing", reasons)
            self.assertIn("policy_profile_missing", reasons)
            p2, h2 = self._manifest(tmp, gate_id="ADR-0002:G2a")
            self.assertIn("gate_id_mismatch:ADR-0002:G2a", G.verify(p2, h2)[1])
            p3, h3 = self._manifest(tmp, scope={"platform": "genio-520", "backend": "x", "feature_ids": [],
                                                "trial_ids": []})
            self.assertIn("scope_platform_not_desktop", G.verify(p3, h3)[1])
            with open(os.path.join(tmp, "src.txt"), "wb") as f:
                f.write(b"abd")                                        # 來源被改
            self.assertTrue(any(r.startswith("source_hash_mismatch") for r in G.verify(p, h)[1]))
            out = os.path.join(tmp, "run")
            self.assertEqual(G.main(["--manifest", p, "--sha256", h, "--out", out]), 2)
            info = __import__("json").load(open(os.path.join(out, "RUN_INFO.json"), encoding="utf-8"))
            self.assertEqual(info["result"], "NOT_RELEASED")
            self.assertEqual(sorted(os.listdir(out)), ["RUN_INFO.json"])   # 沒有跑任何測試
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
