"""LLM 說明層：只引用已提供的事實與可行候選；失敗時仍輸出規則說明。

HOLD 的 choice_id 僅為緊急備選供顯示，不是可套用的飛行操作。
"""
from __future__ import annotations

import json
import math
import re

from gcs_demo import llm

SYSTEM_ZH = (
    "你是無人機地面站的告警助理。只能使用提供的事實與數字，不可自行計算或編造數字。"
    "有 feasible=true 的候選時，decision 必須 SELECT 且只選可行候選，優先保留必要目標與進度。"
    "全部不可行時 decision 必須 HOLD，choice_id 只標示緊急備選，不可說成已核可的操作。"
    "evidence_ids 必須非空且每一項都存在；summary_zh 和 reason_zh 的每個數字（含百分比）"
    "都須逐字對應 facts 裡的完整數字 token，不可截取或四捨五入。"
    "回覆只輸出 JSON：{\"decision\":\"SELECT或HOLD\",\"choice_id\":\"C?\","
    "\"reason_zh\":\"一句話理由\",\"evidence_ids\":[\"E?\"],\"summary_zh\":\"兩句白話說明\"}。"
    "一律使用台灣繁體中文，不寫出內部欄位名稱。"
)

SCHEMA = {"required": {"decision": "str", "choice_id": "str", "reason_zh": "str",
                       "evidence_ids": "list", "summary_zh": "str"}}


def get_backend():
    return llm.get_backend()


def _facts(ev):
    """模型實際可見的事實，也是 validate 的唯一數字白名單來源。"""
    return {
        "alert": {"title": ev["title"], "value": ev["value"], "lead_s": ev.get("lead_s")},
        "rule_decision": "SELECT" if any(c.get("feasible") is True for c in ev.get("candidates", [])) else "HOLD",
        "evidence": ev.get("evidence", []),
        "candidates": [{k: c[k] for k in ("id", "label", "end_pct", "completion_pct", "missed_required",
                                         "energy_feasible", "operational_status", "feasible") if k in c}
                       for c in ev.get("candidates", [])],
    }


def rule_text(ev: dict) -> dict:
    cands = {c["id"]: c for c in ev.get("candidates", [])}
    feasible = [c for c in cands.values() if c.get("feasible") is True]
    pick = cands.get(ev.get("rule_choice"))
    decision = "SELECT" if feasible else "HOLD"
    if feasible and (pick is None or pick.get("feasible") is not True):
        pick = feasible[0]
    s = f"{ev['title']}：{ev['value']}。"
    if decision == "HOLD":
        s += "沒有能保住保留電量且可確認可行的選項，請人工判斷。"
        if pick:
            s += f"緊急備選「{pick['label']}」僅供顯示，尚未核可執行。"
            if pick.get("operational_status") == "unknown":
                s += "地面作業條件未知。"
        reason = "規則：候選全部不可行，暫停選擇並請人工判斷。"
    else:
        tail = f"（預估落地 {pick['end_pct']:.1f}%）" if "end_pct" in pick else ""
        s += f"建議「{pick['label']}」{tail}。"
        reason = "規則：從可行候選中選擇；飛行操作仍須操作員確認。"
    return {"decision": decision, "choice_id": pick["id"] if pick else None, "reason_zh": reason,
            "evidence_ids": [e["id"] for e in ev.get("evidence", [])][:2], "summary_zh": s}


def explain(ev: dict, backend=None, timeout_s=60) -> dict:
    """先建規則結果；後端建立、呼叫、解碼、驗證例外都退回規則。"""
    rule = rule_text(ev)
    log = {"backend": "?", "model": None, "prompt_sha256": None, "ok": False,
           "latency_s": None, "error": None, "raw": ""}

    def fallback(reason):
        return {"text": rule, "source": "rule", "fallback_reason": reason, "llm": log}

    try:
        if not ev.get("candidates"):
            return fallback("沒有候選，保留 HOLD")
        user = json.dumps(_facts(ev), ensure_ascii=False, allow_nan=False)
        log["prompt_sha256"] = llm.prompt_hash(SYSTEM_ZH, user)
        if backend is None:
            backend = get_backend()
        log.update(backend=getattr(backend, "name", "?"), model=getattr(backend, "model", None))
        res = backend.complete_json(SYSTEM_ZH, user, SCHEMA, timeout_s=timeout_s)
        latency = float(res["latency_s"])
        if not math.isfinite(latency):
            raise ValueError("後端 latency_s 非有限數值")
        log.update(ok=res["ok"], latency_s=round(latency, 2), error=res["error"],
                   raw=(res.get("raw") or "")[:800])
        if res["ok"] is not True:
            return fallback(res["error"] or "後端未成功")
        data = res["data"]
        if isinstance(data, str):
            data = json.loads(data)
        reason = validate(data, ev)
        if reason:
            return fallback(reason)
        d = dict(data)
        d["rule_agrees"] = (d["decision"], d["choice_id"]) == (rule["decision"], rule["choice_id"])
        return {"text": d, "source": "llm", "fallback_reason": None, "llm": log}
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        log.update(ok=False, error=reason)
        return fallback(reason)


_FIELD_NAMES = ("end_pct", "end_pct_raw", "missed_required", "feasible", "energy_feasible",
                "completion_pct", "choice_id", "evidence_ids", "operational_status", "rule_decision")
_SIMPLIFIED = set("电线这为时还应发达变项预备点务议机险问题实际们没过")
# 完整數字 token：保留正負號、小數位與 %；5% 不會被 15% 或 5.0% 放行。
_NUMBER = re.compile(r"[-+−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?(?:\s*[%％])?")


def _number_tokens(text):
    return {re.sub(r"\s+(?=[%％])", "", m.group(0)) for m in _NUMBER.finditer(text)}


def _fact_numbers(value):
    if isinstance(value, dict):
        # E1/C1 等識別碼不是可引用的量測數字；WP13 等 label 中數字仍是事實。
        return set().union(*(_fact_numbers(v) for k, v in value.items() if k != "id"))
    if isinstance(value, list):
        return set().union(*(_fact_numbers(v) for v in value))
    if isinstance(value, str):
        return _number_tokens(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number_tokens(json.dumps(value, allow_nan=False))
    return set()


def validate(d: dict, ev: dict) -> str | None:
    if not isinstance(d, dict):
        return "模型輸出必須是物件"
    if d.get("decision") not in ("SELECT", "HOLD"):
        return "decision 必須為 SELECT 或 HOLD"
    for k in ("choice_id", "summary_zh", "reason_zh"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            return f"缺欄位 {k}"
    cands = {c["id"]: c for c in ev.get("candidates", [])}
    c = cands.get(d["choice_id"])
    if c is None:
        return f"choice_id {d['choice_id']} 不在候選清單"
    any_ok = any(x.get("feasible") is True for x in cands.values())
    if any_ok and d["decision"] != "SELECT":
        return "有可行選項時不得 HOLD"
    if not any_ok and d["decision"] != "HOLD":
        return "全部不可行時必須 HOLD"
    if any_ok and c.get("feasible") is not True:
        return f"選了不可行的 {d['choice_id']}"
    ids = d.get("evidence_ids")
    ev_ids = {e["id"] for e in ev.get("evidence", [])}
    if (not isinstance(ids, list) or not ids
            or any(not isinstance(x, str) or x not in ev_ids for x in ids)):
        return "evidence_ids 必須非空、全為字串且全部存在"
    text = d["summary_zh"] + "\n" + d["reason_zh"]
    if any(f in text for f in _FIELD_NAMES):
        return "說明寫出內部欄位名稱"
    if sum(ch in _SIMPLIFIED for ch in text) >= 2:
        return "說明用了簡體字"
    allowed = _fact_numbers(_facts(ev))
    for num in sorted(_number_tokens(text)):
        if num not in allowed:
            return f"說明出現事實裡沒有的數字 {num}"
    return None
