"""LLM 說明層：把演算法算好的告警寫成白話，並從可行建議裡挑一個。

照三功能共用的 llm_contract v0：
- 模型只能選演算法給的 candidate id；選到不存在或不可行的 → 退回規則。
- 說明句只能引用存在的 evidence id；引用不存在的整句丟掉。
- 模型掛掉、逾時、輸出壞掉 → 用規則模板，告警照發，不會因為模型失敗而漏報。
告警只呼叫一次模型（說明＋選擇合併成一份 JSON），減少延遲。
"""
from __future__ import annotations

import json

from gcs_demo import llm

SYSTEM_ZH = (
    "你是無人機地面站的告警助理。只能使用使用者提供的事實與數字，不可自行計算或編造數字。"
    "建議只能從 candidates 中選一個 id，且只能選 feasible=true 的，優先選 missed_required（漏掉的必要目標數）為 0 的；都不可行時選 end_pct 最高者。"
    "回覆只輸出 JSON：{\"decision\":\"SELECT\",\"choice_id\":\"C?\",\"reason_zh\":\"一句話理由\","
    "\"evidence_ids\":[\"E?\"],\"summary_zh\":\"給操作員的兩句白話說明\"}。"
)

# gcs_demo.llm 的極簡 schema 格式（只檢查必要欄位與型別）
SCHEMA = {"required": {"decision": "str", "choice_id": "str", "reason_zh": "str",
                       "evidence_ids": "list", "summary_zh": "str"}}


def get_backend():
    """三功能共用的可抽換後端（GCS_LLM_BACKEND=openai|ollama|none）。"""
    return llm.get_backend()


# ---------------- 規則模板（模型失敗時） ----------------
def rule_text(ev: dict) -> dict:
    cands = {c["id"]: c for c in ev.get("candidates", [])}
    pick = cands.get(ev.get("rule_choice") or "")
    s = f"{ev['title']}：{ev['value']}。"
    if pick:
        tail = f"（預估落地 {pick['end_pct']:.0f}%）" if "end_pct" in pick else ""
        s += f"建議「{pick['label']}」{tail}。"
    return {"decision": "SELECT" if pick else "HOLD", "choice_id": pick["id"] if pick else None,
            "reason_zh": "規則：可行選項中保留最多任務進度。", "evidence_ids": [e["id"] for e in ev.get("evidence", [])][:2],
            "summary_zh": s}


# ---------------- 主函式 ----------------
def explain(ev: dict, backend=None, timeout_s=60) -> dict:
    """回傳 {"text": {...}, "source": "llm"|"rule", "fallback_reason", "llm": 記錄}。"""
    backend = backend or get_backend()
    facts = {
        "alert": {"title": ev["title"], "value": ev["value"], "lead_s": ev.get("lead_s")},
        "evidence": ev.get("evidence", []),
        "candidates": [{k: c.get(k) for k in ("id", "label", "end_pct", "completion_pct", "missed_required", "feasible") if k in c}
                       for c in ev.get("candidates", [])],
    }
    user = json.dumps(facts, ensure_ascii=False)
    res = backend.complete_json(SYSTEM_ZH, user, SCHEMA, timeout_s=timeout_s)
    log = {"backend": getattr(backend, "name", "?"), "model": getattr(backend, "model", None),
           "prompt_sha256": llm.prompt_hash(SYSTEM_ZH, user),
           "ok": res["ok"], "latency_s": round(res["latency_s"], 2), "error": res["error"], "raw": (res.get("raw") or "")[:800]}
    rule = rule_text(ev)
    if not res["ok"]:
        return {"text": rule, "source": "rule", "fallback_reason": res["error"], "llm": log}

    d = res["data"] or {}
    reason = validate(d, ev)
    if reason:
        return {"text": rule, "source": "rule", "fallback_reason": reason, "llm": log}
    ev_ids = {e["id"] for e in ev.get("evidence", [])}
    d["evidence_ids"] = [x for x in d.get("evidence_ids", []) if x in ev_ids]
    d["rule_agrees"] = d["choice_id"] == ev.get("rule_choice")
    return {"text": d, "source": "llm", "fallback_reason": None, "llm": log}


def validate(d: dict, ev: dict) -> str | None:
    """模型輸出不合規就回傳原因（退回規則），合規回 None。"""
    for k in ("choice_id", "summary_zh"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            return f"缺欄位 {k}"
    cands = {c["id"]: c for c in ev.get("candidates", [])}
    c = cands.get(d["choice_id"])
    if c is None:
        return f"choice_id {d['choice_id']} 不在候選清單"
    any_ok = any(x.get("feasible") for x in cands.values())
    if any_ok and not c.get("feasible"):
        return f"選了不可行的 {d['choice_id']}"
    ev_ids = {e["id"] for e in ev.get("evidence", [])}
    if d.get("evidence_ids") and not set(d["evidence_ids"]) & ev_ids:
        return "引用的 evidence 全部不存在"
    # 模型句子裡不准出現事實裡沒有的百分比數字
    allowed = json.dumps(ev, ensure_ascii=False)
    import re
    for num in re.findall(r"\d+(?:\.\d+)?(?=\s*%)", d["summary_zh"]):
        if num not in allowed and str(round(float(num))) not in allowed:
            return f"說明出現事實裡沒有的數字 {num}%"
    return None
