import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gcs_demo import llm
from gcs_demo.domain_profile import load_domains, resolve_domain
from gcs_demo.recognition import registry as R
from gcs_demo.recognition.switcher import Switcher

FRAME = {"frame_id": "f1", "objects": [
    {"class": "crop_disease", "bbox": [0.1, 0.1, 0.1, 0.1]},
    {"class": "insulator_defect", "bbox": [0.5, 0.2, 0.1, 0.1]},
    {"class": "person", "bbox": [0.7, 0.7, 0.05, 0.1]},
    {"class": "car", "bbox": [0.3, 0.6, 0.1, 0.05]}]}


class Fake(llm.LLMBackend):
    name = "fake"

    def __init__(self, data):
        super().__init__("http://x", "fake")
        self.data = data

    def available(self):
        return True

    def complete_json(self, system, user, schema, timeout_s=None):
        return {"ok": True, "data": self.data, "raw": "", "latency_s": 0.0, "error": None}


class DomainTest(unittest.TestCase):
    def setUp(self):
        self.d = load_domains()

    def test_three_domains_share_ui_template_field(self):
        self.assertEqual(set(self.d), {"agriculture", "inspection", "multi_uav"})
        for v in self.d.values():
            self.assertTrue(v["ui_template"])

    def test_resolve(self):
        self.assertEqual(resolve_domain("設定任務：巡檢電線", self.d)["domain_id"], "inspection")
        self.assertEqual(resolve_domain("去果園看病蟲害", self.d)["domain_id"], "agriculture")
        self.assertEqual(resolve_domain("三架編隊搜索", self.d)["domain_id"], "multi_uav")
        self.assertEqual(resolve_domain("起飛", self.d)["decision"], "CLARIFY")

    def test_tie_clarifies(self):
        r = resolve_domain("作物電線", self.d)  # 2 字對 2 字
        self.assertEqual(r["decision"], "CLARIFY")
        self.assertEqual({o["id"] for o in r["options"]}, {"agriculture", "inspection"})

    def test_domain_name_wins(self):
        self.assertEqual(resolve_domain("農業場域，順便看電線", self.d)["domain_id"], "agriculture")


class SwitchTest(unittest.TestCase):
    def test_registry_marks_missing_and_stub(self):
        rows = {r["id"]: r for r in Switcher().rows()}
        self.assertTrue(rows["stub_agri_v0"]["installed"])
        self.assertFalse(rows["onnx_general_missing"]["installed"])

    def test_inspection_picks_full_model_and_rejects_lite(self):
        s = Switcher()
        p = s.propose("巡檢電塔絕緣子")
        self.assertEqual(p["model_id"], "stub_inspect_v0")
        rej = {r["id"]: r["reasons"] for r in p["evaluation"]["rejected"]}
        self.assertTrue(any("電線異物" in x for x in rej["stub_inspect_lite_v0"]))

    def test_agri_latency_filter(self):
        p = Switcher().propose(domain_id="agriculture")
        self.assertEqual(p["model_id"], "stub_agri_v0")
        rej = {r["id"]: r["reasons"] for r in p["evaluation"]["rejected"]}
        self.assertTrue(any("延遲" in x for x in rej["stub_agri_heavy_v0"]))

    def test_multi_uses_general_with_alias(self):
        s = Switcher()
        s.apply(s.propose("多機協同搜索")["proposal_id"])
        self.assertEqual(s.model_id, "stub_general_v0")
        classes = {d["class"] for d in s.detect({**FRAME, "frame_id": "x"})} | {
            d["class"] for d in s.detect({**FRAME, "frame_id": "y"})}
        self.assertTrue(classes <= {"person", "vehicle"})

    def test_apply_undo_and_events(self):
        s = Switcher(clock=lambda: 0.0)
        s.apply(s.propose(domain_id="agriculture")["proposal_id"])
        s.apply(s.propose(domain_id="inspection")["proposal_id"])
        self.assertEqual(s.model_id, "stub_inspect_v0")
        self.assertTrue(s.undo()["ok"])
        self.assertEqual((s.domain_id, s.model_id), ("agriculture", "stub_agri_v0"))
        self.assertTrue(s.undo()["ok"])
        self.assertEqual((s.domain_id, s.model_id), (None, None))
        self.assertFalse(s.undo()["ok"])
        kinds = [e["kind"] for e in s.events]
        self.assertEqual(kinds.count("undo"), 2)
        json.dumps(s.events, ensure_ascii=False)

    def test_keep_when_already_suitable(self):
        s = Switcher()
        s.apply(s.propose(domain_id="agriculture")["proposal_id"])
        self.assertEqual(s.propose("農田噴灑")["status"], "KEEP")

    def test_detection_threshold_and_format(self):
        s = Switcher()
        s.apply(s.propose(domain_id="inspection")["proposal_id"])
        th = s.domains["inspection"]["recognition"]["conf_threshold"]
        for d in s.detect(FRAME):
            self.assertGreaterEqual(d["conf"], th)
            self.assertIn(d["class"], {"insulator_defect", "line_foreign_object", "bird_nest"})
            for k in ("frame_id", "domain", "model_id", "class_zh", "bbox", "track_id"):
                self.assertIn(k, d)

    def test_sha_mismatch_blocks_and_keeps_old_model(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            for p in R.MODEL_DIR.iterdir():
                shutil.copy(p, tmp / p.name)
            s = Switcher(model_dir=tmp)
            s.apply(s.propose(domain_id="agriculture")["proposal_id"])
            p = s.propose(domain_id="inspection")
            (tmp / "stub_inspect_v0.weights.json").write_text("tampered", encoding="utf-8")
            r = s.apply(p["proposal_id"])
            self.assertFalse(r["ok"])
            self.assertEqual(s.model_id, "stub_agri_v0")
            p2 = s.propose(domain_id="inspection")
            self.assertEqual(p2["status"], "HOLD")
        finally:
            shutil.rmtree(tmp)

    def test_llm_invalid_falls_back_and_valid_used(self):
        s = Switcher(backend=Fake({"decision": "SELECT", "choice_id": "M9", "reason_zh": "x", "evidence_ids": []}))
        p = s.propose(domain_id="inspection")
        self.assertEqual((p["model_id"], p["source"]), ("stub_inspect_v0", "rule"))
        s2 = Switcher(backend=Fake({"decision": "SELECT", "choice_id": "M1", "reason_zh": "ok", "evidence_ids": ["E1"]}))
        p2 = s2.propose(domain_id="inspection")
        self.assertEqual(p2["source"], "llm")

    def test_judge_under_two_seconds(self):
        p = Switcher().propose("巡檢電線")
        self.assertLess(p["judge_ms"], 2000)


if __name__ == "__main__":
    unittest.main()
