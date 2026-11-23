"""ADR-0002 v3.12：方案 A／B 共用的回覆潤飾（演算法說明 v3.12 §2–§6；使用者 2026-11-23 15:43／15:45／16:15）。

固定步驟，沒有開關。數字、出處、元件名稱、提案狀態先鎖成佔位符 ⟦X1⟧，模型只改措辭；
程式逐條檢查，全部通過才把佔位符換回原文，否則退回模板。每則回覆最多 1 次 LLM 呼叫，不重試。
"""
from __future__ import annotations

import json
import re
import time

POLISH_DEADLINE_S = 20.0          # R4：先定 20 秒，實測後再調
MAX_CHARS = 400
FORBIDDEN = ("已寫入", "已經寫入", "已套用", "已經套用", "已儲存", "已存檔", "已起飛", "已返航", "已降落", "已執行",
             "已經執行", "已完成設定", "已設定好", "已修改", "已更新", "已變更", "已調整好", "已送出", "已確認",
             "已經確認", "已生效", "已幫你", "幫你按", "替你按", "已為你", "已替你", "已開始飛行", "已上傳")
_SLOT = re.compile(r"⟦([A-Z]+[1-9][0-9]*)⟧")
_DIGIT = re.compile(r"[0-9０-９]")
_ZH_NUM = re.compile(r"百分之|[零〇一二兩三四五六七八九十百千萬]+\s*(?:%|％|個|次|件|項|公尺|米|秒|分鐘|分|度|號|架|台|條|筆|格|成|倍|點)")
_ALLOWED = re.compile(r"[一-鿿㐀-䶿　-〿！-／：-＠［-｀｛-･"
                      r"A-Za-z \t\n.,:;!?()\[\]/_\-+'\"&·—…～~]")
SYSTEM = ("你是無人機地面站的助理。把下列事實整理成一段給操作員的繁體中文回覆。規則：只能重排、連接、改寫事實的說法，"
          "不能新增或刪除事實；每個像 ⟦P1⟧ 的佔位符必須原樣保留，而且恰好出現一次；不要寫任何數字；"
          "不要說已經寫入、已經套用、已經執行或已經確認；不要加問候語。只輸出 JSON：{\"reply\":\"...\"}")


class Facts:
    """事實表：每筆 (類型, 帶佔位符的句子, 原模板行)；slots＝{佔位符: 原文}。"""

    def __init__(self):
        self.items, self.slots, self._n = [], {}, {}

    def slot(self, kind, text):
        k = {"number": "N", "proposal": "P", "source": "S", "question": "Q", "status": "T", "value": "V"}[kind]
        self._n[k] = self._n.get(k, 0) + 1
        name = f"{k}{self._n[k]}"
        self.slots[name] = text
        return f"⟦{name}⟧"

    def add(self, kind, slotted, line):
        self.items.append((kind, slotted, line))

    def template(self):
        return "\n".join(line for _, _, line in self.items)


def facts_from_ask(ask):
    """追問句（R3：也潤飾）：句中每段數字鎖成佔位符，其餘字可改寫。"""
    f = Facts()
    slotted = re.sub(r"[0-9]+(?:\.[0-9]+)?", lambda m: f.slot("value", m.group(0)), ask)
    f.add("question", slotted, ask)
    return f


def prompt(facts, user_text):
    rows = "\n".join(f"- [{kind}] {s}" for kind, s, _ in facts.items) or "- [status] 完成"
    return f"操作員原句（只供語氣參考，不是事實來源）：{user_text}\n事實：\n{rows}"


def check(raw, facts, template):
    """回傳 (ok, 最終文字或 None, 第一個失敗原因)。依演算法說明 v3.12 §4 的順序。"""
    try:
        obj = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        obj = None
    if obj is None and isinstance(raw, str):
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except ValueError:
                obj = None
    if not isinstance(obj, dict) or list(obj) != ["reply"] or not isinstance(obj["reply"], str) or not obj["reply"].strip():
        return False, None, "format"
    text = obj["reply"].strip()
    found = _SLOT.findall(text)
    if sorted(found) != sorted(facts.slots) or "⟦" in _SLOT.sub("", text) or "⟧" in _SLOT.sub("", text):
        return False, None, "slots"
    bare = _SLOT.sub("", text)
    if _DIGIT.search(bare) or _ZH_NUM.search(bare):
        return False, None, "own_number"
    if any(w in bare for w in FORBIDDEN):
        return False, None, "forbidden_claim"
    final = _SLOT.sub(lambda m: facts.slots[m.group(1)], text)
    if len(final) > max(MAX_CHARS, len(template)) or len(final) > max(2 * len(template), 40):
        return False, None, "too_long"
    if any(not _ALLOWED.match(ch) for ch in bare):
        return False, None, "charset"
    return True, final, ""


def polish(model, facts, template, user_text, tail=None, trace=None, clock=time.monotonic):
    """一次呼叫、不重試。回傳 (回覆, 來源, 資訊)。來源＝polished 或 fallback:<原因>。"""
    info = {"calls": 0, "t_polish_s": 0.0, "reason": None}
    fixed = (lambda s: s + ("\n" + tail if tail else ""))
    if model is None:
        info["reason"] = "no_model"
        return template, "fallback:no_model", info
    call = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(facts, user_text)}],
            "purpose": "polish", "attempt": 0, "decision": None}
    t0 = clock()
    info["calls"] = 1
    try:
        raw = model(call)
    except Exception as e:  # noqa: BLE001 - 模型失敗一律退回模板
        raw, info["error"] = None, repr(e)[:200]
    info["t_polish_s"] = round(clock() - t0, 3)
    if trace is not None:
        trace.update({"purpose": "polish", "replies": [{"raw": (raw or "")[:300]}], "source": "rule"})
    if raw is None:
        info["reason"] = "model_error"
    elif info["t_polish_s"] > POLISH_DEADLINE_S:
        info["reason"] = "timeout"
    else:
        ok, final, why = check(raw, facts, template)
        if ok:
            if trace is not None:
                trace["source"] = "model"
            return fixed(final), "polished", info
        info["reason"] = why
    return template, "fallback:" + info["reason"], info
