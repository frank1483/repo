"""ADR-0002 M2 有界 Agent 迴圈控制器（桌面參考實作；M2 只用假模型驗證）。

依「演算法說明 v1：有界 Agent 迴圈控制器」（adr0002_algo/迴圈控制器_演算法說明_v1.md，使用者 2026-11-17 08:57「是」）。
- 每一步用 agent_loop.Session（原檔不改）讓模型只從「這一步合法的動作代碼」選一個；修正一次；不行就退回規則。
- 程式負責：Gate 第 1 層、方向上限（K_max＝3）、目標建立、前置條件、參數（H-10）、依賴（唯一合格成果才綁定）、
  預算帳本（所有模型呼叫都要先保留額度）、停止條件與終態判定、追問與接續、模板回覆。
- 沒有任何飛控動作；PROPOSE_HOME_ROUTE 只開確認視窗。
數值都是測試用值。
"""
from __future__ import annotations

import copy
import hashlib
import json

from . import agent_loop as al
from .gate_l1 import gate
from .planner_t3 import _canonical

TEST_VALUES = {"per_sentence_calls": 12, "per_task_calls": 24, "clarify_rounds": 3, "steps_max": 10, "k_max": 3}
KINDS = ("plan", "ui", "qa", "report", "chat", "manual")   # manual：使用者 11/18 選 B，向量檢索進 M4
KIND_ZH = {"plan": "任務規劃", "ui": "介面", "qa": "問答", "report": "報告", "chat": "閒聊", "manual": "手冊查詢"}
KEYWORDS = {"plan": ["巡檢", "航線", "規劃", "覆蓋"], "ui": ["首頁", "顯示在", "放到", "畫面"],
            "qa": ["是什麼", "如何", "為什麼", "多少", "怎麼"], "report": ["報告", "摘要"],
            "manual": ["手冊", "說明書", "文件", "PX4", "QGC", "px4", "qgc"]}
ACTION_ZH = {"QUERY_AREA": "查詢巡檢區域", "GEN_COVERAGE": "生成覆蓋航點", "VERIFY_PREVIEW": "預覽驗算",
             "PROPOSE_HOME_ROUTE": "開啟套用到首頁的確認視窗", "QA_LOOKUP": "查詢資料回答",
             "REPORT_DRAFT": "產生報告草稿", "MANUAL_SEARCH": "查手冊（附出處）", "ASK_USER": "向使用者追問",
             "FINISH": "結束這個方向",
             "HOLD": "停止（安全）"}


def _h(o):
    return hashlib.sha256(_canonical(o).encode("ascii")).hexdigest()[:16]


class Ledger:
    """兩層預算：每句一份、任務累計；追問輪數另計。所有模型呼叫送出前先 reserve()。"""

    def __init__(self, per_sentence=None, per_task=None, clarify=None):
        self.per_sentence = TEST_VALUES["per_sentence_calls"] if per_sentence is None else per_sentence
        self.per_task = TEST_VALUES["per_task_calls"] if per_task is None else per_task
        self.clarify_max = clarify if clarify is not None else TEST_VALUES["clarify_rounds"]
        self.sentence_used = 0
        self.task_used = 0
        self.clarify_used = 0
        self.log = []

    def new_sentence(self):
        self.sentence_used = 0

    def reserve(self, purpose):
        ok = self.sentence_used < self.per_sentence and self.task_used < self.per_task
        self.log.append({"purpose": purpose, "granted": ok})
        if ok:
            self.sentence_used += 1
            self.task_used += 1
        return ok


class _StepLib:
    """把「選一個動作」包成 agent_loop 的方法庫。"""

    def __init__(self, header_lines, allowed, rule_code):
        self.lines = header_lines
        self.allowed_codes = allowed
        self.rule_code = rule_code

    def begin(self, h):
        h.go("STEP")

    def options(self, st):
        return {"need": "下一個動作", "allowed": [{"code": c, "zh": ACTION_ZH[c]} for c in self.allowed_codes]}

    def header(self, st):
        return list(self.lines)

    def transition(self, code, h):
        h.finish({"decision": code, "steps": []}, "model")
        return ""

    def rule_decision(self):
        return {"decision": self.rule_code, "steps": []}


class Controller:
    def __init__(self, tools, model=None, ledger_cfg=None, steps_max=None, k_max=None, alert_active=None):
        """tools：query_area/gen_coverage/verify_preview/propose_home_route/qa_lookup/report_draft。
        model(call) → 原始回覆文字（假模型或閘道）；None 表示不用模型（全部規則）。"""
        self.tools = tools
        self.model = model
        self.ledger_cfg = ledger_cfg or {}
        self.steps_max = steps_max or TEST_VALUES["steps_max"]
        self.k_max = k_max or TEST_VALUES["k_max"]
        self.tasks = {}
        self.n = 0
        self.alert_active = alert_active      # M3：固定告警狀態；有告警就停在步間

    # ---------- 模型呼叫（經帳本） ----------
    def _ask(self, task, purpose, header, allowed, rule_code):
        lib = _StepLib(header, allowed, rule_code)
        sess = al.Session(lib, max_calls=2, system_prompt="你是地面站助理。只回 JSON。", goal=task["text"],
                          model_enabled=self.model is not None)
        while True:
            step = sess.next()
            if step["type"] == "done":
                d = step["decision"]
                # M4 v2（Codex 0399 第 3 點）：保存每一步引擎 trace，供 T1 嚴格／寬鬆／無效統計
                task.setdefault("traces", []).append({"purpose": purpose, "source": d["source"],
                                                      "decision": d["decision"], "trace": step["trace"],
                                                      "model_calls": step["model_calls"]})
                return d["decision"], ("model" if d["source"] == "model" else "rule")
            if not task["ledger"].reserve(purpose):
                sess._rule_fallback("預算用完", "rule_budget")
                continue
            try:
                reply = self.model(step["call"])
            except Exception as exc:  # noqa: BLE001 - 傳輸錯誤視為一次失敗回答
                sess.fail(str(exc))
                continue
            if reply is None:
                sess.fail("no reply")
            else:
                sess.answer(reply)

    # ---------- 入口 ----------
    def request(self, text):
        g = gate(text)
        if g["status"] != "PASS":
            return {"status": g["status"], "reply_zh": g.get("message_zh", "無法處理這句話"), "task_id": None}
        self.n += 1
        tid = f"task-{self.n}"
        task = {"id": tid, "text": text, "status": "ACTIVE", "ledger": Ledger(**self.ledger_cfg), "directions": [],
                "goals": [], "artifacts": {}, "questions": [], "steps": [], "notes": []}
        self.tasks[tid] = task
        kinds = self._directions(task)
        if len(kinds) > self.k_max:
            task["status"] = "PARKED"
            task["questions"].append({"field": "task_scope", "zh": f"這句話包含 {len(kinds)} 件事，請先選最多 "
                                                                 f"{self.k_max} 件（{'、'.join(KIND_ZH[k] for k in kinds)}）"})
            return self._reply(task)
        self._build(task, kinds)
        if "bind_task" in self.tools:
            self.tools["bind_task"](task)
        return self._run(task)

    def continue_task(self, task_id):
        """告警解除後接續（不重設步數與預算）。"""
        task = self.tasks[task_id]
        if task.get("paused_by_alert"):
            task["paused_by_alert"] = False
            task["status"] = "ACTIVE"
        return self._run(task)

    def cancel(self, task_id):
        """使用者明確取消（按鈕）。進行中的模型回覆若晚到，只記錄、不採用。"""
        task = self.tasks[task_id]
        task["cancelled"] = True
        task["status"] = "CANCELLED"
        return self._reply(task)

    def resume(self, task_id, answers):
        task = self.tasks[task_id]
        task["ledger"].new_sentence()
        task["ledger"].clarify_used += 1
        for a in answers:
            if a["field"] == "cancel_confirm":
                task["status"] = "CANCELLED" if a["value"] is True else task.get("pre_cancel", "ACTIVE")
                task["questions"] = []
                return self._reply(task)
            if a["field"] == "boundary":
                task["artifacts"]["area_record"] = {"kind": "area_record", "ref": a["value"], "verdict": "ok",
                                                   "source": "user_drawn"}
            if a["field"] == "area_choice":
                task["artifacts"]["area_record"] = {"kind": "area_record", "ref": a["value"], "verdict": "ok",
                                                   "source": "user_choice"}
        task["questions"] = []
        task["status"] = "ACTIVE"
        for d in task["directions"]:
            if d["status"] == "NEEDS_USER":
                d["status"] = "RUNNING"
        return self._run(task)

    def resume_text(self, task_id, text):
        """自由文字回覆：先過 Gate，再用 1 次模型判斷 RESUME／NEW_REQUEST／CANCEL；CANCEL 先請使用者確認。"""
        task = self.tasks[task_id]
        g = gate(text)
        if g["status"] != "PASS":
            return {"status": g["status"], "reply_zh": g.get("message_zh", ""), "task_id": task_id}
        task["ledger"].new_sentence()
        intent, _ = self._ask_resume(task, text)
        if intent == "CANCEL":
            task["pre_cancel"] = task["status"]
            task["status"] = "PARKED"
            task["questions"] = [{"field": "cancel_confirm", "zh": "要取消這個任務嗎？"}]
            return self._reply(task)
        if intent == "NEW_REQUEST":
            return self.request(text)
        return self._run(task)

    def _ask_resume(self, task, text):
        lib = _StepLib(["使用者的回覆：" + text], [], "RESUME")
        lib.options = lambda st: {"need": "回覆的意圖", "allowed": [{"code": c, "zh": c} for c in
                                                              ("RESUME", "NEW_REQUEST", "CANCEL")]}
        sess = al.Session(lib, max_calls=2, goal=task["text"], model_enabled=self.model is not None)
        while True:
            step = sess.next()
            if step["type"] == "done":
                return step["decision"]["decision"], step["decision"]["source"]
            if not task["ledger"].reserve("resume"):
                sess._rule_fallback("預算用完", "rule_budget")
                continue
            try:
                reply = self.model(step["call"])
            except Exception as exc:  # noqa: BLE001
                sess.fail(str(exc))
                continue
            sess.answer(reply) if reply is not None else sess.fail("no reply")

    # ---------- 方向與目標 ----------
    def _directions(self, task):
        rule = [k for k in KINDS if any(w in task["text"] for w in KEYWORDS.get(k, []))] or ["chat"]
        if self.model is None or not task["ledger"].reserve("directions"):
            return rule
        call = {"messages": [{"role": "system", "content": "只回 JSON"},
                             {"role": "user", "content": "句子：" + task["text"] + "\n可選：" + "｜".join(KINDS) +
                              '\n只輸出 JSON：{"kinds":["..."]}'}]}
        try:
            obj = al.default_extract(self.model(call))
        except Exception:  # noqa: BLE001
            obj = None
        if not isinstance(obj, dict) or list(obj) != ["kinds"] or not isinstance(obj["kinds"], list) or \
                not obj["kinds"] or any(k not in KINDS for k in obj["kinds"]):
            task["notes"].append("方向判斷無效，改用關鍵字表")
            return rule
        kinds = list(dict.fromkeys(obj["kinds"]))
        unmapped = [k for k in kinds if k not in rule and k not in ("chat",)]
        for k in unmapped:
            task["notes"].append(f"模型判斷有「{KIND_ZH[k]}」但程式對應不到具體目標，標 UNMAPPED")
        return [k for k in kinds if k not in unmapped] or rule

    def _build(self, task, kinds):
        for k in kinds:
            task["directions"].append({"id": f"{task['id']}-{k}", "kind": k, "status": "PENDING", "steps": 0,
                                       "last_sig": None})
            req = {"plan": ["route_preview"], "ui": ["apply_proposal"], "qa": ["qa_claims"],
                   "report": ["report_draft"], "chat": [], "manual": ["manual_claims"]}[k]
            task["goals"].append({"requirement_id": f"R-{k}", "goal_id": f"G-{k}-1", "direction": k,
                                  "required": req, "predicate": {"plan": "pass", "manual": "ok"}.get(k, "exists")})

    # ---------- 合法動作（前置條件由程式判定） ----------
    def _allowed(self, task, d):
        A = task["artifacts"]
        k = d["kind"]
        acts = []
        if k == "plan":
            if "area_record" not in A:
                acts.append("QUERY_AREA")
            elif "coverage_route" not in A:
                acts.append("GEN_COVERAGE")
            elif "route_preview" not in A:
                acts.append("VERIFY_PREVIEW")
        elif k == "ui":
            rp = A.get("route_preview")
            if rp and rp.get("verdict") == "pass" and "apply_proposal" not in A:
                acts.append("PROPOSE_HOME_ROUTE")
        elif k == "qa" and ("qa_claims" not in A or A["qa_claims"]["verdict"] == "none"):
            acts.append("QA_LOOKUP")
        elif k == "report" and "report_draft" not in A:
            acts.append("REPORT_DRAFT")
        elif k == "manual" and "manual_claims" not in A:
            acts.append("MANUAL_SEARCH")
        return acts + ["FINISH", "HOLD"]

    def _goals_met(self, task, d):
        A = task["artifacts"]
        for g in task["goals"]:
            if g["direction"] != d["kind"]:
                continue
            for slot in g["required"]:
                a = A.get(slot)
                if a is None or (g["predicate"] in ("pass", "ok") and a.get("verdict") != g["predicate"]):
                    return False
        return True

    def _waiting(self, task, d):
        """ui 方向需要合格預覽：plan 方向還可能產出時等待；plan 已結束卻沒有合格預覽就是未完成。"""
        if d["kind"] != "ui":
            return None
        rp = task["artifacts"].get("route_preview")
        if rp and rp.get("verdict") == "pass":
            return None
        plan = next((x for x in task["directions"] if x["kind"] == "plan"), None)
        if plan is None:
            return "UPSTREAM_NO_MATCH"
        if plan["status"] in ("DONE", "INCOMPLETE", "FAILED_SAFE", "CANCELLED", "EXPIRED"):
            return "UPSTREAM_NO_MATCH"
        if plan["status"] == "NEEDS_USER":
            return "NEEDS_USER"
        return "WAIT"

    # ---------- 執行 ----------
    def _exec(self, task, d, code):
        A = task["artifacts"]
        T = self.tools
        if code == "QUERY_AREA":
            r = T["query_area"](task["text"])
            if r["status"] == "ONE":
                A["area_record"] = {"kind": "area_record", "ref": r["candidates"][0], "verdict": "ok", "source": "table"}
            elif r["status"] == "MANY":
                d["status"] = "NEEDS_USER"
                task["questions"].append({"field": "area_choice", "zh": "要用哪個區域？",
                                          "options": r["candidates"][:5]})
            else:
                d["status"] = "NEEDS_USER"
                task["questions"].append({"field": "boundary", "zh": "找不到這個區域，請在地圖上框選"})
            return r
        if code == "GEN_COVERAGE":
            r = T["gen_coverage"](A["area_record"]["ref"])
            if r["status"] == "OK":
                A["coverage_route"] = {"kind": "coverage_route", "ref": r["route_ref"], "verdict": "ok"}
            else:
                d["status"] = "INCOMPLETE"
                d["reason"] = r["status"]
            return r
        if code == "VERIFY_PREVIEW":
            r = T["verify_preview"](A["coverage_route"]["ref"])
            A["route_preview"] = {"kind": "route_preview", "ref": r["preview_ref"], "verdict": r["result"],
                                  "est_end_pct": r.get("est_end_pct"), "reasons": r.get("reasons", [])}
            return r
        if code == "PROPOSE_HOME_ROUTE":
            r = T["propose_home_route"](A["route_preview"]["ref"])
            A["apply_proposal"] = {"kind": "apply_proposal", "ref": r["shown_hash"], "verdict": "ok"}
            return r
        if code == "QA_LOOKUP":
            r = T["qa_lookup"](task["text"])
            A["qa_claims"] = {"kind": "qa_claims", "ref": r.get("ref"), "verdict": "ok" if r.get("claims") else "none",
                              "claims": r.get("claims", [])}
            return r
        if code == "MANUAL_SEARCH":
            r = T["manual_search"](task["text"]) if "manual_search" in T else {"status": "NOT_LOADED", "results": []}
            A["manual_claims"] = {"kind": "manual_claims", "ref": None,
                                  "verdict": "ok" if r.get("results") else ("not_loaded" if r.get("status") == "NOT_LOADED"
                                                                            else "not_found"),
                                  "degraded": r.get("degraded"),
                                  "refs": [{k2: x[k2] for k2 in ("manual", "path", "heading_path", "version", "chunk_id")}
                                           for x in r.get("results", [])]}
            return {"status": r.get("status"), "n": len(r.get("results", []))}
        if code == "REPORT_DRAFT":
            r = T["report_draft"](sorted(A))
            A["report_draft"] = {"kind": "report_draft", "ref": r.get("ref"), "verdict": "ok"}
            return r
        return None

    def _rule_next(self, task, d, allowed):
        work = [a for a in allowed if a not in ("FINISH", "HOLD")]
        return work[0] if work else "FINISH"

    def _step(self, task, d):
        allowed = self._allowed(task, d)
        header = ["句子：" + task["text"], f"方向：{KIND_ZH[d['kind']]}",
                  "已有成果：" + ("、".join(sorted(task["artifacts"])) or "無"), f"剩餘步數：{self.steps_max - d['steps']}"]
        code, source = self._ask(task, "step:" + d["kind"], header, allowed, self._rule_next(task, d, allowed))
        if task.get("cancelled"):
            task["notes"].append(f"取消後才回來的回覆（{code}）只記錄、不採用")
            task["steps"].append({"direction": d["kind"], "action": code, "source": source, "late": True})
            return
        d["steps"] += 1
        before = _h(sorted(task["artifacts"].items()))
        if code == "HOLD":
            d["status"] = "FAILED_SAFE"
            result = None
        elif code == "FINISH":
            d["status"] = "DONE" if self._goals_met(task, d) else "INCOMPLETE"
            result = None
        else:
            result = self._exec(task, d, code)
        sig = (code, d["kind"], before, _h({"r": result}))
        task["steps"].append({"direction": d["kind"], "action": code, "source": source, "input": before,
                              "result": sig[3]})
        if d["status"] == "RUNNING" and d["last_sig"] == sig:
            d["status"] = "INCOMPLETE"
            d["reason"] = "REPEATED_ACTION"
        d["last_sig"] = sig
        if d["status"] == "RUNNING" and d["steps"] >= self.steps_max:
            d["status"] = "INCOMPLETE"
            d["reason"] = "STEPS_MAX"

    def _run(self, task):
        for d in task["directions"]:
            if d["status"] == "PENDING":
                d["status"] = "RUNNING"
        progressed = True
        while progressed:
            progressed = False
            for d in task["directions"]:                     # 輪流：每個方向一次一步
                if d["status"] == "WAITING_DEP":
                    d["status"] = "RUNNING"
                if d["status"] != "RUNNING":
                    continue
                w = self._waiting(task, d)
                if w == "WAIT":
                    d["status"] = "WAITING_DEP"
                    continue
                if w == "NEEDS_USER":
                    d["status"] = "NEEDS_USER"
                    continue
                if w == "UPSTREAM_NO_MATCH":
                    d["status"] = "INCOMPLETE"
                    d["reason"] = "UPSTREAM_NO_MATCH"
                    continue
                if task.get("cancelled"):
                    return self._reply(task)
                if self.alert_active is not None and self.alert_active():
                    task["paused_by_alert"] = True
                    task["status"] = "PARKED"
                    task["notes"].append("告警中，迴圈停在步與步之間")
                    return self._reply(task)
                if task["ledger"].task_used >= task["ledger"].per_task and self.model is not None:
                    task["notes"].append("任務預算用完，其餘改由規則完成")
                self._step(task, d)
                progressed = True
            if not progressed and any(d["status"] == "WAITING_DEP" for d in task["directions"]):
                # 上游已無可推進者：重新判定等待者
                for d in task["directions"]:
                    if d["status"] == "WAITING_DEP":
                        d["status"] = "RUNNING"
                        w = self._waiting(task, d)
                        if w in ("WAIT", None):
                            d["status"] = "INCOMPLETE" if w == "WAIT" else "RUNNING"
                            progressed = w is None
                        else:
                            d["status"] = "NEEDS_USER" if w == "NEEDS_USER" else "INCOMPLETE"
        if task.get("cancelled"):
            task["status"] = "CANCELLED"
            return self._reply(task)
        st = [d["status"] for d in task["directions"]]
        if any(s == "FAILED_SAFE" for s in st):
            task["status"] = "FAILED_SAFE"
        elif any(s == "NEEDS_USER" for s in st):
            if task["ledger"].clarify_used >= task["ledger"].clarify_max:
                task["status"] = "INCOMPLETE"
                task["notes"].append("追問次數已達上限")
            else:
                task["status"] = "PARKED"
        elif all(s == "DONE" for s in st):
            task["status"] = "DONE"
        elif any(s == "DONE" for s in st):
            task["status"] = "PARTIAL"
        else:
            task["status"] = "INCOMPLETE"
        return self._reply(task)

    # ---------- 模板回覆（首版不用整理 LLM） ----------
    def _reply(self, task):
        lines = []
        A = task["artifacts"]
        if "route_preview" in A:
            rp = A["route_preview"]
            lines.append(f"預覽驗算：{'合格' if rp['verdict'] == 'pass' else '不合格'}，預估落地電量 "
                         f"{rp['est_end_pct']:.1f}%（出處：預覽 {rp['ref']}）" if rp.get("est_end_pct") is not None
                         else f"預覽驗算：{rp['verdict']}（出處：預覽 {rp['ref']}）")
        if "apply_proposal" in A:
            lines.append("已開啟套用到首頁的確認視窗，請在視窗內確認。")
        if "manual_claims" in A:
            mc = A["manual_claims"]
            if mc["verdict"] == "ok":
                for x in mc["refs"]:
                    lines.append(f"手冊出處：{x['manual'].upper()} {x['path']}（{x['heading_path'] or '無標題'}，版本 {x['version'][:7]}）")
            else:
                lines.append("手冊查不到相關內容。" if mc["verdict"] == "not_found" else "手冊尚未載入。")
        for d in task["directions"]:
            if d["status"] in ("INCOMPLETE", "FAILED_SAFE"):
                lines.append(f"{KIND_ZH[d['kind']]}：未完成（{d.get('reason', d['status'])}）")
        for q in task["questions"]:
            lines.append("請問：" + q["zh"])
        srcs = [s["source"] for s in task["steps"]]
        return {"status": task["status"], "task_id": task["id"], "reply_zh": "\n".join(lines) or "完成。",
                "questions": copy.deepcopy(task["questions"]),
                "directions": {d["kind"]: d["status"] for d in task["directions"]},
                "steps": copy.deepcopy(task["steps"]), "calls_used": task["ledger"].task_used,
                "sources": srcs, "notes": list(task["notes"])}
