"""共用 LLM 閘道（MVP，四功能共用同一個模型）。只用 Python 標準庫。

為什麼要有它：板上只會跑一個輕量模型，UI agent、告警、任務規劃、報告、辨識切換若各自
直連模型會互相卡住。閘道把所有呼叫排成一列、照功能優先順序處理、每次呼叫寫一行紀錄；
之後換成 Genio 520 板上推論，只換閘道後面的引擎，各功能的設定不用改。

啟動（在你的 PC，後面接 Ollama）：
    python -m gcs_demo.llm_gateway
    環境變數（都有預設值）：
      GCS_GATEWAY_PORT      8090
      GCS_GATEWAY_UPSTREAM  ollama | openai | none       （預設 ollama）
      GCS_GATEWAY_UP_URL    ollama 預設 http://127.0.0.1:11434；openai 例 http://127.0.0.1:8080/v1
      GCS_GATEWAY_MODEL     gemma4:e2b
      GCS_GATEWAY_LOG       ./gateway_logs/calls.jsonl
      GCS_GATEWAY_BUDGETS   選填 JSON，覆寫各功能逾時秒數，例 {"ui": 15}

各功能怎麼接（只改網址，不改程式）：
    Python 功能：GCS_LLM_BACKEND=openai
                 GCS_LLM_URL=http://127.0.0.1:8090/f/<功能>/v1
                 GCS_LLM_MODEL=gemma4:e2b
    QML UI agent：模型網址設 http://127.0.0.1:8090/f/ui/v1（openai 模式）
    <功能> = ui | alerts | mission | report | recognition（其他名稱排最後）

規則（llm_contract v0.3）：
  * 優先順序（使用者 2026-11-02 定）：UI > 告警 > 任務規劃 > 報告 > 辨識切換。
    已在跑的呼叫不中斷，只影響排隊順序。
  * 一律 temperature 0、關閉 thinking、要求 JSON 輸出。
  * 每個功能有逾時預算；排隊等待已超過預算的請求直接回 504，不送進模型，
    由功能端退回規則。
  * 每次呼叫（含被拒、逾時）都寫一行 JSONL：功能、排隊秒數、模型秒數、prompt hash、
    原始回覆全文、錯誤。紀錄只追加，不覆寫。
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import itertools
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 數字越小越先處理
PRIORITY = {"ui": 0, "alerts": 1, "mission": 2, "report": 3, "recognition": 4}
UNKNOWN_PRIORITY = 9
# 逾時預算（秒，含排隊）。PC 上 Gemma 4 E2B 中位約 5 秒、首次載入約 12 秒。
DEFAULT_BUDGETS = {"ui": 20.0, "alerts": 30.0, "mission": 60.0, "report": 90.0,
                   "recognition": 30.0, "unknown": 60.0}


def feature_of(path: str, headers) -> tuple[str, str]:
    """回傳 (功能名, 去掉 /f/<功能> 前綴後的路徑)。也接受 X-GCS-Feature 標頭。"""
    feat = (headers.get("X-GCS-Feature") or "").strip().lower()
    rest = path
    if path.startswith("/f/"):
        parts = path.split("/", 3)  # ['', 'f', name, rest]
        if len(parts) >= 3 and parts[2]:
            feat = feat or parts[2].lower()
            rest = "/" + (parts[3] if len(parts) > 3 else "")
    return (feat or "unknown"), rest


def _sha16(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 上游引擎

# 上游是本機／板上服務：不走系統代理（Windows 登錄檔或 HTTP_PROXY 設定會讓 urllib 繞去代理）
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

class Upstream:
    """把 OpenAI 形式的請求送到真正的模型，回 (content 文字, 原始回覆 dict)。"""
    name = "none"

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model

    def chat(self, req: dict, timeout_s: float):
        raise RuntimeError("upstream none：沒有設定模型")

    def _post(self, path, body, timeout_s):
        r = urllib.request.Request(self.url + path, data=json.dumps(body).encode("utf-8"),
                                   headers={"Content-Type": "application/json"})
        with _NO_PROXY.open(r, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _json_format(req: dict):
    """OpenAI response_format → Ollama format。沒指定也要求 JSON（共用契約：模型只回 JSON）。"""
    rf = req.get("response_format") or {}
    if rf.get("type") == "json_schema":
        schema = (rf.get("json_schema") or {}).get("schema")
        if isinstance(schema, dict):
            return schema
    return "json"


class OllamaUpstream(Upstream):
    name = "ollama"

    def chat(self, req, timeout_s):
        opts = {"temperature": 0, "seed": 17,
                "num_predict": int(req.get("max_tokens") or 1024)}
        body = {"model": self.model or req.get("model"), "stream": False, "think": False,
                "format": _json_format(req), "options": opts,
                "messages": req.get("messages", [])}
        out = self._post("/api/chat", body, timeout_s)
        msg = out.get("message") or {}
        return msg.get("content") or "", out


class OpenAIUpstream(Upstream):
    """llama.cpp llama-server / vLLM（之後板上可用這種）。"""
    name = "openai"

    def chat(self, req, timeout_s):
        body = dict(req)
        body["model"] = self.model or req.get("model")
        body["temperature"] = 0
        body["stream"] = False
        body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        if "response_format" not in body:
            body["response_format"] = {"type": "json_object"}
        out = self._post("/chat/completions", body, timeout_s)
        msg = out["choices"][0]["message"]
        return msg.get("content") or "", out


def make_upstream(kind: str, url: str, model: str) -> Upstream:
    kind = (kind or "ollama").lower()
    if kind == "ollama":
        return OllamaUpstream(url or "http://127.0.0.1:11434", model)
    if kind == "openai":
        return OpenAIUpstream(url or "http://127.0.0.1:8080/v1", model)
    return Upstream(url, model)


# ------------------------------------------------------------------ 排隊與紀錄

class _Job:
    def __init__(self, feature, req, budget_s):
        self.feature = feature
        self.req = req
        self.budget_s = budget_s
        self.t_enq = time.time()
        self.done = threading.Event()
        self.result = None  # (http_status, body_dict)


class Gateway:
    def __init__(self, upstream: Upstream, log_path: str, budgets: dict | None = None):
        self.upstream = upstream
        self.log_path = log_path
        self.budgets = dict(DEFAULT_BUDGETS)
        self.budgets.update(budgets or {})
        self._heap = []
        self._seq = itertools.count()
        self._cv = threading.Condition()
        self._log_lock = threading.Lock()
        self.stats = {"calls": 0, "ok": 0, "error": 0, "expired": 0}
        d = os.path.dirname(os.path.abspath(log_path))
        os.makedirs(d, exist_ok=True)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def budget(self, feature: str) -> float:
        return float(self.budgets.get(feature, self.budgets["unknown"]))

    def submit(self, feature: str, req: dict) -> tuple[int, dict]:
        job = _Job(feature, req, self.budget(feature))
        prio = PRIORITY.get(feature, UNKNOWN_PRIORITY)
        with self._cv:
            heapq.heappush(self._heap, (prio, next(self._seq), job))
            self._cv.notify()
        # 多等 5 秒給已送進模型的呼叫收尾；真正的逾時由 worker 判斷
        if not job.done.wait(job.budget_s + 5):
            return 504, {"error": {"message": "gateway timeout", "type": "timeout"}}
        return job.result

    def _run(self):
        while True:
            with self._cv:
                while not self._heap:
                    self._cv.wait()
                _, _, job = heapq.heappop(self._heap)
            self._serve(job)

    def _serve(self, job: _Job):
        t_start = time.time()
        wait_s = t_start - job.t_enq
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "feature": job.feature,
               "priority": PRIORITY.get(job.feature, UNKNOWN_PRIORITY),
               "upstream": self.upstream.name, "model": self.upstream.model,
               "prompt_hash": _sha16(job.req.get("messages", [])),
               "queue_wait_s": round(wait_s, 3), "budget_s": job.budget_s}
        remaining = job.budget_s - wait_s
        if remaining <= 0.5:
            rec.update(ok=False, error="expired in queue", latency_s=0.0, content="")
            self.stats["expired"] += 1
            job.result = (504, {"error": {"message": "expired in gateway queue", "type": "timeout"}})
            self._log(rec)
            job.done.set()
            return
        try:
            content, raw = self.upstream.chat(job.req, remaining)
            lat = time.time() - t_start
            rec.update(ok=True, error=None, latency_s=round(lat, 3), content=content,
                       upstream_meta={k: raw.get(k) for k in ("eval_count", "prompt_eval_count",
                                                              "total_duration", "usage") if k in raw})
            self.stats["ok"] += 1
            job.result = (200, {
                "id": "gcs-" + rec["prompt_hash"], "object": "chat.completion",
                "created": int(t_start), "model": self.upstream.model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "gcs_gateway": {"feature": job.feature, "queue_wait_s": rec["queue_wait_s"],
                                "latency_s": rec["latency_s"]}})
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError,
                ValueError, RuntimeError) as exc:
            lat = time.time() - t_start
            rec.update(ok=False, error=f"{type(exc).__name__}: {exc}", latency_s=round(lat, 3),
                       content="")
            self.stats["error"] += 1
            job.result = (502, {"error": {"message": rec["error"], "type": "upstream"}})
        self.stats["calls"] += 1
        self._log(rec)
        job.done.set()

    def _log(self, rec: dict):
        with self._log_lock, open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def queue_len(self) -> int:
        with self._cv:
            return len(self._heap)


# ------------------------------------------------------------------ HTTP

def make_handler(gw: Gateway):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, data):
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-GCS-Feature")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self):
            _, path = feature_of(self.path, self.headers)
            if path in ("/health", "/"):
                return self._send(200, {"ok": True, "upstream": gw.upstream.name,
                                        "model": gw.upstream.model, "queue": gw.queue_len(),
                                        "stats": gw.stats, "priority": PRIORITY,
                                        "budgets_s": gw.budgets})
            if path == "/v1/models":
                return self._send(200, {"object": "list", "data": [
                    {"id": gw.upstream.model, "object": "model"}]})
            self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            feat, path = feature_of(self.path, self.headers)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": {"message": "bad json"}})
            if path in ("/v1/chat/completions", "/chat/completions"):
                code, body = gw.submit(feat, req)
                return self._send(code, body)
            if path == "/api/chat":  # Ollama 原生格式也收，回 Ollama 形式
                oreq = {"messages": req.get("messages", []),
                        "max_tokens": (req.get("options") or {}).get("num_predict")}
                if isinstance(req.get("format"), dict):
                    oreq["response_format"] = {"type": "json_schema",
                                               "json_schema": {"schema": req["format"]}}
                code, body = gw.submit(feat, oreq)
                if code != 200:
                    return self._send(code, body)
                return self._send(200, {"model": body["model"], "done": True,
                                        "message": body["choices"][0]["message"],
                                        "gcs_gateway": body["gcs_gateway"]})
            self._send(404, {"error": {"message": "not found"}})

        def log_message(self, fmt, *args):
            pass

    return H


def build_from_env() -> tuple[Gateway, int]:
    budgets = {}
    raw = os.environ.get("GCS_GATEWAY_BUDGETS", "")
    if raw:
        budgets = {k: float(v) for k, v in json.loads(raw).items()}
    up = make_upstream(os.environ.get("GCS_GATEWAY_UPSTREAM", "ollama"),
                       os.environ.get("GCS_GATEWAY_UP_URL", ""),
                       os.environ.get("GCS_GATEWAY_MODEL", "gemma4:e2b"))
    gw = Gateway(up, os.environ.get("GCS_GATEWAY_LOG", "gateway_logs/calls.jsonl"), budgets)
    return gw, int(os.environ.get("GCS_GATEWAY_PORT", "8090"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="GCS 共用 LLM 閘道")
    ap.add_argument("--port", type=int)
    ap.add_argument("--host", default="127.0.0.1")  # 只聽本機，不對外開放
    a = ap.parse_args(argv)
    gw, port = build_from_env()
    port = a.port or port
    srv = ThreadingHTTPServer((a.host, port), make_handler(gw))
    print(f"LLM 閘道 http://{a.host}:{port}  上游 {gw.upstream.name} {gw.upstream.url} "
          f"模型 {gw.upstream.model}  紀錄 {gw.log_path}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
