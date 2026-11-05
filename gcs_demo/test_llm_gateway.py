"""共用 LLM 閘道的離線測試：用本機假 Ollama，不呼叫真模型。

python -m unittest gcs_demo.test_llm_gateway
"""
import json
import os
import tempfile
import threading
import time
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import llm
from . import llm_gateway as G
from . import harness_manifest as HM
from . import harness_report as HR


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
            self.assertEqual(rec["format_kind"], "json")
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
            self.assertEqual(read_log(self.log)[0]["format_kind"], "json_schema")
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


class HarnessHTTPTest(unittest.TestCase):
    def test_headers_and_schema_on_both_protocols(self):
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp:
            log = str(Path(tmp) / "calls.jsonl")
            fake = FakeOllama()
            _, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), log)
            schema = {"type": "object", "properties": {"id": {"enum": ["甲"]}}}
            try:
                for protocol in ("openai", "ollama"):
                    for label in (None, "ui@harness-v1#12345678", ""):
                        req = {"messages": []}
                        endpoint = "/f/ui/v1/chat/completions"
                        if protocol == "ollama":
                            endpoint = "/f/ui/api/chat"
                            req["format"] = schema
                        elif label is not None:
                            req["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
                        headers = {"Content-Type": "application/json"}
                        if label is not None:
                            headers["X-GCS-Harness"] = label
                        request = urllib.request.Request(url + endpoint,
                                    data=json.dumps(req).encode(), headers=headers)
                        with G._NO_PROXY.open(request) as response:
                            self.assertEqual(response.status, 200)
                        record = read_log(log)[-1]
                        self.assertEqual(record["harness"], "unversioned" if label is None else label)
                        expected = hashlib.sha256(json.dumps(schema, ensure_ascii=False,
                                                  sort_keys=True).encode()).hexdigest()[:16]
                        self.assertEqual(record["schema_hash"], expected if protocol == "ollama"
                                         or label is not None else None)
                        self.assertNotIn("harness", fake.seen[-1])
                request = urllib.request.Request(url, method="OPTIONS")
                with G._NO_PROXY.open(request) as response:
                    self.assertIn("X-GCS-Harness", response.headers["Access-Control-Allow-Headers"])
            finally:
                srv.shutdown()
                srv.server_close()
                fake.close()
                fake.srv.server_close()

    def test_expired_and_failed_calls_keep_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = str(Path(tmp) / "calls.jsonl")
            gw = G.Gateway(G.Upstream("", "m"), log)
            for budget, label, expected in ((0, "expired-label", 504), (2, "failure-label", 502)):
                job = G._Job("alerts", {"messages": []}, budget, harness=label)
                gw._serve(job)
                self.assertEqual(job.result[0], expected)
                self.assertEqual(read_log(log)[-1]["harness"], label)
                self.assertIsNone(read_log(log)[-1]["schema_hash"])


class HarnessManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.component = self.root / "component.txt"
        self.component.write_bytes(b"alpha\nbeta\n")
        self.manifest_path = self.root / "gcs_demo/harness/ui/manifest.json"
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest = {"feature": "ui", "version": "test-v1", "components": {
            name: {"path": None, "sha256": None, "note": "not available in fixture"}
            for name in HM.COMPONENTS}}
        self.manifest["components"]["guard"] = {"path": "component.txt",
            "sha256": hashlib.sha256(self.component.read_bytes()).hexdigest()}
        self.write_manifest()
        patcher = patch.object(HM, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_manifest(self):
        self.manifest["harness_sha256"] = HM.digest(self.manifest)
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")

    def test_header_and_deterministic_canonical_hash(self):
        digest = HM.digest(self.manifest)
        reordered = dict(reversed(list(self.manifest.items())))
        self.assertEqual(HM.digest(reordered), digest)
        payload = {k: v for k, v in self.manifest.items() if k != "harness_sha256"}
        expected = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual(HM.header("ui"), f"ui@test-v1#{expected[:8]}")

    def test_manifest_tamper_fails(self):
        self.manifest["version"] = "changed"
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "harness_sha256"):
            HM.load("ui")

    def test_component_one_byte_tamper_fails(self):
        self.component.write_bytes(b"Alpha\nbeta\n")
        with self.assertRaisesRegex(ValueError, "component sha256"):
            HM.load("ui")

    def test_crlf_and_lf_hashes_differ(self):
        self.component.write_bytes(b"alpha\r\nbeta\r\n")
        self.assertNotEqual(hashlib.sha256(self.component.read_bytes()).hexdigest(),
                            self.manifest["components"]["guard"]["sha256"])
        with self.assertRaisesRegex(ValueError, "component sha256"):
            HM.load("ui")
        self.manifest["components"]["guard"]["sha256"] = hashlib.sha256(self.component.read_bytes()).hexdigest()
        self.write_manifest()
        self.assertEqual(HM.load("ui"), self.manifest)

    def test_missing_component_and_invalid_feature_fail(self):
        self.component.unlink()
        with self.assertRaises(FileNotFoundError):
            HM.load("ui")
        with self.assertRaises(ValueError):
            HM.load("../ui")

    def test_repo_manifests_load(self):
        with patch.object(HM, "ROOT", Path(__file__).resolve().parent.parent):
            for feature in HM.FEATURES:
                self.assertEqual(HM.load(feature)["feature"], feature)


class HarnessReportTest(unittest.TestCase):
    def test_grouping_rates_timeouts_and_percentiles(self):
        records = [{"feature": "ui", "harness": "v1", "ok": True, "latency_s": n}
                   for n in range(1, 21)]
        records += [{"feature": "ui", "ok": False, "error": "expired in queue", "latency_s": 0},
                    {"feature": "ui", "harness": "v2", "ok": False, "error": "TimeoutError: timed out"},
                    {"feature": "alerts", "harness": "v1", "ok": False,
                     "error": "connection refused", "latency_s": float("nan")}]
        groups = {(g["feature"], g["harness"]): g for g in HR.summarize(records)["groups"]}
        self.assertEqual(len(groups), 4)
        group = groups[("ui", "v1")]
        self.assertEqual((group["count"], group["ok_rate"], group["latency_median_s"],
                          group["latency_p95_s"]), (20, 1.0, 10.5, 19))
        self.assertEqual(groups[("ui", "unversioned")]["timeout_count"], 1)
        self.assertEqual(groups[("ui", "v2")]["timeout_count"], 1)
        self.assertIsNone(groups[("alerts", "v1")]["latency_p95_s"])
        mixed = HR.summarize([{"ok": True, "latency_s": 1}, {"ok": False, "latency_s": 3}])["groups"][0]
        self.assertEqual(mixed["ok_rate"], .5)

    def test_report_preserves_input_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "calls.jsonl", Path(tmp) / "summary.json"
            original = b'{"feature":"ui","ok":true,"latency_s":1}\n'
            source.write_bytes(original)
            HR.report(source, output)
            self.assertEqual(source.read_bytes(), original)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                HR.report(source, output)
            self.assertEqual(output.read_bytes(), before)
            with self.assertRaises(ValueError):
                HR.report(source, source)


if __name__ == "__main__":
    unittest.main()
