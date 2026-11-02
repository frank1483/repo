"""typed P1/P2/P3 編排的 LLM 說明入口（MVP，契約 v0.3 第 6 節）。

分級一律由演算法先出：告警事件立刻用規則文字顯示，模型說明之後非同步補上。
模型只能寫兩句說明與引用依據；typed 編排目前沒有可執行候選（candidates 為空），
所以 selected_id 必須是 null。回覆抵達時告警版本不同就丟棄，不覆蓋新狀態。
"""
from __future__ import annotations

import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor

from gcs_demo import llm
from .explain import ALERTS_TIMEOUT_S, _SIMPLIFIED, _number_tokens, get_backend

MAX_SENTENCE_CHARS = 60

SEVERITY_ZH = {2: "嚴重", 4: "警告", 5: "注意"}
TITLE_ZH = {"P1": "航線電量可能不足", "P2": "回程探查點有電量風險", "P3": "電池容量可能低於標稱"}

# 依據欄位 → (中文名稱, 單位)；未列出的欄位不給模型看，避免內部名稱外露
EVIDENCE_LABELS = {
    "nominal_end_pct": ("預估落地電量（中值）", "%"),
    "low_pct": ("預估落地電量（下界）", "%"),
    "high_pct": ("預估落地電量（上界）", "%"),
    "reserve_pct": ("落地保留電量", "%"),
    "first_sampled_infeasible_id": ("第一個不可行的回程探查點", ""),
    "first_sampled_infeasible_nominal_eta_s": ("到達該探查點約需", " 秒"),
    "sample_count": ("推估用的資料筆數", " 筆"),
    "energy_span_wh": ("推估涵蓋的放電量", " Wh"),
    "capacity_ratio": ("推估容量占標稱", "%"),
    "soc_overestimate_pct": ("飛控剩餘量可能高估", "%"),
}
_RATIO_KEYS = {"capacity_ratio"}   # 0–1 比值，顯示成百分比

_BANNED = ("一定", "保證", "絕對", "完全安全", "確定安全", "所有必要目標都能完成")

SYSTEM_TYPED = (
    "你是無人機地面站的告警助理。告警等級已由演算法決定，你不能更改，也不能提出新的處置動作。"
    "只能使用 facts 裡的事實與數字，不可自行計算、換算或四捨五入。"
    "allowed_ids 為空時 selected_id 必須是 null。"
    "回覆只輸出 JSON：{\"alert_version\":\"照抄 facts 的 alert_version\",\"selected_id\":null,"
    "\"sentences\":[\"第一句說明發生什麼\",\"第二句說明操作員該注意什麼\"],\"evidence_ids\":[\"E1\"]}。"
    f"sentences 剛好兩句，每句不超過 {MAX_SENTENCE_CHARS} 字。evidence_ids 必須非空且每一項都存在。"
    "一律使用台灣繁體中文，不寫出內部欄位名稱，不可寫「一定」「保證」「絕對」等沒有依據的斷言。"
)

SCHEMA_TYPED = {"required": {"alert_version": "str", "selected_id": "any",
                             "sentences": "list", "evidence_ids": "list"}}


def _fmt(key, value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and math.isfinite(value):
        if key in _RATIO_KEYS:
            value *= 100
        return f"{value:.1f}"
    return None


def alert_version(event: dict) -> str:
    return f"{event.get('mission_version')}|{event['key']}|{event.get('sequence')}"


def typed_view(event: dict) -> dict | None:
    """把 typed 事件轉成模型可見的事實；不是成立中的 raise/update 就回 None（不呼叫模型）。"""
    if event.get("type") not in ("raise", "update") or event.get("active") is not True:
        return None
    evidence = []
    for block in event.get("evidence") or []:
        for key, raw in (block.get("value") or {}).items():
            if key not in EVIDENCE_LABELS:
                continue
            text = _fmt(key, raw)
            if text is None:
                continue
            label, unit = EVIDENCE_LABELS[key]
            evidence.append({"id": f"E{len(evidence) + 1}", "text": label, "value": text + unit, "_key": key})
    if not evidence:
        return None
    pred = event.get("predictor")
    return {"alert_version": alert_version(event), "key": event["key"], "predictor": pred,
            "severity_zh": SEVERITY_ZH.get(event.get("severity"), "注意"),
            "title_zh": TITLE_ZH.get(pred, "告警"), "evidence": evidence, "allowed_ids": []}


def _facts(view):
    return {"alert_version": view["alert_version"], "level": view["severity_zh"],
            "title": view["title_zh"], "allowed_ids": view["allowed_ids"],
            "evidence": [{k: e[k] for k in ("id", "text", "value")} for e in view["evidence"]]}


def rule_text(view: dict) -> dict:
    ev = {e["_key"]: e for e in view["evidence"]}
    first = f"{view['severity_zh']}：{view['title_zh']}"
    if "nominal_end_pct" in ev:
        first += f"，{ev['nominal_end_pct']['text']} {ev['nominal_end_pct']['value']}"
    elif "first_sampled_infeasible_id" in ev:
        first += f"，探查點 {ev['first_sampled_infeasible_id']['value']} 的回程電量不足"
    elif "capacity_ratio" in ev:
        first += f"，{ev['capacity_ratio']['text']} {ev['capacity_ratio']['value']}"
    first += "。"
    second = "目前沒有已驗證可執行的處置選項，請人工判斷。"
    return {"alert_version": view["alert_version"], "selected_id": None,
            "sentences": [first, second], "evidence_ids": [view["evidence"][0]["id"]]}


def validate(d, view) -> str | None:
    if not isinstance(d, dict):
        return "模型輸出必須是物件"
    if d.get("alert_version") != view["alert_version"]:
        return "alert_version 不符"
    sel = d.get("selected_id")
    if view["allowed_ids"]:
        if sel not in view["allowed_ids"]:
            return "selected_id 不在允許集合"
    elif sel is not None:
        return "沒有允許選項時 selected_id 必須是 null"
    s = d.get("sentences")
    if (not isinstance(s, list) or len(s) != 2
            or any(not isinstance(x, str) or not x.strip() or len(x) > MAX_SENTENCE_CHARS for x in s)):
        return f"sentences 必須剛好兩句、非空且每句不超過 {MAX_SENTENCE_CHARS} 字"
    ids = d.get("evidence_ids")
    known = {e["id"] for e in view["evidence"]}
    if not isinstance(ids, list) or not ids or any(x not in known for x in ids):
        return "evidence_ids 必須非空且全部存在"
    text = "\n".join(s)
    if any(e["_key"] in text for e in view["evidence"]) or "_pct" in text or "_id" in text:
        return "說明寫出內部欄位名稱"
    if sum(ch in _SIMPLIFIED for ch in text) >= 2:
        return "說明用了簡體字"
    if any(b in text for b in _BANNED):
        return "說明含沒有依據的斷言"
    allowed = set().union(*(_number_tokens(e["text"] + " " + e["value"]) for e in view["evidence"]))
    for num in sorted(_number_tokens(text)):
        if num not in allowed:
            return f"說明出現事實裡沒有的數字 {num}"
    return None


def explain_typed(view: dict, backend=None, timeout_s=ALERTS_TIMEOUT_S) -> dict:
    """同步呼叫一次模型；任何失敗都回規則文字。給 AsyncExplainer 在背景執行。"""
    rule = rule_text(view)
    user = json.dumps(_facts(view), ensure_ascii=False, allow_nan=False)
    log = {"backend": "?", "model": None, "prompt_sha256": llm.prompt_hash(SYSTEM_TYPED, user),
           "ok": False, "latency_s": None, "error": None, "raw": ""}

    def fallback(reason):
        return {"text": rule, "source": "rule", "fallback_reason": reason, "llm": log}

    try:
        backend = backend or get_backend()
        log.update(backend=getattr(backend, "name", "?"), model=getattr(backend, "model", None))
        res = backend.complete_json(SYSTEM_TYPED, user, SCHEMA_TYPED, timeout_s=timeout_s)
        log.update(ok=res["ok"], latency_s=res.get("latency_s"), error=res.get("error"),
                   raw=(res.get("raw") or "")[:800])
        if res["ok"] is not True:
            return fallback(res.get("error") or "後端未成功")
        reason = validate(res["data"], view)
        if reason:
            return fallback(reason)
        return {"text": dict(res["data"]), "source": "llm", "fallback_reason": None, "llm": log}
    except Exception as exc:
        log.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        return fallback(log["error"])


class AsyncExplainer:
    """規則文字立即回傳；模型說明在背景執行緒補上。

    current(key) 記錄每則告警最新的版本；回覆抵達時版本已變（告警更新或解除）就丟棄。
    poll() 取出可套用的說明，由呼叫端（UI 或模擬迴圈）在自己的執行緒更新畫面。
    """

    def __init__(self, explain_fn, max_workers=1):
        self._fn = explain_fn
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._current = {}
        self._ready = []
        self.discarded = []

    def submit(self, key, version, rule_result, *args):
        """登記新版本並排入背景；回傳規則結果給呼叫端立刻顯示。"""
        with self._lock:
            self._current[key] = version
        fut = self._pool.submit(self._fn, *args)
        fut.add_done_callback(lambda f: self._done(key, version, f))
        return rule_result

    def retire(self, key):
        """告警解除：之後抵達的舊回覆一律丟棄。"""
        with self._lock:
            self._current.pop(key, None)

    def _done(self, key, version, fut):
        try:
            result = fut.result()
        except Exception as exc:          # explain_fn 本身已接住例外，這裡只是保險
            result = {"source": "rule", "fallback_reason": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            if self._current.get(key) == version:
                self._ready.append({"key": key, "version": version, "result": result})
            else:
                self.discarded.append({"key": key, "version": version, "result": result})

    def poll(self):
        with self._lock:
            out, self._ready = self._ready, []
        return out

    def close(self, wait=True):
        self._pool.shutdown(wait=wait)


class TypedAlertExplainer:
    """接在 TypedMissionOrchestrator.tick() 後面：事件先用規則顯示，模型說明非同步補上。"""

    def __init__(self, backend=None, timeout_s=ALERTS_TIMEOUT_S):
        self._backend = backend
        self._timeout = timeout_s
        self.async_ = AsyncExplainer(self._run)

    def _run(self, view):
        return explain_typed(view, self._backend, self._timeout)

    def on_output(self, output: dict) -> list:
        """回傳這一刻要立刻顯示的規則說明；resolve／reset 會讓舊回覆失效。"""
        shown = []
        for event in output.get("events", []):
            if event.get("type") in ("resolve", "reset", "unknown") or event.get("active") is not True:
                self.async_.retire(event["key"])
                continue
            view = typed_view(event)
            if view is None:
                continue
            rule = {"text": rule_text(view), "source": "rule_pending", "fallback_reason": None}
            shown.append({"key": view["key"], "version": view["alert_version"],
                          "result": self.async_.submit(view["key"], view["alert_version"], rule, view)})
        return shown

    def poll(self):
        return self.async_.poll()

    def close(self, wait=True):
        self.async_.close(wait)


class LegacyAlertExplainer:
    """給舊多旋翼引擎（sim.run、AlertFeed 的 explain_fn）用的非同步版本。

    呼叫時立刻回傳規則結果（source=rule_pending），模型說明在背景補上，用 poll() 取回。
    """

    def __init__(self, backend=None, timeout_s=ALERTS_TIMEOUT_S):
        from . import explain as _explain
        self._explain = _explain
        self._backend = backend
        self._timeout = timeout_s
        self.async_ = AsyncExplainer(self._run)

    def _run(self, ev):
        return self._explain.explain(ev, self._backend or get_backend(), timeout_s=self._timeout)

    def __call__(self, ev):
        if ev.get("type") == "resolve":
            self.async_.retire(ev["key"])
            return None
        version = f"{ev['key']}|{ev.get('t')}|{ev.get('type')}"
        rule = {"text": self._explain.rule_text(ev), "source": "rule_pending", "fallback_reason": None}
        return self.async_.submit(ev["key"], version, rule, ev)

    def poll(self):
        return self.async_.poll()

    def close(self, wait=True):
        self.async_.close(wait)
