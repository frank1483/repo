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
import http.client
import select
import socket
import urllib.error
import urllib.parse
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

# 上游是本機／板上服務：直接用 http.client 連線，不經系統代理。
# _NO_PROXY 保留給測試與工具當不走代理的本機用戶端（舊名相容）。
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DeadlineExceeded(Exception):
    """上游呼叫因期限到或呼叫端取消而被強制中斷。

    phase：中斷時所在階段（_ConnGuard.PHASES）；sent：請求是否已通過 claim_send（可能已送到上游）。
    """

    def __init__(self, msg, phase="unknown", sent=False):
        super().__init__(msg)
        self.phase = phase
        self.sent = sent


class UpstreamHTTPError(Exception):
    pass


class Upstream:
    """把 OpenAI 形式的請求送到真正的模型，回 (content 文字, 原始回覆 dict)。"""
    name = "none"

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model

    def chat(self, req: dict, timeout_s: float, cancel=None):
        raise RuntimeError("upstream none：沒有設定模型")

    # 測試用掛鉤：連線建立後、發布 socket 與送出前呼叫（可放屏障模擬「連線中被取消」）
    _after_connect_hook = None
    _before_send_hook = None   # 測試用：socket 已發布、尚未 claim_send
    _after_read_hook = None    # 測試用：回應已讀完、最後一次 check 之前

    def _post(self, path, body, timeout_s, cancel: "CancelToken | None" = None):
        """送出並在期限到或被取消時強制關閉上游連線（v0.4.1）。

        * 計時器在 timeout_s 到時 abort；cancel 透過回呼 abort（不另開等待執行緒）。
        * socket 發布、abort、送出三者由同一把鎖同步：已 abort 就不連線；
          連線建立後才發現已 abort → 立即關閉、拒絕送出；送出中 abort → shutdown 該 socket。
        * 「上游斷線後 Ollama 會停止推論」是部署假設，尚未在真模型上驗證。
        """
        u = urllib.parse.urlsplit(self.url + path)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(u.hostname, u.port, timeout=max(0.05, timeout_s))
        g = _ConnGuard()
        timer = threading.Timer(max(0.0, timeout_s), g.abort)
        timer.daemon = True
        unregister = cancel.on_cancel(g.abort) if cancel is not None else (lambda: None)
        timer.start()
        try:
            g.check()                      # 已取消／已到期：不連線
            conn.connect()
            if self._after_connect_hook:
                self._after_connect_hook()
            g.publish(conn.sock)           # 同鎖檢查：若期間已 abort → 關閉並丟 DeadlineExceeded
            target = u.path + (("?" + u.query) if u.query else "")
            payload = json.dumps(body).encode("utf-8")
            if self._before_send_hook:
                self._before_send_hook()
            g.claim_send()                 # 取消與送出的唯一判定點
            conn.request("POST", target, body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = resp.read()
            g.mark("received")
            if self._after_read_hook:
                self._after_read_hook()
            g.check()                      # 讀完才發現已 abort：當作期限到（sent=True）
            if resp.status >= 400:
                raise UpstreamHTTPError(f"HTTP {resp.status}: {data[:200]!r}")
            return json.loads(data.decode("utf-8"))
        except DeadlineExceeded:
            raise
        except (OSError, http.client.HTTPException) as exc:
            if g.aborted:
                raise DeadlineExceeded(f"upstream aborted at deadline/cancel (phase {g.phase})",
                                       g.phase, g.sent) from exc
            raise
        finally:
            timer.cancel()
            unregister()
            conn.close()


class _ConnGuard:
    """上游連線的階段、abort 與 socket 發布同步（v0.4.3）。

    階段：idle → connected（socket 已發布）→ sending（已通過 claim_send，請求可能已到上游）
          → received（回應已讀完）。中斷時以「當下階段」判定 sent，不再用錯誤字串猜。
    """
    PHASES = ("idle", "connected", "sending", "received")

    def __init__(self):
        self._lock = threading.Lock()
        self.aborted = False
        self.phase = "idle"
        self._sock = None

    @property
    def sent(self):
        return self.phase in ("sending", "received")

    def abort(self):
        # 在鎖內 shutdown（非阻塞）：與 claim_send 互斥，沒有「已標記 abort 但還沒關」的空窗
        with self._lock:
            self.aborted = True
            sock = self._sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _raise(self, msg):
        raise DeadlineExceeded(f"{msg} (phase {self.phase})", self.phase, self.sent)

    def check(self):
        with self._lock:
            if self.aborted:
                self._raise("cancelled before send" if not self.sent else "cancelled after send")

    def publish(self, sock):
        with self._lock:
            if self.aborted:
                try:
                    sock.close()
                finally:
                    self._raise("cancelled during connect; socket closed, not sent")
            self._sock = sock
            self.phase = "connected"

    def claim_send(self):
        """送出前的唯一同步點：abort 先拿到鎖 → 這裡丟例外、0 個 POST；
        這裡先通過 → phase=sending，之後的 abort 以 shutdown 中斷傳輸與等待回應。"""
        with self._lock:
            if self.aborted:
                self._raise("cancelled before send; not sent")
            self.phase = "sending"

    def mark(self, phase):
        with self._lock:
            self.phase = phase


class CancelToken:
    """取消旗標＋回呼（取代每次呼叫一條等待執行緒）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._set = False
        self._cbs = []

    def is_set(self):
        with self._lock:
            return self._set

    def set(self):
        with self._lock:
            if self._set:
                return
            self._set = True
            cbs, self._cbs = self._cbs, []
        for cb in cbs:
            cb()

    def on_cancel(self, cb):
        with self._lock:
            if not self._set:
                self._cbs.append(cb)
                def unregister():
                    with self._lock:
                        if cb in self._cbs:
                            self._cbs.remove(cb)
                return unregister
        cb()
        return lambda: None


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

    def chat(self, req, timeout_s, cancel=None):
        opts = {"temperature": 0, "seed": 17,
                "num_predict": int(req.get("max_tokens") or 1024)}
        body = {"model": self.model or req.get("model"), "stream": False, "think": False,
                "format": _json_format(req), "options": opts,
                "messages": req.get("messages", [])}
        out = self._post("/api/chat", body, timeout_s, cancel)
        msg = out.get("message") or {}
        return msg.get("content") or "", out


class OpenAIUpstream(Upstream):
    """llama.cpp llama-server / vLLM（之後板上可用這種）。"""
    name = "openai"

    def chat(self, req, timeout_s, cancel=None):
        body = dict(req)
        body["model"] = self.model or req.get("model")
        body["temperature"] = 0
        body["stream"] = False
        body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        if "response_format" not in body:
            body["response_format"] = {"type": "json_object"}
        out = self._post("/chat/completions", body, timeout_s, cancel)
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
    """一次呼叫的狀態機（v0.4.1）。所有終態都在同一把鎖內、對照同一個時鐘決定：

    queued → running → completed（期限前完成，可交付）
                     ↘ cancelled（期限到／呼叫端斷線；之後的結果一律不交付）
    """
    _ids = itertools.count(1)

    def __init__(self, feature, req, budget_s, harness="unversioned", clock=time.monotonic):
        self.id = next(_Job._ids)
        self.feature = feature
        self.req = req
        self.budget_s = budget_s
        self.harness = harness
        self.clock = clock
        self.t_enq = time.time()
        self.t0 = clock()
        self.deadline = self.t0 + budget_s
        self.done = threading.Event()      # 有可交付結果，或已取消
        self.log_written = threading.Event()  # worker 的紀錄已落檔（只供觀察，不擋交付）
        self.cancel = CancelToken()
        self.cancel_reason = None
        self.state = "queued"
        self.lock = threading.Lock()
        self.result = None  # (http_status, body_dict)

    def remaining(self) -> float:
        return self.deadline - self.clock()

    def _cancel_locked(self, reason):
        self.state = "cancelled"
        self.cancel_reason = reason

    def begin(self) -> bool:
        """worker 要送模型前呼叫；已取消或已過期 → False（不送）。"""
        with self.lock:
            if self.state == "queued" and self.clock() < self.deadline:
                self.state = "running"
                return True
            if self.state != "cancelled":
                self._cancel_locked("deadline")
        self.cancel.set()
        self.done.set()
        return False

    def complete(self, result) -> bool:
        """worker 交回結果；只有「未取消且仍在期限內」才成立。過期一律改判取消。"""
        with self.lock:
            if self.state == "running" and self.clock() < self.deadline:
                self.result = result
                self.state = "completed"
                ok = True
            else:
                if self.state != "cancelled":
                    self._cancel_locked("deadline")
                ok = False
        self.done.set()   # 成功或取消都立刻叫醒呼叫端；紀錄之後才寫，與交付分開
        return ok

    def release(self):
        """相容舊呼叫：紀錄寫完後呼叫；不影響交付。"""
        self.log_written.set()

    def abandon(self, reason: str) -> bool:
        """呼叫端放棄（期限到或斷線）。已完成 → False（照常交付，一定在期限前完成）。"""
        with self.lock:
            if self.state == "completed":
                return False
            if self.state != "cancelled":
                self._cancel_locked(reason)
        self.cancel.set()
        self.done.set()
        return True


class Gateway:
    def __init__(self, upstream: Upstream, log_path: str, budgets: dict | None = None,
                 clock=time.monotonic):
        self.upstream = upstream
        self.clock = clock
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

    def submit(self, feature: str, req: dict, harness: str = "unversioned",
               deadline_s: float | None = None, client_gone=None, job_out=None) -> tuple[int, dict]:
        """期限／取消契約（v0.4.1）：
        * 有效期限 = min(功能預算, 呼叫端 X-GCS-Deadline-Ms)；呼叫端只能縮短、不能放寬。
        * 只有在期限前完成的結果會交付；回應最晚在有效期限（＋排程誤差）送出，不為寫紀錄多等。
        * 期限到或呼叫端斷線 → 取消：排隊中的不送模型；送出中的強制關閉上游連線；
          之後才回來的結果不交付，只記錄。
        """
        budget = self.budget(feature)
        if deadline_s is not None and deadline_s > 0:
            budget = min(budget, deadline_s)
        job = _Job(feature, req, budget, harness, clock=self.clock)
        if job_out is not None:
            job_out.append(job)
        prio = PRIORITY.get(feature, UNKNOWN_PRIORITY)
        with self._cv:
            heapq.heappush(self._heap, (prio, next(self._seq), job))
            self._cv.notify()
        reason = "deadline"
        while not job.done.is_set():
            if job.state == "completed":   # 已成功認領：不等 done／紀錄
                break
            rem = job.remaining()
            if rem <= 0:
                break
            if job.done.wait(min(rem, 0.2)):
                break
            if client_gone is not None and client_gone():
                reason = "client_gone"
                break
        if job.abandon(reason):
            r = job.cancel_reason or reason
            return 504, {"error": {"message": f"gateway {r}", "type": "deadline"}}
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
               "harness": job.harness,
               "schema_hash": _sha16(_json_format(job.req))
                              if isinstance(_json_format(job.req), dict) else None,
               "queue_wait_s": round(wait_s, 3), "budget_s": job.budget_s,
               # 有沒有用到約束解碼：json_schema = 候選 ID 等 schema 已交給 Ollama format；json = 只要求 JSON
               "format_kind": "json_schema" if isinstance(_json_format(job.req), dict) else "json"}
        remaining = job.remaining()
        if remaining <= 0.5 and job.state == "queued":
            job.abandon("deadline")          # 剩不到 0.5 秒：不值得送模型
        if not job.begin():
            rec.update(ok=False, error=("cancelled before start: client_gone"
                                        if job.cancel_reason == "client_gone" else "expired in queue"),
                       cancel_reason=job.cancel_reason, latency_s=0.0, content="",
                       claimed=False, upstream_attempted=False, sent_upstream=False, job_id=job.id)
            with job.lock:  # 供檢查用的終態結果；呼叫端已自行回 504，這個值不會被交付
                if job.result is None:
                    job.result = (504, {"error": {"message": "expired in gateway queue",
                                                  "type": "deadline"}})
            self.stats["expired"] += 1
            self._log(rec)
            return
        remaining = job.remaining()
        rec["deadline_s"] = round(remaining, 3)
        try:
            rec["upstream_attempted"] = True
            content, raw = self.upstream.chat(job.req, remaining, job.cancel)
            lat = time.time() - t_start
            rec.update(ok=True, error=None, latency_s=round(lat, 3), content=content,
                       upstream_meta={k: raw.get(k) for k in ("eval_count", "prompt_eval_count",
                                                              "total_duration", "usage") if k in raw})
            self.stats["ok"] += 1
            result = (200, {
                "id": "gcs-" + rec["prompt_hash"], "object": "chat.completion",
                "created": int(t_start), "model": self.upstream.model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "gcs_gateway": {"feature": job.feature, "queue_wait_s": rec["queue_wait_s"],
                                "latency_s": rec["latency_s"]}})
        except DeadlineExceeded as exc:
            lat = time.time() - t_start
            rec.update(ok=False, error=f"deadline: {exc} ({job.cancel_reason or 'deadline'})",
                       latency_s=round(lat, 3), content="",
                       sent_upstream=exc.sent, upstream_phase=exc.phase)
            self.stats["error"] += 1
            result = (504, {"error": {"message": rec["error"], "type": "deadline"}})
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError,
                ValueError, RuntimeError, UpstreamHTTPError, http.client.HTTPException) as exc:
            lat = time.time() - t_start
            rec.update(ok=False, error=f"{type(exc).__name__}: {exc}", latency_s=round(lat, 3),
                       content="")
            self.stats["error"] += 1
            result = (502, {"error": {"message": rec["error"], "type": "upstream"}})
        self.stats["calls"] += 1
        # claimed = 期限前完成、可交付給 HTTP 層；是否真的寫到用戶端另記 http_write 事件
        rec["claimed"] = job.complete(result)
        if not rec["claimed"]:
            rec["late_discarded"] = True
            rec["cancel_reason"] = job.cancel_reason
        rec["job_id"] = job.id
        self._log(rec)
        job.release()

    def _log(self, rec: dict):
        with self._log_lock, open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def queue_len(self) -> int:
        with self._cv:
            return len(self._heap)


# ------------------------------------------------------------------ HTTP

def make_handler(gw: Gateway):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, data, jobs=None):
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            ok, err = True, None
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b)
                self.wfile.flush()
            except OSError as exc:
                ok, err = False, f"{type(exc).__name__}: {exc}"
            if jobs:
                # http_write：回應是否寫進 socket（不保證對方已讀取）
                gw._log({"event": "http_write", "job_id": jobs[0].id, "feature": jobs[0].feature,
                         "status": code, "write_ok": ok, "error": err,
                         "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")})

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-GCS-Feature, X-GCS-Harness, X-GCS-Deadline-Ms")
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
            harness = self.headers.get("X-GCS-Harness", "unversioned")
            deadline_s = None
            raw_dl = self.headers.get("X-GCS-Deadline-Ms")
            if raw_dl:
                try:
                    v = float(raw_dl) / 1000.0
                    deadline_s = v if v > 0 and v == v else None
                except ValueError:
                    deadline_s = None  # 不認得就忽略，用功能預算
            conn = self.connection

            def client_gone():
                try:
                    r, _, _ = select.select([conn], [], [], 0)
                    return bool(r) and conn.recv(1, socket.MSG_PEEK) == b""
                except (OSError, ValueError):
                    return True
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": {"message": "bad json"}})
            if path in ("/v1/chat/completions", "/chat/completions"):
                jobs = []
                code, body = gw.submit(feat, req, harness=harness, deadline_s=deadline_s,
                                       client_gone=client_gone, job_out=jobs)
                return self._send(code, body, jobs)
            if path == "/api/chat":  # Ollama 原生格式也收，回 Ollama 形式
                oreq = {"messages": req.get("messages", []),
                        "max_tokens": (req.get("options") or {}).get("num_predict")}
                if isinstance(req.get("format"), dict):
                    oreq["response_format"] = {"type": "json_schema",
                                               "json_schema": {"schema": req["format"]}}
                jobs = []
                code, body = gw.submit(feat, oreq, harness=harness, deadline_s=deadline_s,
                                       client_gone=client_gone, job_out=jobs)
                if code != 200:
                    return self._send(code, body, jobs)
                return self._send(200, {"model": body["model"], "done": True,
                                        "message": body["choices"][0]["message"],
                                        "gcs_gateway": body["gcs_gateway"]}, jobs)
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
