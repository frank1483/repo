"""可抽換的輕量 LLM 後端（三功能共用）。

只用標準庫。用環境變數切換，不改程式：
  GCS_LLM_BACKEND = openai | ollama | none   （預設 none：全部走規則）
  GCS_LLM_URL     = 例 http://127.0.0.1:8000/v1（openai 相容）或 http://127.0.0.1:11434（ollama）
  GCS_LLM_MODEL   = 模型名稱
規則：模型永遠只回 JSON；呼叫失敗或格式不符時回 ok=False，由呼叫端退回規則。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request


def default_timeout() -> float:
    """GCS_LLM_TIMEOUT（秒），CPU 推論較慢時可調大；預設 60。"""
    try:
        return float(os.environ.get("GCS_LLM_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _result(ok, data=None, raw="", latency=0.0, error=None, backend="none", model=""):
    return {"ok": ok, "data": data, "raw": raw, "latency_s": round(latency, 3),
            "error": error, "backend": backend, "model": model}


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    return json.loads(text[start:end + 1])


def _check_schema(data, schema: dict):
    """極簡檢查：只確認必要欄位存在與型別大致正確。"""
    if not isinstance(data, dict):
        return "not an object"
    for key, typ in schema.get("required", {}).items():
        if key not in data:
            return f"missing {key}"
        if typ == "str" and not isinstance(data[key], str):
            return f"{key} not str"
        if typ == "list" and not isinstance(data[key], list):
            return f"{key} not list"
    return None


class LLMBackend:
    name = "none"

    def __init__(self, url: str = "", model: str = ""):
        self.url = url.rstrip("/")
        self.model = model

    def available(self) -> bool:
        return False

    def complete_json(self, system: str, user: str, schema: dict, timeout_s: float = None) -> dict:
        return _result(False, error="backend none", backend=self.name)

    def _post(self, path: str, body: dict, timeout_s: float):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _finish(self, text: str, t0: float, schema: dict, msg: dict = None):
        latency = time.time() - t0
        if not text.strip():
            think = (msg or {}).get("thinking") or (msg or {}).get("reasoning_content") or ""
            return _result(False, raw=f"[content 空] thinking 前 800 字：{think[:800]}", latency=latency,
                           error="empty content", backend=self.name, model=self.model)
        try:
            data = _extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            return _result(False, raw=text, latency=latency, error=f"bad json: {exc}",
                           backend=self.name, model=self.model)
        err = _check_schema(data, schema)
        if err:
            return _result(False, data, text, latency, f"schema: {err}", self.name, self.model)
        return _result(True, data, text, latency, None, self.name, self.model)


class OpenAICompatBackend(LLMBackend):
    """vLLM / llama.cpp server / Ollama 的 /v1/chat/completions。"""
    name = "openai"

    def available(self) -> bool:
        return bool(self.url and self.model)

    def complete_json(self, system, user, schema, timeout_s=None):
        timeout_s = timeout_s or default_timeout()
        t0 = time.time()
        # 關閉 thinking（Gemma 4 等預設會先思考，吃光輸出上限、content 變空）；不認得的伺服器會忽略
        body = {"model": self.model, "temperature": 0, "max_tokens": 1024,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        try:
            out = self._post("/chat/completions", body, timeout_s)
            msg = out["choices"][0]["message"]
            text = msg.get("content") or ""
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, OSError) as exc:
            return _result(False, raw="", latency=time.time() - t0, error=str(exc),
                           backend=self.name, model=self.model)
        return self._finish(text, t0, schema, msg)


class OllamaBackend(LLMBackend):
    name = "ollama"

    def available(self) -> bool:
        return bool(self.url and self.model)

    def complete_json(self, system, user, schema, timeout_s=None):
        timeout_s = timeout_s or default_timeout()
        t0 = time.time()
        body = {"model": self.model, "stream": False, "format": "json", "think": False,
                "options": {"temperature": 0, "seed": 17, "num_predict": 1024},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        try:
            out = self._post("/api/chat", body, timeout_s)
            msg = out["message"]
            text = msg.get("content") or ""
        except (urllib.error.URLError, TimeoutError, KeyError, OSError) as exc:
            return _result(False, raw="", latency=time.time() - t0, error=str(exc),
                           backend=self.name, model=self.model)
        return self._finish(text, t0, schema, msg)


def get_backend() -> LLMBackend:
    kind = os.environ.get("GCS_LLM_BACKEND", "none").lower()
    url = os.environ.get("GCS_LLM_URL", "")
    model = os.environ.get("GCS_LLM_MODEL", "")
    if kind == "openai":
        return OpenAICompatBackend(url or "http://127.0.0.1:8000/v1", model)
    if kind == "ollama":
        return OllamaBackend(url or "http://127.0.0.1:11434", model)
    return LLMBackend()


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n---\n" + user).encode("utf-8")).hexdigest()[:16]


# ---- 共同決策格式：模型只能從演算法給的候選 ID 裡選 ----

DECISION_SCHEMA = {"required": {"decision": "str", "choice_id": "str", "reason_zh": "str",
                                "evidence_ids": "list"}}


def pick_candidate(backend: LLMBackend, task_zh: str, candidates: list, evidence: list,
                   rule_choice: str, timeout_s: float = None) -> dict:
    """H-a：演算法產生候選並先算出規則選擇，模型在候選內挑一個或 HOLD。

    回傳 {"choice_id", "source": "llm"|"rule", "reason_zh", "evidence_ids", "llm": 呼叫紀錄}
    """
    # 模型只能選可直接套用的候選：不可行或需換電分趟的都不算
    ids = {c["id"] for c in candidates if c.get("feasible", True) and not c.get("requires_battery_swap")}
    ev_ids = {e["id"] for e in evidence}
    fallback = {"choice_id": rule_choice, "source": "rule", "decision": "SELECT",
                "reason_zh": "規則選擇：可行候選中能耗最低且涵蓋所有必要目標。",
                "evidence_ids": [], "llm": None}
    if not backend.available():
        return fallback
    system = ("你是無人機地面站的任務規劃助理。只能從給定候選中選一個 id，"
              "或在資訊不足、全部有風險時回 HOLD。只輸出 JSON："
              '{"decision":"SELECT|HOLD","choice_id":"<候選id或空字串>",'
              '"reason_zh":"一句繁體中文理由","evidence_ids":["證據id"]}')
    user = json.dumps({"task": task_zh, "candidates": candidates, "evidence": evidence},
                      ensure_ascii=False)
    res = backend.complete_json(system, user, DECISION_SCHEMA, timeout_s)
    res["prompt_hash"] = prompt_hash(system, user)
    if not res["ok"]:
        fallback["llm"] = res
        fallback["reason_zh"] += f"（模型無效：{res['error']}）"
        return fallback
    d = res["data"]
    decision = d.get("decision", "").upper()
    cited = [e for e in d.get("evidence_ids", []) if e in ev_ids]
    if decision == "HOLD":
        return {"choice_id": "", "source": "llm", "decision": "HOLD",
                "reason_zh": d.get("reason_zh", ""), "evidence_ids": cited, "llm": res}
    if decision != "SELECT" or d.get("choice_id") not in ids:
        fallback["llm"] = res
        fallback["reason_zh"] += "（模型選了不存在的候選，已退回規則）"
        return fallback
    return {"choice_id": d["choice_id"], "source": "llm", "decision": "SELECT",
            "reason_zh": d.get("reason_zh", ""), "evidence_ids": cited, "llm": res}
