"""共用狀態機迴圈引擎（slot loop），Python 版。

與 ui_agent/qml/GcpAgentSlotLoop.js 是同一份契約：兩邊都要通過 gcs_demo/agent_loop_vectors.json，
所以 UI agent、告警、任務規劃用的是同一套迴圈行為。

程式擁有迴圈，功能端只提供「方法庫」(lib)：
  lib.begin(h)            開始：呼叫 h.finish(...) / h.rule_fallback(...)，或 h.go(state, observation)
  lib.options(st)         -> {"need": "要填什麼", "allowed": [{"code", "zh"}]}
  lib.header(st)          -> 提示詞開頭幾行（句子、目前狀態、已知、觀察）
  lib.transition(code, h) -> ""：已前進；非空字串：前置條件不符，視為無效回答（可修正一次）
  lib.rule_decision()     -> 規則決策（退回用）
  lib.finalize(decision)  -> 選填，回傳前整理決策
引擎負責：外部狀態物件、每步重建短提示、只填一個列舉值 {"value":"代碼"}、嚴格檢查、
修正一次、呼叫上限、退回規則。不碰網路、檔案或裝置；傳輸與期限由呼叫端處理。
只用 Python 標準庫。
"""
from __future__ import annotations

import copy as _copy
import json

ENGINE_VERSION = "slot-loop-1"
DEFAULT_MAX_CALLS = 4


def _js_str(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def default_extract(text):
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except ValueError:
        return None


class _Helper:
    def __init__(self, sess):
        self._s = sess
        self.st = sess.st

    def log(self, event):
        self._s._log(event)

    def go(self, state, observation=None):
        self._s._go(state, observation)

    def finish(self, decision, source, why=""):
        self._s._finish(decision, source, why)

    def escalate(self, why, extra=None):
        d = {"decision": "CLARIFY", "choice_id": "", "reason_zh": why}
        d.update(extra or {})
        self._s._finish(d, "state_machine", why)

    def rule_fallback(self, why, source=None):
        self._s._rule_fallback(why, source)


class Session:
    def __init__(self, lib, *, version=ENGINE_VERSION, system_prompt="", max_calls=DEFAULT_MAX_CALLS,
                 extract_json=default_extract, goal="", model_enabled=True):
        self.lib = lib
        self.system_prompt = system_prompt
        self.max_calls = max_calls or DEFAULT_MAX_CALLS
        self.extract = extract_json
        self.st = {"version": version, "goal": str(goal or ""), "state": "S1", "kind": "", "slots": {},
                   "need": "", "allowed": [], "last_observation": "", "last_error": "",
                   "repair_used": False, "model_calls": 0, "trace": [], "done": None}
        self.h = _Helper(self)
        lib.begin(self.h)
        if self.st["done"] is None and model_enabled is False:
            self._rule_fallback("模型未啟用", "rule")

    # ---- engine internals
    def _log(self, event):
        event = dict(event)
        event["state"] = self.st["state"]
        self.st["trace"].append(_copy.deepcopy(event))

    def _finish(self, decision, source, why=""):
        decision = _copy.deepcopy(decision)
        if hasattr(self.lib, "finalize"):
            decision = self.lib.finalize(decision)
        decision["source"] = source
        decision["model_errors"] = [e["why"] for e in self.st["trace"] if e["event"] == "invalid"]
        self.st["state"] = "END"
        self.st["done"] = decision
        self._log({"event": "done", "decision": decision.get("decision"),
                   "ids": [s["choice_id"] for s in decision.get("steps") or []], "source": source, "why": why or ""})

    def _rule_fallback(self, why, source=None):
        self._finish(self.lib.rule_decision(), "rule_fallback", why)
        if source:
            self.st["done"]["source"] = source

    def _go(self, state, observation=None):
        st = self.st
        st["state"] = state
        if observation is not None:
            st["last_observation"] = observation
        o = self.lib.options(st)
        st["need"] = o["need"]
        st["allowed"] = o["allowed"]
        st["last_error"] = ""

    def _render(self):
        st = self.st
        lines = list(self.lib.header(st))
        lines.append("要填：" + st["need"])
        lines.append("只能選：" + "｜".join(a["code"] + " " + a["zh"] for a in st["allowed"]))
        if st["last_error"]:
            lines.append("上次錯誤：" + st["last_error"] + "。請只從清單重選一個代碼。")
        lines.append('只輸出 JSON：{"value":"代碼"}')
        codes = [a["code"] for a in st["allowed"]]
        return {"version": st["version"], "state": st["state"], "repair": st["last_error"] != "",
                "messages": [{"role": "system", "content": self.system_prompt},
                             {"role": "user", "content": "\n".join(lines)}],
                "schema": {"type": "object", "additionalProperties": False, "required": ["value"],
                           "properties": {"value": {"type": "string", "enum": codes}}},
                "codes": codes}

    def _invalid(self, why, raw):
        st = self.st
        self._log({"event": "invalid", "why": why, "raw": _js_str(raw)[:200]})
        if not st["repair_used"] and st["model_calls"] < self.max_calls:
            st["repair_used"] = True
            st["last_error"] = why
            self._log({"event": "repair_requested", "why": why})
            return
        self._rule_fallback(("修正一次後仍無效：" if st["repair_used"] else "模型呼叫已達上限：") + why)

    def _parse(self, raw):
        obj = self.extract(raw)
        if not isinstance(obj, dict):
            return {"error": "回覆不是 JSON 物件"}
        if list(obj.keys()) != ["value"]:
            return {"error": "只能有 value 一個欄位"}
        if not isinstance(obj["value"], str):
            return {"error": "value 必須是字串"}
        codes = [a["code"] for a in self.st["allowed"]]
        v = obj["value"]
        if v in codes:
            return {"value": v}
        hit = _lenient_prefix(v, codes)
        if hit is not None:
            return {"value": hit, "lenient_prefix": True}
        return {"error": "回答「" + v[:40] + "」不在可選清單內"}

    # ---- host API
    def state(self):
        return _copy.deepcopy(self.st)

    def next(self):
        st = self.st
        if st["done"] is not None:
            return {"type": "done", "decision": _copy.deepcopy(st["done"]), "trace": _copy.deepcopy(st["trace"]),
                    "model_calls": st["model_calls"]}
        if st["model_calls"] >= self.max_calls:
            self._rule_fallback("模型呼叫已達上限")
            return self.next()
        return {"type": "ask", "call": self._render()}

    def answer(self, raw):
        st = self.st
        if st["done"] is not None:
            raise RuntimeError("session already finished")
        st["model_calls"] += 1
        self._log({"event": "model_reply", "raw": _js_str(raw)[:200], "repair": st["last_error"] != ""})
        p = self._parse(raw)
        if "error" in p:
            self._invalid(p["error"], raw)
            return
        if p.get("lenient_prefix"):
            self._log({"event": "lenient_prefix", "value": p["value"]})
        self._log({"event": "filled", "value": p["value"]})
        problem = self.lib.transition(p["value"], self.h)
        if problem:
            self._invalid(problem, p["value"])

    def fail(self, reason):
        if self.st["done"] is not None:
            return
        self.st["model_calls"] += 1
        self._invalid("模型未回覆：" + str(reason or "error"), "")


def _lenient_prefix(v, codes):
    """模型常把「代碼 說明」整段抄回：開頭（去掉前導空白）恰為一個合法代碼，且後面緊接非英數字元或結尾時，取該代碼。
    多個代碼都符合時取最長者；不符合就回 None（仍走原本的修正／規則備援）。"""
    s = v.lstrip()
    best = None
    for c in codes:
        if c and s.startswith(c):
            rest = s[len(c):]
            if rest == "" or not (rest[0].isascii() and (rest[0].isalnum() or rest[0] == "_")):
                if best is None or len(c) > len(best):
                    best = c
    return best


def run(sess: Session, model):
    """同步驅動：model(call) 回傳原始回覆文字；None 代表沒回覆；丟例外視為失敗。"""
    calls = []
    for _ in range(16):
        step = sess.next()
        if step["type"] == "done":
            return {"decision": step["decision"], "trace": step["trace"], "model_calls": step["model_calls"],
                    "calls": calls}
        calls.append(step["call"])
        try:
            reply = model(step["call"]) if model else None
        except Exception as exc:  # noqa: BLE001 - transport errors count as a failed answer
            sess.fail(str(exc))
            continue
        if reply is None:
            sess.fail("no model")
        else:
            sess.answer(reply)
    raise RuntimeError("slot loop did not terminate")


def backend_model(backend, timeout_s=None, record=None):
    """把 gcs_demo.llm 的後端包成 run() 用的 model(call)。原始回覆交給引擎嚴格檢查。"""
    def model(call):
        system, user = call["messages"][0]["content"], call["messages"][1]["content"]
        res = backend.complete_json(system, user, {"required": {"value": "str"}}, timeout_s)
        if record is not None:
            record.append({k: res.get(k) for k in ("ok", "error", "latency_s", "backend", "model", "raw")})
        raw = res.get("raw") or ""
        if not raw.strip():
            raise RuntimeError(res.get("error") or "empty reply")
        return raw
    return model
