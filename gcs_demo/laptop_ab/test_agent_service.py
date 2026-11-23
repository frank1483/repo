"""AiAgent 服務的假模型測試（不是 live）。需要手冊索引與 ID 索引：環境變數 GCS_AB_TEST_BASE 指到含 adr0002_rag_v1 的資料夾，
沒有就跳過。用法：GCS_AB_TEST_BASE=~/thesis_ab python -m unittest gcs_demo.laptop_ab.test_agent_service"""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from . import agent_service as S

BASE = os.path.expanduser(os.environ.get("GCS_AB_TEST_BASE", ""))
HAVE = bool(BASE) and os.path.isdir(os.path.join(BASE, "adr0002_rag_v1", "id_index_v1"))


@unittest.skipUnless(HAVE, "需要 GCS_AB_TEST_BASE（含 adr0002_rag_v1）")
class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.svcs = {p: S.AgentService(p, os.path.join(cls.tmp, p), fake=True, base=BASE) for p in ("A", "B")}

    def ask(self, plan, text):
        return self.svcs[plan].request(text)

    def test_route_plan_both(self):
        for p in ("A", "B"):
            v = self.ask(p, "規劃北側巡檢區域的覆蓋航線")
            self.assertTrue(v["ok"], v["error"])
            routes = [x for x in v["proposals"] if x["ui"] and x["ui"]["kind"] == "route"]
            self.assertTrue(routes and routes[0]["supported"] and len(routes[0]["ui"]["points"]) >= 2, p)
            self.assertIn(v["reply_source"], ("polished",) + tuple(v["reply_source"] for _ in [0] if str(v["reply_source"]).startswith("fallback:")))
            self.assertEqual(v["polish_calls"], 1, p)            # v3.12：每句潤飾 1 次（假模型不回 JSON → 退回 format）
            self.assertIsNotNone(v["reply_template"])

    def test_layout_candidate_shape(self):
        for p in ("A", "B"):
            v = self.ask(p, "把姿態儀放大")
            lays = [x["ui"] for x in v["proposals"] if x["ui"] and x["ui"]["kind"] == "layout"]
            for u in lays:                                       # UI agent 候選格式
                self.assertTrue(u["id"].startswith("AB_LAY_"))
                self.assertIn(u["op"], ("scale", "reset", "move", "show", "hide"))
                if u["op"] == "scale":
                    self.assertIn(u["factor"], (0.8, 1.25))
                if u["op"] == "move":
                    self.assertIn(u["region"], ("TL", "TR", "BL", "BR", "C"))

    def test_flight_has_no_actionable(self):
        for p in ("A", "B"):
            v = self.ask(p, "現在起飛")
            self.assertFalse([x for x in v["proposals"] if x["supported"] and x["ui"] and x["ui"]["kind"] not in
                              ("route", "layout", "text_scale", "theme", "model")])

    def test_mark_and_http(self):
        svc = self.svcs["A"]
        v = svc.request("規劃北側巡檢區域的覆蓋航線")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        httpd.svc = svc
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        try:
            port = httpd.server_address[1]
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/api/agent/health")
            h = json.loads(c.getresponse().read())
            self.assertEqual(h["plan"], "A")
            c.request("POST", "/api/agent/mark", json.dumps({"task_id": v["task_id"], "index": 0, "state": "APPLIED"}),
                      {"Content-Type": "application/json"})
            r = c.getresponse()
            self.assertEqual(r.status, 200, r.read())
            r.read()
            c.request("POST", "/api/agent/mark", json.dumps({"task_id": v["task_id"], "index": 0, "state": "WRITTEN"}))
            r = c.getresponse()
            self.assertEqual(r.status, 400)
            r.read()
            c2 = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c2.putrequest("GET", "/api/agent/health", skip_host=True)
            c2.putheader("Host", "evil.example")
            c2.endheaders()
            self.assertEqual(c2.getresponse().status, 403)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
