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


def read_events(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [r for r in (json.loads(x) for x in f if x.strip()) if "event" in r]


def wait_for(fn, timeout=5.0):
    t_end = time.time() + timeout
    while time.time() < t_end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


def _settle(path, timeout=3.0, quiet=0.15):
    """v0.4.2 起回應不等紀錄落檔：讀紀錄前等檔案出現且 quiet 秒內沒有再變動。"""
    t_end = time.time() + timeout
    last, t_last = None, time.time()
    while time.time() < t_end:
        size = os.path.getsize(path) if os.path.exists(path) else -1
        if size != last:
            last, t_last = size, time.time()
        elif size > 0 and time.time() - t_last >= quiet:
            return
        time.sleep(0.02)


def read_log(path):
    _settle(path)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    return [r for r in rows if "event" not in r]  # http_write 事件另讀，見 read_events


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
            # v0.4：ui 在 1.0 秒就收到 504（不再等 worker）；worker 之後才把它記成過期、不送模型
            ui = wait_for(lambda: [r for r in read_log(self.log) if r["feature"] == "ui"])
            self.assertEqual(len(fake.seen), 1)
            self.assertEqual(ui[0]["error"], "expired in queue")
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


class SlowOllama:
    """假 Ollama：收到請求後慢慢「推論」，每 20 ms 檢查連線是否被對方關閉，記錄中斷時間。"""

    def __init__(self, delay):
        import select as _select
        import socket as _socket
        self.delay = delay
        self.events = []  # (kind, t_monotonic)
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                fake.events.append(("start", time.monotonic()))
                t_end = time.monotonic() + fake.delay
                while time.monotonic() < t_end:
                    r, _, _ = _select.select([self.connection], [], [], 0.02)
                    if r:
                        try:
                            gone = self.connection.recv(1, _socket.MSG_PEEK) == b""
                        except OSError:
                            gone = True
                        if gone:
                            fake.events.append(("aborted", time.monotonic()))
                            return
                fake.events.append(("finished", time.monotonic()))
                content = json.dumps({"decision": "SELECT", "choice_id": "C1",
                                      "reason_zh": "慢", "evidence_ids": []})
                b = json.dumps({"message": {"role": "assistant", "content": content}}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def kinds(self):
        return [k for k, _ in self.events]

    def close(self):
        self.srv.shutdown()


def post(url, body, headers=None, timeout=30):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with G._NO_PROXY.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class DeadlineContractTest(unittest.TestCase):
    """llm_contract v0.4 期限／取消契約：不放寬 ui 20 s，也不放寬呼叫端給的期限。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def test_http_reply_at_budget_not_budget_plus_5_and_upstream_aborted(self):
        fake = SlowOllama(delay=4.0)
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 1.0})
        try:
            t0 = time.monotonic()
            st, body = post(url + "/f/ui/v1/chat/completions", {"messages": []})
            took = time.monotonic() - t0
            self.assertEqual(st, 504)
            self.assertEqual(body["error"]["type"], "deadline")
            self.assertLess(took, 1.4)   # 舊版會等到 budget+5 = 6 秒
            ev = wait_for(lambda: "aborted" in fake.kinds() and fake.events)
            self.assertIn("aborted", fake.kinds())
            self.assertNotIn("finished", fake.kinds())
            aborted_at = dict(fake.events)["aborted"]
            self.assertLess(aborted_at - t0, 1.5)  # 上游推論在期限附近被中斷
            rec = wait_for(lambda: read_log(self.log))[0]
            self.assertFalse(rec["ok"])
            self.assertTrue(rec["error"].startswith("deadline"))
        finally:
            srv.shutdown(); fake.close()

    def test_client_deadline_header_only_shortens(self):
        fake = SlowOllama(delay=4.0)
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 2.0})
        try:
            t0 = time.monotonic()
            st, _ = post(url + "/f/ui/v1/chat/completions", {"messages": []},
                         {"X-GCS-Deadline-Ms": "600"})
            self.assertEqual(st, 504)
            self.assertLess(time.monotonic() - t0, 1.0)  # 0.6 s，而不是預算 2 s
            t1 = time.monotonic()
            st, _ = post(url + "/f/ui/v1/chat/completions", {"messages": []},
                         {"X-GCS-Deadline-Ms": "60000"})
            self.assertEqual(st, 504)
            self.assertLess(time.monotonic() - t1, 2.5)  # 60 s 被壓回 ui 預算 2 s
        finally:
            srv.shutdown(); fake.close()

    def test_invalid_deadline_header_ignored(self):
        fake = FakeOllama()
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log)
        try:
            for bad in ("abc", "-5", "0", "nan"):
                st, _ = post(url + "/f/ui/v1/chat/completions", {"messages": []},
                             {"X-GCS-Deadline-Ms": bad})
                self.assertEqual(st, 200, bad)
        finally:
            srv.shutdown(); fake.close()

    def test_queued_job_cancelled_at_deadline_never_sent(self):
        fake = SlowOllama(delay=1.5)
        gw = G.Gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 0.8, "report": 5})
        try:
            t = threading.Thread(target=gw.submit, args=("report", {"messages": []}))
            t.start(); time.sleep(0.1)
            t0 = time.monotonic()
            st, body = gw.submit("ui", {"messages": []})
            self.assertEqual(st, 504)
            self.assertLess(time.monotonic() - t0, 1.0)
            t.join()
            ui = wait_for(lambda: [r for r in read_log(self.log) if r["feature"] == "ui"])
            self.assertEqual(fake.kinds().count("start"), 1)  # 只有 report 送進模型
            self.assertEqual(ui[0]["error"], "expired in queue")
            self.assertFalse(ui[0]["claimed"])
        finally:
            fake.close()

    def test_client_disconnect_cancels_upstream(self):
        import socket as _socket
        fake = SlowOllama(delay=4.0)
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 20})
        try:
            host, port = srv.server_address
            body = json.dumps({"messages": []}).encode()
            c = _socket.create_connection((host, port))
            c.sendall(b"POST /f/ui/v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
                      b"Content-Type: application/json\r\nContent-Length: "
                      + str(len(body)).encode() + b"\r\n\r\n" + body)
            wait_for(lambda: "start" in fake.kinds())
            t0 = time.monotonic()
            c.close()  # 呼叫端放棄（例如 UI 使用者按取消）
            wait_for(lambda: "aborted" in fake.kinds())
            self.assertIn("aborted", fake.kinds())
            self.assertLess(time.monotonic() - t0, 1.5)
            rec = wait_for(lambda: read_log(self.log))[0]
            self.assertIn("client_gone", rec["error"])
        finally:
            srv.shutdown(); fake.close()

    def test_ui_budget_is_still_20s(self):
        self.assertEqual(G.DEFAULT_BUDGETS["ui"], 20.0)

    def test_success_before_deadline_delivered(self):
        fake = SlowOllama(delay=0.2)
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 2.0})
        try:
            st, body = post(url + "/f/ui/v1/chat/completions", {"messages": []},
                            {"X-GCS-Deadline-Ms": "1500"})
            self.assertEqual(st, 200)
            rec = read_log(self.log)[0]
            self.assertTrue(rec["ok"]); self.assertTrue(rec["claimed"])
            self.assertLessEqual(rec["deadline_s"], 1.5)
        finally:
            srv.shutdown(); fake.close()


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.t

    def advance(self, dt):
        with self.lock:
            self.t += dt


class ScriptedUpstream(G.Upstream):
    """不連網的上游：執行指定動作後回固定內容（測期限與認領的交錯）。"""
    name = "scripted"

    def __init__(self, action):
        super().__init__("", "m")
        self.action = action
        self.calls = 0

    def chat(self, req, timeout_s, cancel=None):
        self.calls += 1
        self.action()
        return '{"decision":"HOLD","choice_id":"","reason_zh":"x","evidence_ids":[]}', {}


class DeadlineRaceTest(unittest.TestCase):
    """v0.4.1：Codex 0417 的 P1 情境（認領與期限、取消與連線建立）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def test_result_after_deadline_is_not_claimed(self):
        clock = FakeClock()
        up = ScriptedUpstream(lambda: clock.advance(5.0))  # 推論「花了」5 秒，超過 2 秒期限
        gw = G.Gateway(up, self.log, {"ui": 2.0}, clock=clock)
        st, body = gw.submit("ui", {"messages": []})
        self.assertEqual(st, 504)
        self.assertEqual(body["error"]["type"], "deadline")
        rec = wait_for(lambda: read_log(self.log))[0]
        self.assertFalse(rec["claimed"])
        self.assertTrue(rec["late_discarded"])
        self.assertTrue(rec["ok"])  # 模型其實回了，只是太晚，不交付

    def test_result_just_before_deadline_is_claimed(self):
        clock = FakeClock()
        up = ScriptedUpstream(lambda: clock.advance(1.9))
        gw = G.Gateway(up, self.log, {"ui": 2.0}, clock=clock)
        st, _ = gw.submit("ui", {"messages": []})
        self.assertEqual(st, 200)
        self.assertTrue(wait_for(lambda: read_log(self.log))[0]["claimed"])

    def test_blocked_log_does_not_delay_reply_past_deadline(self):
        up = ScriptedUpstream(lambda: None)
        gw = G.Gateway(up, self.log, {"ui": 1.0})
        orig = gw._log
        gw._log = lambda rec: (time.sleep(3.0), orig(rec))
        t0 = time.monotonic()
        st, _ = gw.submit("ui", {"messages": []})
        took = time.monotonic() - t0
        self.assertEqual(st, 200)          # 期限前已完成 → 照常交付
        self.assertLess(took, 1.3)         # 不等 3 秒的紀錄、也不多等 1 秒

    def test_deadline_vs_completion_race_invariant(self):
        fake = SlowOllama(delay=0.0)
        gw = G.Gateway(G.make_upstream("ollama", fake.url, "m"), self.log, {"ui": 0.6})
        try:
            outcomes = []
            for i in range(30):
                fake.delay = 0.6 + (i % 7 - 3) * 0.03   # 0.51 ~ 0.69 秒，跨越期限
                jobs = []
                t0 = time.monotonic()
                st, _ = gw.submit("ui", {"messages": [{"role": "user", "content": str(i)}]},
                                  job_out=jobs)
                took = time.monotonic() - t0
                outcomes.append(st)
                self.assertLess(took, 0.6 + 0.35, i)
                rec = wait_for(lambda: [r for r in read_log(self.log)
                                        if r.get("job_id") == jobs[0].id])[0]
                self.assertEqual(st == 200, rec["claimed"] is True, (i, st, rec))
            self.assertIn(504, outcomes)
        finally:
            fake.close()

    def test_cancel_while_connecting_never_sends(self):
        fake = SlowOllama(delay=0.1)
        up = G.make_upstream("ollama", fake.url, "m")
        gate = threading.Event()
        up._after_connect_hook = lambda: gate.wait(5)
        gw = G.Gateway(up, self.log, {"ui": 0.8})
        try:
            res = {}
            t = threading.Thread(target=lambda: res.setdefault("r", gw.submit("ui", {"messages": []})))
            t.start()
            t.join(2.0)                      # 期限 0.8 秒先到 → 取消；連線還卡在屏障
            self.assertEqual(res["r"][0], 504)
            gate.set()                       # 放行：此時發現已取消 → 關閉、不送
            rec = wait_for(lambda: read_log(self.log))[0]
            time.sleep(0.2)
            self.assertNotIn("start", fake.kinds())
            self.assertIn("cancelled during connect", rec["error"])
            self.assertFalse(rec["sent_upstream"])
        finally:
            fake.close()

    def test_cancel_set_before_post_never_connects(self):
        fake = SlowOllama(delay=0.1)
        up = G.make_upstream("ollama", fake.url, "m")
        tok = G.CancelToken(); tok.set()
        with self.assertRaises(G.DeadlineExceeded):
            up.chat({"messages": []}, 5.0, tok)
        time.sleep(0.2)
        self.assertEqual(fake.kinds(), [])
        fake.close()

    def test_no_thread_growth_after_many_quick_calls(self):
        fake = FakeOllama()
        gw = G.Gateway(G.make_upstream("ollama", fake.url, "m"), self.log)
        try:
            gw.submit("ui", {"messages": []})
            base = threading.active_count()
            for _ in range(20):
                self.assertEqual(gw.submit("ui", {"messages": []})[0], 200)
            time.sleep(0.2)
            self.assertLessEqual(threading.active_count(), base + 2)
        finally:
            fake.close()

    def test_http_write_event_recorded(self):
        fake = FakeOllama()
        gw, srv, url = start_gateway(G.make_upstream("ollama", fake.url, "m"), self.log)
        try:
            st, _ = post(url + "/f/ui/v1/chat/completions", {"messages": []})
            self.assertEqual(st, 200)
            ev = wait_for(lambda: read_events(self.log))
            self.assertEqual(ev[0]["event"], "http_write")
            self.assertEqual(ev[0]["status"], 200)
            self.assertTrue(ev[0]["write_ok"])
            self.assertEqual(ev[0]["job_id"], read_log(self.log)[0]["job_id"])
        finally:
            srv.shutdown(); fake.close()


class DeadlineRace2Test(unittest.TestCase):
    """v0.4.2：Codex 0423 指定的兩個交錯。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def test_submit_returns_while_log_barrier_held_before_deadline(self):
        clock = FakeClock()            # 時間不前進：期限（20 s）絕不會到
        up = ScriptedUpstream(lambda: None)
        gw = G.Gateway(up, self.log, {"ui": 20.0}, clock=clock)
        barrier = threading.Event()
        orig = gw._log
        gw._log = lambda rec: (barrier.wait(10), orig(rec))
        res = {}
        t = threading.Thread(target=lambda: res.setdefault("r", gw.submit("ui", {"messages": []})))
        t.start()
        t.join(2.0)
        try:
            self.assertFalse(t.is_alive(), "submit 仍被紀錄屏障擋住")
            self.assertEqual(res["r"][0], 200)
            self.assertFalse(barrier.is_set())          # 紀錄還沒放行
            self.assertGreater(gw_job_remaining(clock), 0)
        finally:
            barrier.set()
            t.join(2.0)

    def test_cancel_wins_after_publish_zero_post(self):
        fake = SlowOllama(delay=0.1)
        up = G.make_upstream("ollama", fake.url, "m")
        published = threading.Event()
        gate = threading.Event()
        up._before_send_hook = lambda: (published.set(), gate.wait(5))
        tok = G.CancelToken()
        res = {}

        def run():
            try:
                up.chat({"messages": []}, 5.0, tok)
                res["r"] = "sent"
            except G.DeadlineExceeded as exc:
                res["r"] = str(exc)

        t = threading.Thread(target=run)
        t.start()
        try:
            self.assertTrue(published.wait(2))  # socket 已發布、尚未送出
            tok.set()                           # 取消先拿到鎖：shutdown 也在鎖內完成
            gate.set()
            t.join(3)
            self.assertIn("not sent", res["r"])
            time.sleep(0.3)
            self.assertNotIn("start", fake.kinds())     # 0 個 POST
        finally:
            gate.set(); fake.close()


class DeadlinePhaseTest(unittest.TestCase):
    """v0.4.3：Codex 0426 P2——回應已讀完後才取消，紀錄必須是「已送出」。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def test_cancel_after_read_before_last_check_is_sent(self):
        fake = FakeOllama()
        up = G.make_upstream("ollama", fake.url, "m")
        tok = G.CancelToken()
        up._after_read_hook = tok.set
        try:
            with self.assertRaises(G.DeadlineExceeded) as cm:
                up.chat({"messages": []}, 5.0, tok)
            self.assertTrue(cm.exception.sent)
            self.assertEqual(cm.exception.phase, "received")
            self.assertEqual(len(fake.seen), 1)
        finally:
            fake.close()

    def test_gateway_logs_sent_when_cancelled_after_read(self):
        fake = FakeOllama()
        up = G.make_upstream("ollama", fake.url, "m")
        gw = G.Gateway(up, self.log, {"ui": 5.0})
        jobs = []
        up._after_read_hook = lambda: jobs[0].abandon("client_gone")
        try:
            st, body = gw.submit("ui", {"messages": []}, job_out=jobs)
            self.assertEqual(st, 504)
            rec = wait_for(lambda: read_log(self.log))[0]
            self.assertTrue(rec["sent_upstream"])
            self.assertEqual(rec["upstream_phase"], "received")
            self.assertFalse(rec["claimed"])
            self.assertEqual(len(fake.seen), 1)
        finally:
            fake.close()

    def test_phase_before_send_is_not_sent(self):
        fake = SlowOllama(delay=0.1)
        up = G.make_upstream("ollama", fake.url, "m")
        tok = G.CancelToken()
        up._before_send_hook = tok.set
        try:
            with self.assertRaises(G.DeadlineExceeded) as cm:
                up.chat({"messages": []}, 5.0, tok)
            self.assertFalse(cm.exception.sent)
            self.assertEqual(cm.exception.phase, "connected")
            time.sleep(0.2)
            self.assertNotIn("start", fake.kinds())
        finally:
            fake.close()


def gw_job_remaining(clock):
    return 20.0 - (clock() - 1000.0)


if __name__ == "__main__":
    unittest.main()
