"""ADR-0002 M3：迴圈接真工具、告警暫停、取消、閘道優先序（M3 演算法說明 v1 §6）。規則版＋假模型。
首次執行由 Claude 負責，結果與失敗原樣保留。"""
import os
import shutil
import tempfile
import unittest

from . import commit_layer as cl
from . import llm_gateway as G
from .agent_controller import Controller
from .agent_tools import AgentTools, match_areas, load_areas, parse_constraints
from .planner import _to_ll
from .preview_api import PreviewService, SessionFeeder
from .test_agent_controller import FakeModel, allowed_of
from .test_preview_api import FakeSession

O = (24.0, 121.0)


def ll(x, y):
    a, b = _to_ll(O, (x, y))
    return {"lat": a, "lon": b}


class Parsing(unittest.TestCase):
    def test_reserve_parsing(self):
        self.assertEqual(parse_constraints("北側巡檢，留 25%，放到首頁"), {"reserve_req_pct": 25.0})
        self.assertEqual(parse_constraints("保留30％"), {"reserve_req_pct": 30.0})
        self.assertEqual(parse_constraints("北側巡檢"), {})

    def test_area_matching(self):
        A = load_areas()
        self.assertEqual([a["id"] for a in match_areas("北側巡檢", A)], ["AREA-N1"])
        self.assertEqual([a["id"] for a in match_areas("北側二巡檢", A)], ["AREA-N2"])
        self.assertEqual(len(match_areas("北側和南側巡檢", A)), 2)
        self.assertEqual(match_areas("東邊巡檢", A), [])


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m3_")
        root = os.path.join(self.tmp, "store")
        cl.init_store(root)
        self.coord, _ = cl.boot(root)
        self.sess = FakeSession()
        self.feeder = SessionFeeder(self.sess, self.coord)
        self.feeder.poll()
        self.svc = PreviewService(self.coord, self.feeder, os.path.join(self.tmp, "ev", "p.jsonl"), boot_epoch=1)
        self.sid = "s-test"
        self.svc.sessions[self.sid] = {"principal": "ui", "last_epoch": 0}
        self.tools = AgentTools(self.svc, "ui", self.sid)
        self.alert = [False]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctl(self, kinds=("plan", "ui"), raw=None):
        return Controller(self.tools, FakeModel(list(kinds), raw=raw), alert_active=lambda: self.alert[0])

    def test_end_to_end_to_dialog_then_user_confirm_writes(self):
        c = self.ctl()
        r = c.request("北側巡檢，留 25%，放到首頁")
        self.assertEqual(r["status"], "DONE", r)
        self.assertEqual(len(self.tools.dialogs), 1)
        ch = self.tools.dialogs[0]
        self.assertEqual(ch["decision"], "CONFIRM")
        rec = next(iter(self.svc.previews.values()))
        self.assertEqual(rec["inputs"]["reserve_req_pct"], 25.0)          # 明講值由程式帶入
        self.assertIsNone(self.coord.word.current().route("home"))         # 開視窗不等於寫入
        tok = self.svc.presented("ui", self.sid, {"shown_hash": ch["shown_hash"], "apply_intent_id": ch["apply_intent_id"],
                                                  "target_slot_id": "home", "window_id": "w", "frame_id": "f"})
        out = self.svc.commit("ui", self.sid, {"target_slot_id": "home", "nonce": "n1",
                                               "apply_intent_id": ch["apply_intent_id"], "shown_hash": ch["shown_hash"],
                                               "confirm_token": tok["confirm_token"]})
        self.assertEqual(out["transaction"]["action"], "WRITE")
        self.assertIsNotNone(self.coord.word.current().route("home"))

    def test_two_named_areas_ask_then_continue(self):
        c = self.ctl()
        r = c.request("北側和南側巡檢，放到首頁")
        self.assertEqual(r["questions"][0]["field"], "area_choice")
        r2 = c.resume(r["task_id"], [{"field": "area_choice", "value": "AREA-S1"}])
        self.assertEqual(r2["status"], "DONE", r2)

    def test_unknown_area_then_drawn_boundary(self):
        c = self.ctl()
        r = c.request("東邊巡檢，放到首頁")
        self.assertEqual(r["questions"][0]["field"], "boundary")
        d = self.svc.area_submit("ui", self.sid, {"polygon": [ll(0, 0), ll(100, 0), ll(100, 100), ll(0, 100)]})
        r2 = c.resume(r["task_id"], [{"field": "boundary", "value": d["area_ref"]}])
        self.assertEqual(r2["status"], "DONE", r2)

    def test_alert_pauses_between_steps_and_resumes(self):
        self.alert[0] = True
        c = self.ctl()
        r = c.request("北側巡檢，放到首頁")
        self.assertEqual(r["status"], "PARKED")
        self.assertIn("告警中，迴圈停在步與步之間", r["notes"])
        self.assertEqual(len(r["steps"]), 0)
        self.alert[0] = False
        r2 = c.continue_task(r["task_id"])
        self.assertEqual(r2["status"], "DONE", r2)

    def test_late_reply_after_cancel_is_ignored(self):
        holder = {}

        def raw(call):
            c = holder["c"]
            c.cancel(sorted(c.tasks)[-1])                      # 使用者在模型回覆前按取消
            al = allowed_of(call)
            return '{"value":"%s"}' % [a for a in al if a not in ("FINISH", "HOLD")][0]
        c = self.ctl(raw=raw)
        holder["c"] = c
        r = c.request("北側巡檢")
        self.assertEqual(r["status"], "CANCELLED")
        self.assertTrue(any("只記錄、不採用" in n for n in r["notes"]))
        self.assertEqual(self.svc.routes, {})                    # 沒有生成航線


class GatewayPriority(unittest.TestCase):
    def test_priority_order_i06(self):
        P = G.PRIORITY
        self.assertEqual(P["ui"], P["mission"])
        self.assertLess(P["ui"], P["alerts"])
        self.assertEqual(P["alerts"], P["qa"])
        for k in ("agent_dir", "agent_step", "agent_resume"):
            self.assertEqual(P[k], P["qa"])
        self.assertLess(P["qa"], P["genui_bg"])
        self.assertLess(P["genui_bg"], P["report"])
        self.assertEqual(P["report"], P["recognition"])

    def test_unknown_feature_rejected(self):
        tmp = tempfile.mkdtemp(prefix="gw_")
        try:
            gw = G.Gateway(G.Upstream("", "m"), os.path.join(tmp, "log.jsonl"))
            code, body = gw.submit("unknown", {"messages": []})
            self.assertEqual(code, 400)
            self.assertEqual(body["error"]["type"], "feature")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
