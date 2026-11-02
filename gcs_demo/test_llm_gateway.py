"""共用 LLM 閘道的離線測試：用本機假 Ollama，不呼叫真模型。

python -m unittest gcs_demo.test_llm_gateway
"""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import llm
from . import llm_gateway as G


class FakeOllama:
    """記錄收到的請求；回固定 JSON；可設定每次延遲。"""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.seen = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.seen.append(body)
                time.sleep(fake.delay)
                content = json.dumps({"decision": "SELECT", "choice_id": "C1",
                                      "reason_zh": "測試", "evidence_ids": []})
                b = json.dumps({"message": {"role": "assistant", "content": content},
                                "eval_count": 7}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


def start_gateway(upstream, log_path, budgets=None):
    gw = G.Gateway(upstream, log_path, budgets)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), G.make_handler(gw))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return gw, srv, f"http://127.0.0.1:{srv.server_address[1]}"


def read_log(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def test_llm_py_through_gateway_with_feature_path(self):
        fake = FakeOllama()
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "gemma4:e2b"), self.log)
        try:
            b = llm.OpenAICompatBackend(url + "/f/mission/v1", "gemma4:e2b")
            res = llm.pick_candidate(b, "測試", [{"id": "C1"}, {"id": "C2"}], [], "C2")
            self.assertEqual(res["source"], "llm")
            self.assertEqual(res["choice_id"], "C1")
            sent = fake.seen[0]
            self.assertIs(sent["think"], False)
            self.assertEqual(sent["format"], "json")
            self.assertEqual(sent["options"]["temperature"], 0)
            rec = read_log(self.log)[0]
            self.assertEqual(rec["feature"], "mission")
            self.assertTrue(rec["ok"])
            self.assertIn("C1", rec["content"])
        finally:
            srv.shutdown(); fake.close()

    def test_json_schema_passed_as_ollama_format(self):
        fake = FakeOllama()
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log)
        try:
            schema = {"type": "object", "properties": {"choice_id": {"enum": ["A"]}}}
            st, body = gw.submit("ui", {"messages": [], "response_format": {
                "type": "json_schema", "json_schema": {"name": "x", "schema": schema}}})
            self.assertEqual(st, 200)
            self.assertEqual(fake.seen[0]["format"], schema)
        finally:
            srv.shutdown(); fake.close()

    def test_priority_ui_before_alerts_before_report(self):
        fake = FakeOllama(delay=0.3)
        gw = G.Gateway(G.make_upstream("ollama", fake.url, "m"), self.log)
        order = []

        def call(feat):
            gw.submit(feat, {"messages": [{"role": "user", "content": feat}]})
            order.append(feat)

        try:
            first = threading.Thread(target=call, args=("recognition",))
            first.start()
            time.sleep(0.1)  # recognition 已進模型；以下三個排隊
            ts = [threading.Thread(target=call, args=(f,)) for f in ("report", "alerts", "ui")]
            for t in ts:
                t.start(); time.sleep(0.02)
            for t in [first] + ts:
                t.join()
            served = [s["messages"][0]["content"] for s in fake.seen]
            self.assertEqual(served, ["recognition", "ui", "alerts", "report"])
        finally:
            fake.close()

    def test_expired_in_queue_not_sent(self):
        fake = FakeOllama(delay=1.2)
        gw = G.Gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 1.0, "report": 5})
        try:
            t = threading.Thread(target=gw.submit, args=("report", {"messages": []}))
            t.start(); time.sleep(0.1)
            st, body = gw.submit("ui", {"messages": []})
            t.join()
            self.assertEqual(st, 504)
            self.assertEqual(len(fake.seen), 1)
            self.assertEqual(read_log(self.log)[-1]["error"], "expired in queue")
        finally:
            fake.close()

    def test_upstream_down_falls_back_to_rule(self):
        gw, srv, url = start_gateway(G.make_upstream("ollama", "http://127.0.0.1:9", "m"), self.log)
        try:
            b = llm.OpenAICompatBackend(url + "/f/alerts/v1", "m")
            res = llm.pick_candidate(b, "t", [{"id": "C1"}], [], "C1")
            self.assertEqual(res["source"], "rule")
            rec = read_log(self.log)[0]
            self.assertFalse(rec["ok"])
            self.assertEqual(rec["feature"], "alerts")
        finally:
            srv.shutdown()

    def test_ollama_native_path_and_health(self):
        fake = FakeOllama()
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log)
        try:
            b = llm.OllamaBackend(url + "/f/report", "m")
            res = b.complete_json("s", "u", {"required": {"decision": "str"}})
            self.assertTrue(res["ok"], res)
            import urllib.request
            h = json.loads(urllib.request.urlopen(url + "/health").read())
            self.assertEqual(h["priority"]["ui"], 0)
            self.assertEqual(read_log(self.log)[0]["feature"], "report")
        finally:
            srv.shutdown(); fake.close()

    def test_feature_of(self):
        self.assertEqual(G.feature_of("/f/UI/v1/chat/completions", {}), ("ui", "/v1/chat/completions"))
        self.assertEqual(G.feature_of("/v1/chat/completions", {"X-GCS-Feature": "alerts"}),
                         ("alerts", "/v1/chat/completions"))
        self.assertEqual(G.feature_of("/v1/models", {}), ("unknown", "/v1/models"))


if __name__ == "__main__":
    unittest.main()
