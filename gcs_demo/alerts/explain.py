"""LLM 說明層：範本句＋模型選格（slot_explain）。模型只選處置、依據與建議句的代碼，
句子由程式寫，再經 v5 驗證器；失敗時仍輸出規則說明。無允許選項時選擇為 null，
緊急備選只在規則文字顯示。
"""
from __future__ import annotations

import json
import math
import os
from copy import deepcopy

from .core import contract
from .display import landing_pct_text

from gcs_demo import llm
from .slot_explain import (ADVICE, GENERIC_ADVICE, LEGACY_GROUP, SEVERITY_ZH, SYSTEM_PROMPT,
                           AlertSlots, run as slot_run)

# MVP（契約 v0.3）：告警預設經共用閘道接模型；設 GCS_LLM_BACKEND 時照環境變數（none 可關閉）
ALERTS_GATEWAY_URL = "http://127.0.0.1:8090/f/alerts/v1"
ALERTS_MODEL = "gemma4:e2b"
ALERTS_TIMEOUT_S = 35.0          # 閘道 alerts 預算 30 秒（含排隊），多留 5 秒給連線


def get_backend():
    if os.environ.get("GCS_LLM_BACKEND"):
        return llm.get_backend()
    return llm.OpenAICompatBackend(os.environ.get("GCS_LLM_URL") or ALERTS_GATEWAY_URL,
                                   os.environ.get("GCS_LLM_MODEL") or ALERTS_MODEL)


def event_version(ev):
    """Prefer the v5 engine version; transitional identity never asserts engine sequencing."""
    return ev.get("alert_version", f"{ev.get('key')}|{ev.get('t')}|{ev.get('type')}")


def _facts(ev):
    """No inference of allowed IDs from feasibility or numeric semantics from text.

    Legacy unstructured evidence is retained as received and fails core validation
    until predict supplies v5 rows. That failure retains the immediate rule text.
    """
    return {"alert_version": event_version(ev), "level": ev.get("severity"),
            "title": ev.get("title"), "allowed_ids": deepcopy(ev.get("allowed_ids", [])),
            "evidence": deepcopy(ev.get("evidence", []))}


def current_state(ev):
    return {"active": ev.get("active", ev.get("type") in ("raise", "update")),
            "alert_version": event_version(ev),
            "feasible_ids": [c["id"] for c in ev.get("candidates", [])
                             if c.get("feasible") is True]}


def _display(d):
    """Compatibility display fields are derived locally, never accepted from the model."""
    out = dict(d)
    out.update(decision="SELECT" if d["selected_id"] is not None else "HOLD",
               choice_id=d["selected_id"], summary_zh="".join(d["sentences"]),
               reason_zh=d["sentences"][1])
    return out


def rule_text(ev: dict) -> dict:
    cands = {c["id"]: c for c in ev.get("candidates", [])}
    feasible = [c for c in cands.values() if c.get("feasible") is True]
    pick = cands.get(ev.get("rule_choice"))
    decision = "SELECT" if feasible and ev.get("rule_decision") != "HOLD" else "HOLD"
    if decision == "SELECT" and (pick is None or pick.get("feasible") is not True):
        pick = feasible[0]
    s = f"{ev['title']}：{ev['value']}。"
    if decision == "HOLD":
        s += ("建議尚待穩定確認，請人工決策。" if feasible else
              "無符合條件方案，請人工決策。")
        if pick and not feasible:
            s += f"緊急備選「{pick['label']}」僅供顯示，尚未核可執行。"
            if pick.get("operational_status") == "unknown":
                s += "地面作業條件未知。"
        reason = ("規則：建議尚待穩定確認，暫停選擇並請人工判斷。" if feasible else
                  "規則：候選全部不可行，暫停選擇並請人工判斷。")
    else:
        tail = f"（預估落地 {landing_pct_text(pick.get('end_pct_raw', pick['end_pct']))}）" if "end_pct" in pick else ""
        s += f"建議「{pick['label']}」{tail}。"
        reason = "規則：從可行候選中選擇；飛行操作仍須操作員確認。"
    selected = pick["id"] if pick and decision == "SELECT" else None
    return {"decision": decision, "choice_id": selected, "reason_zh": reason,
            "alert_version": event_version(ev), "selected_id": selected,
            "sentences": [f"{ev['title']}：{ev['value']}。", reason],
            "evidence_ids": [e["id"] for e in ev.get("evidence", [])][:2], "summary_zh": s}


def _slots(ev, rule):
    """範本句＋模型選格的方法庫（slot_explain）。依據只用 v5 綁定欄位齊全的列。"""
    facts = _facts(ev)
    state = current_state(ev)
    allowed = [x for x in facts["allowed_ids"] if x in state["feasible_ids"]]
    labels = {c["id"]: c.get("label", c["id"]) for c in ev.get("candidates", [])}
    group = LEGACY_GROUP.get(ev.get("key"))
    return AlertSlots(level_zh=SEVERITY_ZH.get(ev.get("severity"), "注意"), title=ev.get("title") or "告警",
                      evidence=[e for e in facts["evidence"] if isinstance(e, dict) and "metric" in e],
                      allowed=allowed, labels=labels, advice=ADVICE.get(group, GENERIC_ADVICE),
                      check=lambda out: validate(out, ev), alert_version=facts["alert_version"], rule=rule)


def explain(ev: dict, backend=None, timeout_s=ALERTS_TIMEOUT_S) -> dict:
    """先建規則結果；模型只在共用迴圈裡選格，句子由程式寫。任何失敗都退回規則。"""
    rule = rule_text(ev)
    log = {"backend": "?", "model": None, "prompt_sha256": None, "ok": False,
           "latency_s": None, "error": None, "raw": ""}

    def fallback(reason):
        return {"text": rule, "source": "rule", "fallback_reason": reason, "llm": log}

    try:
        if not ev.get("candidates"):
            return fallback("沒有候選，保留 HOLD")
        if backend is None:
            backend = get_backend()
        log.update(backend=getattr(backend, "name", "?"), model=getattr(backend, "model", None))
        data, loop = slot_run(_slots(ev, rule), backend, timeout_s)
        log.update(loop)
        if loop["prompts"]:
            log["prompt_sha256"] = llm.prompt_hash(SYSTEM_PROMPT, loop["prompts"][-1])
        if data is None:
            return fallback(loop["error"] or "模型選格失敗")
        reason = validate(data, ev)
        if reason:
            return fallback(reason)
        log["ok"] = True
        d = _display(data)
        d["rule_agrees"] = d["selected_id"] == rule["selected_id"]
        return {"text": d, "source": "llm", "fallback_reason": None, "llm": log}
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        log.update(ok=False, error=reason)
        return fallback(reason)


def validate(d: dict, ev: dict, current=None) -> str | None:
    """One validator for both callers; current may be a fresh state or zero-arg getter.

    With no getter this validates the supplied event only. Application callers must
    use their current event/state, not the original model request snapshot.
    """
    state = current() if callable(current) else current
    return contract.validate(d, _facts(ev), current_state(ev) if state is None else state)
