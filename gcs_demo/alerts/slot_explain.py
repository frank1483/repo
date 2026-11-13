"""告警說明：範本句＋模型選格（共用狀態機迴圈 agent_loop，使用者 2026-11-08 勾選設計文件第 13 項）。

模型不再寫句子。程式在共用迴圈上最多問三格，每格只回 {"value":"代碼"}：
  S_PICK    要推薦哪個允許且可行的處置（allowed_ids 為空就跳過；只有一個就由程式直接填）
  S_BASIS   第一句要引用哪一條依據（只列「程式寫出的句子能通過 v5 驗證器」的依據）
  S_ADVICE  第二句用固定建議清單裡的哪一句
句子全部由程式用範本寫，再交給同一個 v5 驗證器；回覆不合規格修正一次，仍失敗就退回規則文字。
所有模型呼叫共用一個期限（呼叫端給的 timeout_s），不會因為多格而變長。
"""
from __future__ import annotations

import time

from gcs_demo import agent_loop as L

VERSION = "alerts-sm-1"
SYSTEM_PROMPT = ("你是無人機地面站告警說明流程中的一個步驟，只負責填一格。"
                 '只回答一個 JSON：{"value":"代碼"}。代碼只能從「只能選」清單裡挑一個，不可自創。'
                 "告警等級與數字已由演算法決定，你只挑選。")

SEVERITY_ZH = {2: "嚴重", 4: "警告", 5: "注意"}

# 固定的操作建議清單。P1–P3 照設計文件第 13 項；RTL／P4／P5 是草擬，待使用者確認（可直接改字）。
# 句子不可有數字、內部名稱或「一定／保證」這類斷言，驗證器也會再檢查一次。
ADVICE = {
    "P1": [("SHORTEN", "考慮縮短航線或提早返航"), ("WATCH", "持續注意落地電量預估"),
           ("SAVER", "準備改走較省電的航線")],
    "P2": [("DECIDE_SKIP", "到達該探查點前先決定是否跳過"), ("RETURN_EARLY", "注意回程電量，必要時提早返航")],
    "P3": [("TRUST_ESTIMATE", "飛控剩餘電量可能偏高，請以預估值為準"), ("CHECK_HEALTH", "落地後檢查電池健康")],
    "RTL": [("DECIDE_RTL", "到達最晚返航點前決定是否返航"), ("WATCH", "持續注意落地電量預估")],
    "P4": [("CHECK_FAILSAFE", "確認失聯自動返航已開啟"), ("RETURN_BEFORE", "考慮在訊號變弱前返航"),
           ("WATCH", "持續注意鏈路品質變化")],
    "P5": [("RETURN_NOW", "考慮提早返航避開強風"), ("WATCH", "持續注意風速趨勢")],
}
GENERIC_ADVICE = [("ASSESS", "請操作員依告警內容評估是否調整任務")]
# 舊多旋翼引擎的告警 key → 建議清單
LEGACY_GROUP = {"battery_route": "P1", "rtl_point": "RTL", "battery_capacity": "P3",
                "link_route": "P4", "wind_trend": "P5",
                # 電量合併告警（CODEX-APP-0390）：沒有成員資訊時用 P1 的清單；
                # 有 member_status 時由 advice_group() 依成立中、等級最高的成員決定。
                "battery": "P1"}
# 合併後的 battery 告警裡，成員代號 → 建議清單（舊引擎的 P2 是最晚返航點，不是探查點）
BATTERY_MEMBER_GROUP = {"P1": "P1", "P2": "RTL", "P3": "P3"}
NEUTRAL_SECOND = "請操作員評估。"


def advice_group(ev):
    """告警事件 → 建議清單名稱。battery 依成立中、等級最高（數字最小）的成員；
    同等級照 P1、P2、P3 的順序；沒有成立中的成員就用預設 P1。"""
    key = ev.get("key")
    if key != "battery":
        return LEGACY_GROUP.get(key)
    members = ev.get("member_status") or {}
    order = list(BATTERY_MEMBER_GROUP)
    live = [(m.get("severity") if isinstance(m.get("severity"), int) else 99, order.index(name), name)
            for name, m in members.items()
            if name in BATTERY_MEMBER_GROUP and isinstance(m, dict)
            and m.get("truth") == "TRUE" and not m.get("disabled")]
    return BATTERY_MEMBER_GROUP[min(live)[2]] if live else LEGACY_GROUP["battery"]


def _value_text(e):
    if isinstance(e.get("display_value"), str):
        return e["display_value"]
    value, unit = str(e.get("value")), e.get("unit") or ""
    if not unit or value.endswith(unit):
        return value
    return value + ("" if unit == "%" else " ") + unit


def first_sentence(level_zh, title, e):
    """第一句範本：等級：標題，[選項 ]依據名稱 數值。（類別型依據沿用規則句型）"""
    label = e.get("metric_label") or e.get("text") or ""
    head = f"{level_zh}：{title}，"
    if e.get("value_kind") == "categorical_id":
        return f"{head}{label} {e['value']} 的回程電量不足。"
    scope = f"{e['option_id']} " if e.get("option_id") else ""
    return f"{head}{scope}{label} {_value_text(e)}。"


def label_sentence(level_zh, title, e):
    return f"{level_zh}：{title}，主要依據是{e.get('metric_label') or e.get('text') or ''}。"


def second_sentence(advice, pick_label):
    if pick_label:
        s = f"建議「{pick_label}」，{advice}。"
        if len(s) <= 60:
            return s
    return advice + "。"


class AlertSlots:
    """方法庫：給 agent_loop.Session 用。check(output) 回傳 None 或驗證器的拒絕理由。"""

    def __init__(self, *, level_zh, title, evidence, allowed, labels, advice, check, alert_version, rule):
        self.level_zh, self.title = level_zh, title
        self.evidence, self.allowed, self.labels = evidence, allowed, labels
        self.advice, self.check, self.version, self.rule = advice, check, alert_version, rule
        self.h = None
        self.selected = None
        self.basis = None

    # ---- 程式算出每一格可選的代碼（只留能通過驗證的）
    def _output(self, s1, s2, eid):
        return {"alert_version": self.version, "selected_id": self.selected,
                "sentences": [s1, s2], "evidence_ids": [eid]}

    def _basis_options(self):
        out = []
        for e in self.evidence:
            # 數字句綁不上（例如依據不屬於推薦的處置）時，改用不帶數字的句子引用同一條依據
            for s1 in (first_sentence(self.level_zh, self.title, e), label_sentence(self.level_zh, self.title, e)):
                if len(s1) <= 60 and self.check(self._output(s1, NEUTRAL_SECOND, e["id"])) is None:
                    out.append((e, s1))
                    break
        return out

    def _advice_options(self):
        s1 = self.basis[1]
        out = []
        for code, text in self.advice:
            s2 = second_sentence(text, self.labels.get(self.selected))
            if self.check(self._output(s1, s2, self.basis[0]["id"])) is None:
                out.append((code, text, s2))
        return out

    # ---- 狀態轉移（程式決定）
    def begin(self, h):
        self.h = h
        if not self.allowed:
            self._to_basis("沒有可推薦的處置")
        elif len(self.allowed) == 1:
            self.selected = self.allowed[0]
            self._to_basis("唯一可推薦的處置 " + self.selected)
        else:
            h.go("S_PICK", f"可推薦的處置 {len(self.allowed)} 個")

    def _to_basis(self, obs):
        opts = self._basis_options()
        if not opts:
            self.h.rule_fallback("沒有可通過驗證的依據句")
        elif len(opts) == 1:
            self.basis = opts[0]
            self._to_advice("唯一可用的依據 " + opts[0][0]["id"])
        else:
            self.h.go("S_BASIS", obs)

    def _to_advice(self, obs):
        opts = self._advice_options()
        if not opts:
            self.h.rule_fallback("建議句都無法通過驗證")
        elif len(opts) == 1:
            self._finish(opts[0])
        else:
            self.h.go("S_ADVICE", obs)

    def _finish(self, opt):
        out = self._output(self.basis[1], opt[2], self.basis[0]["id"])
        out["advice_code"] = opt[0]
        self.h.finish(out, "llm", "filled")

    def _prompt_label(self, e):
        """提示行用的依據名稱。綁定選項的依據要帶「選項代碼 名稱」，否則多個選項的
        同一指標（例如各選項的任務完成度）在提示裡看起來一模一樣。"""
        metric = e.get("metric_label") or e.get("text") or ""
        oid = e.get("option_id")
        if not oid:
            return metric
        text = e.get("text") or ""
        if text.startswith(str(oid)):
            return text                      # 程式已把代碼與名稱寫進 text
        name = e.get("option_label") or self.labels.get(oid, "")
        return " ".join(x for x in (str(oid), name, metric) if x)

    def header(self, st):
        lines = [f"告警：{self.level_zh}｜{self.title}"]
        lines += [f"{e['id']}：{self._prompt_label(e)} {_value_text(e)}" for e in self.evidence]
        if self.selected:
            lines.append(f"已知：推薦處置={self.selected} {self.labels.get(self.selected, '')}")
        if self.basis:
            lines.append(f"已知：第一句={self.basis[1]}")
        if st["last_observation"]:
            lines.append("觀察：" + st["last_observation"])
        return lines

    def options(self, st):
        s = st["state"]
        if s == "S_PICK":
            return {"need": "要推薦的處置", "allowed": [{"code": c, "zh": self.labels.get(c, c)} for c in self.allowed]}
        if s == "S_BASIS":
            return {"need": "第一句要引用的主要依據",
                    "allowed": [{"code": e["id"], "zh": f"{self._prompt_label(e)} {_value_text(e)}"}
                                for e, _ in self._basis_options()]}
        return {"need": "第二句的操作建議", "allowed": [{"code": c, "zh": t} for c, t, _ in self._advice_options()]}

    def transition(self, code, h):
        s = h.st["state"]
        if s == "S_PICK":
            if code not in self.allowed:
                return "處置「" + code + "」不在允許清單"
            self.selected = code
            self._to_basis("推薦 " + code)
            return ""
        if s == "S_BASIS":
            hit = [o for o in self._basis_options() if o[0]["id"] == code]
            if not hit:
                return "依據「" + code + "」不可用"
            self.basis = hit[0]
            self._to_advice("依據 " + code)
            return ""
        hit = [o for o in self._advice_options() if o[0] == code]
        if not hit:
            return "建議「" + code + "」不可用"
        self._finish(hit[0])
        return ""

    def rule_decision(self):
        return {"rule": True}


def _deadline_model(backend, timeout_s, record):
    """所有格共用一個期限：每次呼叫只給剩下的時間。"""
    end = time.monotonic() + float(timeout_s)

    def model(call):
        left = end - time.monotonic()
        if left <= 0.5:
            raise TimeoutError("告警說明期限已到")
        system, user = call["messages"][0]["content"], call["messages"][1]["content"]
        try:
            res = backend.complete_json(system, user, {"required": {"value": "str"}}, timeout_s=left)
        except Exception as exc:  # noqa: BLE001 - keep the exception type in the fallback reason
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
        record.append({k: res.get(k) for k in ("ok", "error", "latency_s", "raw")})
        raw = res.get("raw") or ""
        if not raw.strip():
            if res.get("ok") and isinstance(res.get("data"), dict):
                return res["data"]
            raise RuntimeError(res.get("error") or "empty reply")
        return raw
    return model


def run(lib: AlertSlots, backend, timeout_s):
    """回傳 (output 或 None, 紀錄)。output 為 None 代表要用規則文字。"""
    record = []
    enabled = backend is not None and (not hasattr(backend, "available") or backend.available())
    sess = L.Session(lib, version=VERSION, system_prompt=SYSTEM_PROMPT, goal=lib.title, model_enabled=enabled)
    r = L.run(sess, _deadline_model(backend, timeout_s, record) if enabled else None)
    d = r["decision"]
    log = {"loop": VERSION, "engine": L.ENGINE_VERSION, "model_calls": r["model_calls"], "calls": record,
           "prompts": [c["messages"][1]["content"] for c in r["calls"]], "trace": r["trace"],
           "latency_s": round(sum(c.get("latency_s") or 0 for c in record), 2),
           "raw": (record[-1].get("raw") or "")[:800] if record else ""}
    if d.get("rule") or r["model_calls"] == 0:
        errors = d.get("model_errors") or []
        why = next((e["why"] for e in reversed(r["trace"]) if e["event"] == "done"), "")
        log["error"] = (why or (errors[-1] if errors else "")) if d.get("rule") else "沒有需要模型填的格，保留規則文字"
        return None, log
    log["error"] = None
    out = {k: d[k] for k in ("alert_version", "selected_id", "sentences", "evidence_ids")}
    out["advice_code"] = d.get("advice_code")
    return out, log
