"""任務規劃的方法庫：在共用狀態機迴圈（agent_loop）上挑航線候選。

取代 llm.pick_candidate 的一次性呼叫（使用者 2026-11-06 決定：三個功能統一新迴圈並直接取代舊路徑）。
呼叫方式與回傳格式和 llm.pick_candidate 相同，planner 只要換 import：

    from gcs_demo.agent_methods_mission import pick_candidate

流程（程式決定轉移，模型每次只填一格）：
  S4_PICK  模型從「可直接套用的候選 id」或 HOLD 裡選一個代碼
  → 程式自己寫理由與引用依據（該候選的證據條目 + 風、電池），模型不寫自由文字
  → 回覆不合規格：修正一次；仍不合或呼叫失敗：退回規則選擇
"""
from __future__ import annotations

import hashlib

from gcs_demo import agent_loop as L

VERSION = "mission-sm-1"
SYSTEM_PROMPT = ("你是無人機地面站任務規劃流程中的一個步驟，只負責填一格。"
                 '只回答一個 JSON：{"value":"代碼"}。代碼只能從「只能選」清單裡挑一個，不可自創。'
                 "資訊不足或全部有風險就回 HOLD。")
RULE_REASON = "規則選擇：可行候選中能耗最低且涵蓋所有必要目標。"


def _applicable(c):
    return c.get("feasible", True) and not c.get("requires_battery_swap")


def _zh(c):
    return (f"{c.get('label', '')}（{len(c.get('order') or [])} 個目標，落地剩 {c.get('end_pct')}%，"
            f"約 {c.get('time_min')} 分鐘，{c.get('energy_wh')} Wh）")


class MissionPick:
    def __init__(self, task_zh, candidates, evidence, rule_choice):
        self.task_zh = task_zh
        self.cands = candidates
        self.evidence = evidence
        self.rule_choice = rule_choice
        self.h = None

    def _evidence_for(self, cid):
        """依據由程式找：風與電池（E1/E2）＋提到這個候選的證據條目。"""
        ids = [e["id"] for e in self.evidence if e["id"] in ("E1", "E2")]
        ids += [e["id"] for e in self.evidence
                if e["id"] not in ids and str(e.get("text", "")).startswith(cid + " ")]
        return ids

    def begin(self, h):
        self.h = h
        n = sum(1 for c in self.cands if _applicable(c))
        h.go("S4_PICK", f"規則建議 {self.rule_choice or '無'}，可直接套用的候選 {n} 個")

    def header(self, st):
        lines = ["任務：" + self.task_zh]
        # 只給模型風、電池與事件這類背景；候選數字已在選項說明裡
        lines += [f"{e['id']}：{e['text']}" for e in self.evidence
                  if not any(str(e.get("text", "")).startswith(c["id"] + " ") for c in self.cands)]
        if st["last_observation"]:
            lines.append("觀察：" + st["last_observation"])
        return lines

    def options(self, st):
        allowed = [{"code": c["id"], "zh": _zh(c)} for c in self.cands if _applicable(c)]
        allowed.append({"code": "HOLD", "zh": "資訊不足或全部有風險，先不選"})
        return {"need": "要採用的航線", "allowed": allowed}

    def transition(self, code, h):
        if code == "HOLD":
            h.finish({"decision": "HOLD", "choice_id": "", "reason_zh": "模型判斷資訊不足或全部有風險，先不套用。",
                      "evidence_ids": ["E1", "E2"]}, "llm", "pick: hold")
            return ""
        c = next((x for x in self.cands if x["id"] == code), None)
        if c is None or not _applicable(c):
            return "候選「" + code + "」不可直接套用"
        why = "與規則選擇相同" if code == self.rule_choice else f"與規則選擇 {self.rule_choice or '無'} 不同"
        h.finish({"decision": "SELECT", "choice_id": code, "reason_zh": f"採用 {code} {_zh(c)}；{why}。",
                  "evidence_ids": self._evidence_for(code)}, "llm", "pick")
        return ""

    def rule_decision(self):
        return {"decision": "SELECT", "choice_id": self.rule_choice, "reason_zh": RULE_REASON, "evidence_ids": []}


def pick_candidate(backend, task_zh: str, candidates: list, evidence: list, rule_choice: str,
                   timeout_s: float = None) -> dict:
    """與 llm.pick_candidate 相同介面。回傳 {"choice_id","source":"llm"|"rule","decision","reason_zh",
    "evidence_ids","llm"}；llm 欄位是這次迴圈的紀錄（每次呼叫、軌跡），沒有呼叫時為 None。"""
    lib = MissionPick(task_zh, candidates, evidence, rule_choice)
    sess = L.Session(lib, version=VERSION, system_prompt=SYSTEM_PROMPT, goal=task_zh,
                     model_enabled=bool(backend is not None and backend.available()))
    calls = []
    r = L.run(sess, L.backend_model(backend, timeout_s, calls) if backend is not None else None)
    d = r["decision"]
    source = "llm" if d["source"] == "llm" else "rule"
    reason = d.get("reason_zh", "")
    if source == "rule" and d["model_errors"]:
        reason += "（模型無效：" + d["model_errors"][-1] + "，已退回規則）"
    return {"choice_id": d.get("choice_id", ""), "source": source, "decision": d.get("decision", "SELECT"),
            "reason_zh": reason, "evidence_ids": d.get("evidence_ids", []),
            "llm": None if not calls else _record(calls, r, source)}


def _prompt_hash(system, user):
    """與 llm.prompt_hash 相同公式（不 import llm，方法庫可單獨測）。"""
    return hashlib.sha256((system + "\n---\n" + user).encode("utf-8")).hexdigest()[:16]


def _record(calls, r, source):
    """舊欄位（ok/error/latency_s/backend/model/raw/prompt_hash）照舊給既有紀錄與 smoke 用，另附迴圈軌跡。"""
    prompts = [c["messages"][1]["content"] for c in r["calls"]]
    last = calls[-1]
    return {"ok": source == "llm", "error": None if source == "llm" else (r["decision"]["model_errors"] or [last.get("error")])[-1],
            "latency_s": round(sum(c.get("latency_s") or 0 for c in calls), 3), "backend": last.get("backend"),
            "model": last.get("model"), "raw": last.get("raw"),
            "prompt_hash": _prompt_hash(SYSTEM_PROMPT, prompts[-1]) if prompts else None,
            "loop": VERSION, "engine": L.ENGINE_VERSION, "calls": calls, "model_calls": r["model_calls"],
            "trace": r["trace"], "prompts": prompts}
