"""ADR-0002 新架構（方案 B）：每批一次結構化規劃，程式驗證後執行（演算法說明 v3.5）。

與方案 A（agent_m4b.M4bController）共用：Gate、第 1 段方向排序、查詢向量 1 次、ID 檢索與分批（每批 3,000）、
動作白名單、ID／參數驗證、工具執行（_exec）、提案狀態與整理回覆。差別只在決策方式：
- A：每一步問模型選一個動作；
- B：每批問模型一次，輸出整份計畫 steps=[{id, direction, action, ids, params, after, bind, when, require}]，
  程式驗證整份計畫（白名單、候選、輸入槽、相依無循環、跨批引用）後依共用排程執行。
重規劃（Z-3，使用者 2026-11-19 12:58）：每任務最多 2 次，初始規劃（每批第一次）另計；計畫不合格的修正也從這 2 次扣（第 18 題）。
只重規劃受影響且未完成的步驟與其下游；用完後回覆各步驟完成／未完成及原因。
"""
from __future__ import annotations

import json
import re

from .agent_loop import default_extract
from . import outcomes as OC
from .agent_m4b import ACTIONS, ID_INPUT, KIND_ZH, PROPOSE, M4bController

REPLAN_MAX = 2
# 動作的輸出欄位（id_catalog_v1.json actions.outputs）；when 只能比對列舉欄位 verdict
OUTPUTS = {"QUERY_AREA": {"area_record"}, "GEN_COVERAGE": {"coverage_route"}, "VERIFY_PREVIEW": {"route_preview"},
           "MANUAL_SEARCH": {"manual_claims"}, "QA_LOOKUP": {"qa_claims"}, "REPORT_DRAFT": {"report_draft"},
           "DECLINE_FLIGHT": {"flight_notice"}}
INPUTS = {"GEN_COVERAGE": {"area": "area_record"}, "VERIFY_PREVIEW": {"route": "coverage_route"},
          "PROPOSE_HOME_ROUTE": {"preview": "route_preview"}}
WHEN_RE = re.compile(r"^(s\d+)\.route_preview\.verdict==(pass|fail)$")
TERMINAL_OK = ("OK", "PROPOSED", "SKIPPED")


BOUND = {"area_record", "coverage_route", "route_preview"}      # 只能經 bind 從來源步驟取得的成果


def _strs(x):
    return isinstance(x, list) and all(isinstance(i, str) for i in x)


def _str_map(x):
    return isinstance(x, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in x.items())


class PlanBController(M4bController):
    def __init__(self, *a, preset=None, **kw):
        """preset＝{"directions": [...], "stage1_calls": n}：同一案例在方案 A 的第 1 段輸出（v3.5 第 4 題：A／B 共用輸入）。"""
        super().__init__(*a, **kw)
        self.preset = preset

    def request(self, text):
        if self.preset is not None and self.preset.get("terminal"):
            t = self.preset["terminal"]
            n = int(self.preset.get("stage1_calls") or 0)
            return {"status": t["status"], "reply_zh": t["reply_zh"], "reply_source": "shared_from_A", "proposals": [],
                    "directions": list(self.preset.get("directions") or []), "stage1_raw": self.preset.get("stage1_raw"),
                    "stage1_augmented": self.preset.get("stage1_augmented"), "stage1_source": self.preset.get("stage1_source"),
                    "stage1_corrections": self.preset.get("stage1_corrections"),
                    "dir_status": {}, "steps": [], "notes": ["第 1 段結果沿用方案 A：" + t["reason"]],
                    "calls_used": n, "traces": [{"purpose": "stage1_shared", "replies": [], "calls": n}],
                    "retrieval": None, "packing": None, "artifacts": {}, "qv_ok": None, "t_pre_summary_s": 0.0,
                    "plan": [], "replans": 0, "plan_log": []}
        return super().request(text)

    def _directions(self, task):
        if self.preset is None:
            return super()._directions(task)
        n = int(self.preset.get("stage1_calls") or 0)
        for _ in range(n):                                   # 共用的第 1 段照 A 的實際次數記帳
            task["ledger"].reserve()
        task["traces"].append({"purpose": "stage1_shared", "replies": [], "source": "shared_from_A",
                               "directions": list(self.preset["directions"]), "calls": n})
        task["notes"].append("第 1 段方向沿用同一案例在方案 A 的輸出")
        task["stage1_source"] = self.preset.get("stage1_source")
        task["stage1_raw"] = self.preset.get("stage1_raw")            # v3.7：補方向前後都隨 A 的輸入帶過來
        task["stage1_corrections"] = self.preset.get("stage1_corrections")   # v3.9：A 的校正紀錄同筆帶過來
        if self.preset.get("stage1_augmented"):
            task["stage1_augmented"] = list(self.preset["stage1_augmented"])
        return list(self.preset["directions"])

    # ---------- 共用排程（每批） ----------
    def _schedule(self, task, qv):
        task.setdefault("plan", [])
        task.setdefault("replans", 0)
        task.setdefault("plan_log", [])
        planned = {s["direction"] for s in task["plan"]}
        batch = [d for d in task["directions"] if task["dir_status"][d] == "PENDING" and d not in planned]
        if "plan" in batch and task.get("area_status") in ("MANY", "NONE"):   # v3.7：與 A 相同，不交給模型猜
            task["dir_status"]["plan"] = "NEEDS_USER"
            task["notes"].append("原句沒有唯一指定區域，請框選或指名")
            batch.remove("plan")
        if batch:                                           # 空批不呼叫模型
            self._add_steps(task, self._plan(task, batch, initial=True))
        self._execute(task, qv)                             # 先前批次在等的步驟也一起推進
        self._accept(task, qv, [d for d in task["directions"] if d in (batch or []) or d in planned])  # 含先前批次
        for d in [d for d in task["directions"] if d in batch or d in planned]:
            ss = [s for s in task["plan"] if s["direction"] == d and s["state"] != "REPLACED"]
            st = [s["state"] for s in ss]
            if any(x == "NEEDS_USER" for x in st):
                task["dir_status"][d] = "NEEDS_USER"
            elif any(x == "WAITING" for x in st):
                task["dir_status"][d] = "WAITING"
            elif ss and all(x in TERMINAL_OK for x in st) and self._dir_done(task, d):
                task["dir_status"][d] = "DONE"
            elif d == "layout" and task.get("layout_items") and any(p["direction"] == "layout" for p in task["proposals"]):
                task["dir_status"][d] = "PARTIAL"            # v3.9：只開了部分版面項目
            else:
                task["dir_status"][d] = "INCOMPLETE"

    def _accept(self, task, qv, batch):
        """執行後驗收：實際成果仍缺、而且沒有步驟在等、不是需要使用者補充或合法略過 → 只對這些方向補計畫（扣 2 次額度）。"""
        while True:
            have = self.have(task)
            live = [x for x in task["plan"] if x["state"] != "REPLACED"]
            gap = []
            for d in batch:
                ss = [x for x in live if x["direction"] == d]
                if any(x["state"] in ("PENDING", "WAITING", "NEEDS_USER") for x in ss):
                    continue
                if OC.missing(d, have):
                    gap.append(d)
            if not gap or self.model is None or task["replans"] >= REPLAN_MAX:
                if gap:
                    task["plan_log"].append({"event": "accept_gap_unfilled", "dirs": gap,
                                             "missing": {d: OC.missing(d, have) for d in gap}})
                return
            task["replans"] += 1
            task["plan_log"].append({"event": "continue", "dirs": gap, "missing": {d: OC.missing(d, have) for d in gap},
                                     "replans": task["replans"]})
            redo = ("執行後驗收發現還缺：" + "；".join(f"{d} 缺 {'→'.join(OC.ZH[k] for k in OC.missing(d, have))}" for d in gap) +
                    f"。請只補上產生這些成果的步驟（可引用已完成步驟的結果），新步驟從 s{self._next_id(task)} 起編號")
            keep = [x for x in task["plan"] if x["state"] != "REPLACED"]
            forbid = frozenset((x["direction"], x["action"], json.dumps([x["ids"], x["params"], x["bind"]], sort_keys=True))
                               for x in keep if x["state"] in ("OK", "PROPOSED"))
            new = self._plan(task, gap, initial=False, fixed=keep, redo=redo, forbid=forbid, max_steps=6)
            if not new:
                task["plan_log"].append({"event": "accept_gap_unfilled", "dirs": gap})
                return
            self._add_steps(task, new, origin="model")
            self._execute(task, qv)

    # ---------- 規劃 ----------
    def _example(self, task, dirs):
        """v3.7：依本批方向產生的完整範例。有 plan 時示範「區域 → 航點 → 預覽 →（ui 時）首頁提案」；
        版面示範「元件＋參數＋value」。範例只示範格式與相依寫法，內容要依句子決定。"""
        steps, n = [], 1

        def add(d, a, ids=(), params=None, bind=None, when=None):
            nonlocal n
            steps.append({"id": f"s{n}", "direction": d, "action": a, "ids": list(ids), "params": params or {},
                          "after": [], "bind": bind or {}, "when": when, "require": {}})
            n += 1
            return steps[-1]["id"]
        verify = None
        for d in dirs:
            if d == "plan":
                area = (self._ids_of(task, "plan", "A") or ["A001"])[:1]
                s1 = add("plan", "QUERY_AREA", area)
                s2 = add("plan", "GEN_COVERAGE", bind={"area": f"{s1}.area_record"})
                verify = add("plan", "VERIFY_PREVIEW", bind={"route": f"{s2}.coverage_route"})
            elif d == "ui":
                if verify:
                    add("ui", "PROPOSE_HOME_ROUTE", ["U100"], bind={"preview": f"{verify}.route_preview"},
                        when=f"{verify}.route_preview.verdict==pass")
            elif d == "layout":
                c = self._ids_of(task, d, "C")[:1]
                pp = [i for i in self._ids_of(task, d, "P") if i != "P001"][:1] or self._ids_of(task, d, "P")[:1]
                if pp:
                    val = (self.graph.nodes[pp[0]].get("allowed") or [""])[0]
                    add("layout", "UI_LAYOUT_PROPOSE", (c if pp[0] != "P001" else []) + pp, {"value": val})
            elif d in ("color", "model"):
                add(d, ACTIONS[d][0], self._ids_of(task, d, "T" if d == "color" else "M")[:1])
            elif ACTIONS.get(d):
                add(d, ACTIONS[d][0])
        return json.dumps({"steps": steps}, ensure_ascii=False)

    def _plan_schema(self, task, dirs):
        """v3.7：每個動作一種形狀（anyOf）：ids 的角色與數量、必填 bind 槽、版面的 params.value。"""
        shapes = []
        for d in dirs:
            for a in ACTIONS.get(d, []):
                ids, params = self.action_shape(task, d, a)
                bind = {"type": "object"}
                if INPUTS.get(a):
                    bind = {"type": "object", "properties": {slot: {"type": "string"} for slot in INPUTS[a]},
                            "required": list(INPUTS[a])}
                shapes.append({"type": "object", "properties": {
                    "id": {"type": "string"}, "direction": {"type": "string", "enum": [d]},
                    "action": {"type": "string", "enum": [a]}, "ids": ids, "params": params,
                    "after": {"type": "array", "items": {"type": "string"}}, "bind": bind,
                    "when": {"type": ["string", "null"]}, "require": {"type": "object"}},
                    "required": ["id", "direction", "action", "ids", "params", "after", "bind", "when", "require"]})
        item = {"anyOf": shapes} if shapes else {"type": "object"}
        return {"type": "object", "properties": {"steps": {"type": "array", "minItems": 1, "items": item}},
                "required": ["steps"]}

    def _refs_hint(self, task, out):
        """修正訊息：目前可以引用的步驟與它們產生的成果。"""
        refs = []
        for x in [y for y in task.get("plan", []) if y["state"] != "REPLACED"] + list(out):
            pr = OC.PRODUCES.get(x["action"])
            if pr:
                refs.append(f"{x['id']}（{x['action']}，產生 {pr}）")
        return "可以引用：" + ("、".join(refs) if refs else "（目前沒有可引用的步驟，要先加產生它的步驟）")

    def _plan_prompt(self, task, dirs, fixed, redo=None):
        parts = [f"句子：{task['text']}", "方向（依序）：" + "、".join(f"{d}（{KIND_ZH[d]}）" for d in dirs)]
        for d in dirs:
            parts.append(f"[{d}] 可選動作：\n" + ("\n".join(f"- {a}：{OC.ACTION_ZH[a]}" for a in ACTIONS[d]) or "（無）") +
                         "\n可用 ID：\n" + ("\n".join(task["lines"].get(d, [])) or "（無）"))
        parts.append("目前狀態與每個方向的必要成果：\n" + OC.summary(dirs, self.have(task)))
        parts.append("計畫必須讓每個方向的必要成果都能產生；需要輸入的動作要用 bind 指到產生該輸入的步驟。")
        if fixed:
            parts.append("已存在的步驟（可在 after／bind／when／require 引用，不可重寫）：" +
                         json.dumps([{k: s[k] for k in ("id", "direction", "action", "state")} for s in fixed],
                                    ensure_ascii=False))
        if redo:
            parts.append("需要重新規劃的部分：" + redo)
        parts.append("規則：bind 寫 {\"輸入槽\":\"sN.輸出欄位\"}；when 只能寫 \"sN.route_preview.verdict==pass\"；"
                     "require 寫 {\"sN\":\"APPLIED\"}；params 只能填允許值。")
        parts.append("格式範例（只示範格式，內容要依句子決定）：" + self._example(task, dirs))
        parts.append('只輸出 JSON：{"steps":[...]}')
        return "\n".join(parts)

    def _next_id(self, task):
        return 1 + max([int(s["id"][1:]) for s in task["plan"]] or [0])

    def _validate(self, task, dirs, raw, fixed_ids, forbid=frozenset(), max_steps=None):
        obj = default_extract(raw)
        if not isinstance(obj, dict) or list(obj) != ["steps"] or not isinstance(obj["steps"], list):
            return False, None, "只能有 steps 一個欄位，且為清單"
        known = {s["id"]: s for s in task["plan"] if s["state"] != "REPLACED"}
        out, seen = [], set()
        if max_steps is not None and len(obj["steps"]) > max_steps:
            return False, None, f"重規劃最多 {max_steps} 步"
        for st in obj["steps"]:
            if not isinstance(st, dict) or not {"id", "direction", "action"} <= set(st) or \
                    not set(st) <= {"id", "direction", "action", "ids", "params", "after", "bind", "when", "require"}:
                return False, None, "步驟欄位錯誤"
            sid, d, a = st["id"], st["direction"], st["action"]
            if not isinstance(sid, str) or not re.fullmatch(r"s\d+", sid) or sid in seen or sid in fixed_ids:
                return False, None, f"步驟編號 {sid} 不合法或重複"
            if d not in dirs or a not in ACTIONS.get(d, []):
                return False, None, (f"{sid}：direction 只能是 {'、'.join(dirs)}；" +
                                     "；".join(f"{x} 的 action 只能是 {'、'.join(ACTIONS.get(x, [])) or '（無）'}" for x in dirs))
            ids, params = st.get("ids", []), st.get("params", {})
            after, bind, req = st.get("after", []), st.get("bind", {}), st.get("require", {})
            ids, after = ([] if ids is None else ids), ([] if after is None else after)
            params, bind, req = ({} if params is None else params), ({} if bind is None else bind), ({} if req is None else req)
            when = st.get("when")
            if not (_strs(ids) and _strs(after) and _str_map(params) and _str_map(bind) and _str_map(req)) or \
                    not (when is None or isinstance(when, str)):
                return False, None, f"{sid}：欄位型別錯誤"
            if (d, a, json.dumps([ids, params, bind], sort_keys=True)) in forbid:
                return False, None, f"{sid}：和已完成的步驟完全相同（{d}／{a}），不可重做"
            missing = set(INPUTS.get(a, {})) - set(bind)
            if missing:
                return False, None, (f"{sid}：{a} 必須用 bind 指定 {'、'.join(sorted(missing))} 的來源步驟。" +
                                     self._refs_hint(task, out))
            ok, _, err = self._parse_step(task, d, json.dumps({"action": a, "ids": ids, "params": params}), ACTIONS[d])
            if not ok:
                if a == "UI_LAYOUT_PROPOSE":                    # v3.7：版面錯誤列出可用的 C 與 P
                    err += f"（可用元件 C：{'、'.join(self._ids_of(task, d, 'C')[:8]) or '無'}；可用參數 P：{'、'.join(self._ids_of(task, d, 'P')) or '無'}）"
                return False, None, f"{sid}：{err}"
            prior = set(known) | seen
            for x in after:
                if x not in prior:
                    return False, None, f"{sid}：after 引用不存在或在後面的步驟 {x}"
            for slot, ref in bind.items():
                m = re.fullmatch(r"(s\d+)\.(\w+)", ref) if isinstance(ref, str) else None
                if slot not in INPUTS.get(a, {}) or not m or m.group(1) not in prior:
                    return False, None, (f"{sid}：bind {slot} 不合法（{a} 的輸入槽是 {'、'.join(INPUTS.get(a, {})) or '無'}，"
                                         f"值寫成「sN.{INPUTS.get(a, {}).get(slot, '欄位')}」）。" + self._refs_hint(task, out))
                src = (known.get(m.group(1)) or next(s for s in out if s["id"] == m.group(1)))
                if m.group(2) != INPUTS[a][slot] or m.group(2) not in OUTPUTS.get(src["action"], set()):
                    return False, None, (f"{sid}：bind {slot} 要指到產生 {INPUTS[a][slot]} 的步驟，"
                                         f"{m.group(1)} 產生的是 {OC.PRODUCES.get(src['action'])}。" + self._refs_hint(task, out))
                if m.group(1) not in after:
                    after = after + [m.group(1)]                  # 來源步驟自動列入 after
            if when is not None:
                m = WHEN_RE.match(when) if isinstance(when, str) else None
                if not m or m.group(1) not in prior:
                    return False, None, f"{sid}：when 只能比對先前步驟的預覽判定"
                src = known.get(m.group(1)) or next(s for s in out if s["id"] == m.group(1))
                if src["action"] != "VERIFY_PREVIEW":
                    return False, None, f"{sid}：when 引用的步驟沒有預覽判定"
            for x, state in req.items():
                if x not in prior or state != "APPLIED":
                    return False, None, f"{sid}：require 只能要求先前步驟 APPLIED"
                src = known.get(x) or next(s for s in out if s["id"] == x)
                if src["action"] not in PROPOSE:
                    return False, None, f"{sid}：require 的步驟不會有 APPLIED 狀態"
            if a == "UI_LAYOUT_PROPOSE" and OC.layout_key({"ids": ids, "params": params}) in \
                    [OC.layout_key(x) for x in out if x["action"] == "UI_LAYOUT_PROPOSE"]:
                return False, None, f"{sid}：和計畫中另一個版面步驟重複（同元件、參數、值）"   # v3.10（G19）
            seen.add(sid)
            out.append({"id": sid, "direction": d, "action": a, "ids": ids, "params": params, "after": after,
                        "bind": bind, "when": when, "require": req})
        # v3.6 執行前完整性：從目前成果與尚未完成的既有步驟出發，模擬整份計畫，每個方向的必要成果都要可達
        live = [x for x in task["plan"] if x["state"] != "REPLACED"]
        outs = {x["id"]: x.get("out") or {} for x in live if x["state"] in ("OK", "PROPOSED")}
        pend = [x for x in live if x["state"] in ("PENDING", "WAITING")]
        prod, bad = OC.simulate_steps(pend + out, outs, self.have(task),
                                      known=[x["id"] for x in live if x["state"] in TERMINAL_OK])  # 與執行器一致：只有 OK／PROPOSED／SKIPPED 滿足純順序 after
        if bad:
            return False, None, "；".join(f"{i} 不可達：{w}" for i, w in bad)
        sim = dict(self.have(task))
        for x in pend + out:                                  # 方向的必要成果要由該方向自己的可達步驟產生
            for k in prod.get(x["id"], set()):
                sim[k] = "（計畫中）"
        gaps = {d: OC.missing(d, sim) for d in dirs if OC.missing(d, sim)}
        if "layout" in dirs and task.get("layout_items"):     # v3.9 §3：逐項檢查版面步驟有沒有涵蓋每個必要項目
            planned = {OC.layout_key(x) for x in pend + out if x["action"] == "UI_LAYOUT_PROPOSE"} |                 {OC.layout_key(p) for p in task.get("proposals") or [] if p.get("direction") == "layout"}
            miss = [x for x in task["layout_items"] if x[1] and x[2] and tuple(x) not in planned]
            gaps.pop("layout", None)
            if miss:
                return False, None, "計畫不完整：版面還缺 " + "；".join(
                    f"{c + '＋' if c else ''}{pp}，value＝{v}" for c, pp, v in miss)
        if gaps:
            return False, None, "計畫不完整：" + "；".join(f"{d} 還缺 {'→'.join(OC.ZH[k] for k in m)}" for d, m in gaps.items())
        return True, out, ""

    def _plan(self, task, dirs, initial, fixed=None, redo=None, forbid=frozenset(), max_steps=None):
        """initial＝每批第一次規劃（另計）；不合格的修正與重規劃都扣每任務 2 次額度。"""
        fixed = fixed if fixed is not None else [s for s in task["plan"] if s["state"] != "REPLACED"]
        fixed_ids = {s["id"] for s in task["plan"]}        # 新編號不可和任何舊步驟（含已取代）重複
        content = self._plan_prompt(task, dirs, fixed, redo)
        trace = {"purpose": "plan" if initial else "replan", "replies": [], "source": "rule"}
        task["traces"].append(trace)
        err = ""
        first = True
        while self.model is not None:
            if not first:                                       # 修正＝扣重規劃額度
                if task["replans"] >= REPLAN_MAX:
                    task["plan_log"].append({"event": "replan_quota_exhausted", "reason": err})
                    break
                task["replans"] += 1
                task["plan_log"].append({"event": "correction", "reason": err, "replans": task["replans"]})
            if not task["ledger"].reserve():
                trace["budget_exhausted"] = True
                break
            msg = content + (f"\n上次錯誤：{err}。請只輸出合法 JSON。" if err else "")
            task["decision_seq"] = task.get("decision_seq", 0) + (1 if first else 0)
            call = {"messages": [{"role": "system", "content": task["rules"]}, {"role": "user", "content": msg}],
                    "purpose": trace["purpose"], "schema": self._plan_schema(task, dirs),
                    "attempt": 0 if first else 1, "decision": task["decision_seq"]}
            try:
                raw = self.model(call)
            except Exception as e:  # noqa: BLE001
                trace["replies"].append({"error": repr(e)})
                err, first = "沒有回覆", False
                continue
            trace["replies"].append({"raw": (raw or "")[:600]})
            try:
                ok, steps, err = self._validate(task, dirs, raw, fixed_ids, forbid, max_steps)
            except Exception as e:  # noqa: BLE001 - 合法 JSON 但型別怪異：當作不合格計畫
                ok, steps, err = False, None, f"計畫格式錯誤（{type(e).__name__}）"
            if ok:
                trace["source"] = "model"
                for x in steps:
                    x["origin"] = "model"
                return steps
            first = False
        if initial:
            task["notes"].append("計畫無效或未呼叫模型，改用規則計畫")
            steps = self._rule_plan(task, dirs)
            for x in steps:
                x["origin"] = "rule"
            return steps
        return None

    def _rule_plan(self, task, dirs):
        """規則計畫：與方案 A 的規則腳本同一套選擇（名稱比對＋相似度），一次寫成計畫。"""
        n = self._next_id(task)
        steps, last_verify = [], None
        for d in dirs:
            done_before = len(task["steps"])
            for a in ACTIONS[d]:
                sid = f"s{n}"
                n += 1
                st = {"id": sid, "direction": d, "action": a, "ids": [], "params": {}, "after": [], "bind": {},
                      "when": None, "require": {}}
                if a == "UI_LAYOUT_PROPOSE" and task.get("layout_items"):   # v3.9：按缺項各建一步
                    miss = [x for x in self.have(task).get("_layout_missing", []) if x[2]]
                    for k, (c, pp, v) in enumerate(miss):
                        if k:
                            sid = f"s{n}"
                            n += 1
                        steps.append({"id": sid, "direction": d, "action": a, "ids": ([c] if c else []) + [pp],
                                      "params": {"value": v}, "after": [], "bind": {}, "when": None, "require": {}})
                    continue
                if a == "QUERY_AREA" or a in ID_INPUT:          # 方向內第一個動作：規則腳本選 ID 與允許值
                    rs = self._rule_step(task, d)
                    st["ids"], st["params"] = rs["ids"], rs["params"]
                if a == "GEN_COVERAGE":
                    st["bind"], st["after"] = {"area": f"{steps[-1]['id']}.area_record"}, [steps[-1]["id"]]
                if a == "VERIFY_PREVIEW":
                    st["bind"], st["after"] = {"route": f"{steps[-1]['id']}.coverage_route"}, [steps[-1]["id"]]
                    last_verify = sid
                if a == "PROPOSE_HOME_ROUTE" and last_verify:
                    st["bind"], st["after"] = {"preview": f"{last_verify}.route_preview"}, [last_verify]
                    st["when"] = f"{last_verify}.route_preview.verdict==pass"
                steps.append(st)
            del task["steps"][done_before:]
        return steps

    def _add_steps(self, task, steps, origin=None):
        for s in steps or []:
            s = dict(s, state="PENDING")
            if origin and "origin" not in s:
                s["origin"] = origin
            task["plan"].append(s)

    # ---------- 執行 ----------
    def _ready(self, task, s):
        """回傳 run／skip／wait／fail_dep（來源失敗）／missing（來源正常結束或略過，但沒有所需結果 → 重新判斷）。"""
        P = {x["id"]: x for x in task["plan"]}
        if s["when"]:                                       # 已知不成立的條件優先：直接略過
            m = WHEN_RE.match(s["when"])
            src = P.get(m.group(1)) or {}
            verdict = ((src.get("out") or {}).get("route_preview") or {}).get("verdict")
            if src.get("state") == "OK" and verdict is not None and verdict != m.group(2):
                return "skip"
        dead = [x for x in s["require"] if x in P and P[x]["state"] not in ("PENDING", "WAITING", "PROPOSED")]
        if dead:                                            # v7（0418）：已知不可能有提案的 require 先判，不受其他來源仍在等待影響
            s["_why"] = "；".join(f"等待套用的 {x} 沒有開提案（{P[x]['state']}），不會套用" for x in dead)
            return "fail_dep"
        deps = set(s["after"]) | {r.split(".")[0] for r in s["bind"].values()} | set(s["require"])
        if s["when"]:
            deps.add(WHEN_RE.match(s["when"]).group(1))
        for x in deps:
            st = P[x]["state"] if x in P else "MISSING"
            if st in ("PENDING", "WAITING"):
                return "wait"
            if st not in TERMINAL_OK:
                return "fail_dep"
        if s["when"]:                                       # v5（0416 第 2 點）：先判條件；已知不成立就略過，不再等套用
            m = WHEN_RE.match(s["when"])
            src = P[m.group(1)]
            verdict = ((src.get("out") or {}).get("route_preview") or {}).get("verdict")
            if src["state"] == "SKIPPED" or verdict is None:
                return "missing"
            if verdict != m.group(2):
                return "skip"
        for slot, ref in s["bind"].items():                 # 取值一律來自來源步驟自己的輸出
            sid, field = ref.split(".", 1)
            if field not in (P[sid].get("out") or {}):
                return "missing"
        dead = [x for x in s["require"] if P[x]["state"] != "PROPOSED"]   # v6：先看全部來源能不能有提案
        if dead:
            s["_why"] = "；".join(f"等待套用的 {x} 沒有開提案（{P[x]['state']}），不會套用" for x in dead)
            return "fail_dep"
        if any(P[x].get("applied") is not True for x in s["require"]):
            return "wait"
        return "run"

    def _execute(self, task, qv):
        order = {d: k for k, d in enumerate(task["directions"])}
        while True:
            progressed = False
            pend = sorted((s for s in task["plan"] if s["state"] in ("PENDING", "WAITING")),
                          key=lambda s: (order[s["direction"]], int(s["id"][1:])))
            for s in pend:
                r = self._ready(task, s)
                if r == "wait":
                    s["state"] = "WAITING"
                    continue
                if r == "skip":
                    s["state"] = "SKIPPED"
                elif r == "fail_dep":
                    s["state"] = "FAILED_DEP"
                    s["reason"] = s.pop("_why", None) or "前置步驟失敗"
                elif r == "missing":                        # v4（CODEX-APP-0408 第 3 點）：缺結果相依 → 重新判斷
                    s["state"] = "FAILED_DEP"
                    s["reason"] = "前置步驟沒有產生所需結果"
                    if self._replan(task, s):
                        progressed = True
                        break
                else:
                    step = {"action": s["action"], "ids": s["ids"], "params": s["params"]}
                    task["steps"].append(dict(step, direction=s["direction"], source="plan", step_id=s["id"]))
                    res = self._exec_bound(task, s, step, qv)
                    s["state"] = {"OK": "PROPOSED" if s["action"] in PROPOSE else "OK"}.get(res, res)
                    if res == "BLOCKED" and self._replan(task, s):
                        progressed = True
                        break
                progressed = True
                break
            if not progressed:
                break
        for s in task["plan"]:
            if s["state"] == "WAITING":
                s["reason"] = "等待前一步（未就緒或尚未 APPLIED）"

    def _exec_bound(self, task, s, step, qv):
        """以步驟自己的視圖執行：可綁定成果只看 bind 指到的來源步驟輸出，不讀任務全域同名成果。"""
        P = {x["id"]: x for x in task["plan"]}
        glob = task["artifacts"]
        view = {k: v for k, v in glob.items() if k not in BOUND}
        for slot, ref in s["bind"].items():
            sid, field = ref.split(".", 1)
            view[field] = P[sid]["out"][field]
        before = {k: id(v) for k, v in view.items()}
        task["artifacts"] = view
        task["cur_by"] = s.get("origin", "rule")
        try:
            res = self._exec(task, s["direction"], step, qv)
        finally:
            task["artifacts"] = glob
        s["out"] = {k: v for k, v in view.items() if before.get(k) != id(v)}
        task["exec_seq"] = task.get("exec_seq", 0) + 1
        s["exec_seq"] = task["exec_seq"]                     # 實際執行順序（v7：結果預覽依此選，不依清單位置）
        for k, v in s["out"].items():                         # 全域只留最新一份給回覆模板
            glob[k] = v
        return res

    def _downstream(self, task, sid):
        out, frontier = {sid}, {sid}
        while frontier:
            nxt = set()
            for s in task["plan"]:
                refs = set(s["after"]) | {r.split(".")[0] for r in s["bind"].values()} | set(s["require"])
                if s["when"]:
                    refs.add(WHEN_RE.match(s["when"]).group(1))
                if refs & frontier and s["id"] not in out:
                    nxt.add(s["id"])
            out |= nxt
            frontier = nxt
        return out

    def _replan(self, task, failed):
        """只重規劃失敗步驟與其未完成下游；成功時以新步驟取代。"""
        if task["replans"] >= REPLAN_MAX or self.model is None:
            failed["reason"] = "重規劃額度已用完" if self.model is not None else "規則計畫不重規劃"
            return False
        affected = [s for s in task["plan"] if s["id"] in self._downstream(task, failed["id"]) and
                    s["state"] in ("PENDING", "WAITING", "BLOCKED", "FAILED_DEP")]
        task["replans"] += 1
        task["plan_log"].append({"event": "replan", "failed": failed["id"], "affected": [s["id"] for s in affected],
                                 "replans": task["replans"]})
        keep = [s for s in task["plan"] if s not in affected and s["state"] != "REPLACED"]
        prev = {s["id"]: s["state"] for s in affected}
        for s in affected:
            s["state"] = "REPLACED"
        dirs = list(dict.fromkeys(s["direction"] for s in affected))
        redo = (f"步驟 {failed['id']}（{failed['action']}）失敗；請只重寫這些步驟：" +
                "、".join(f"{s['id']} {s['action']}" for s in affected) + f"；新步驟從 s{self._next_id(task)} 起編號")
        forbid = frozenset((s["direction"], s["action"], json.dumps([s["ids"], s["params"], s["bind"]], sort_keys=True))
                           for s in keep if s["state"] in ("OK", "PROPOSED"))
        new = self._plan(task, dirs, initial=False, fixed=keep, redo=redo, forbid=forbid,
                         max_steps=len(affected) + 2)
        if new is None:                                    # 空清單＝合法地放棄這些步驟
            for s in affected:
                s["state"] = prev[s["id"]]
            failed["reason"] = "重規劃無有效計畫"
            return False
        self._add_steps(task, new)
        return True

    def have(self, task):
        """B 的成果狀態：除全域最新成果外，只要有任一完成且合格的預覽步驟，就算「有合格預覽」可供首頁提案引用。"""
        h = super().have(task)
        for x in task.get("plan") or []:
            pv = (x.get("out") or {}).get("route_preview") or {}
            if x["action"] == "VERIFY_PREVIEW" and x["state"] == "OK" and pv.get("verdict") == "pass":
                h["route_preview_pass"] = f"合格（預覽 {pv.get('ref')}，步驟 {x['id']}）"
        return h

    def result_preview(self, task):
        """v6（0410）：本任務的「結果預覽」只有一個定義，終態與計分共用——
        有首頁提案時＝它實際綁定的那份預覽；沒有時＝**實際執行順序**最後完成的預覽步驟（與方案 A 的最新一份同義）。
        回覆模板與數字出處也用它（v7，0411）。"""
        outs = {}
        last = None
        done = [x for x in task.get("plan") or [] if x["action"] == "VERIFY_PREVIEW" and x["state"] == "OK"
                and (x.get("out") or {}).get("route_preview")]
        for x in sorted(done, key=lambda x: x.get("exec_seq", 0)):
            pv = x["out"]["route_preview"]
            outs[pv.get("ref")] = pv
            last = pv
        for p in task.get("proposals") or []:
            src = p.get("source") or {}
            if p["action"] == "PROPOSE_HOME_ROUTE" and src.get("preview_ref") in outs:
                return outs[src["preview_ref"]]
        return last

    def _dir_done(self, task, d):
        if d == "plan" and task.get("plan") is not None:
            return ((self.result_preview(task) or {}).get("verdict")) == "pass"
        return super()._dir_done(task, d)

    def _finish(self, task, status, ask=None):
        rp = self.result_preview(task)
        if rp is not None:                                    # v7：回覆模板與數字出處也用同一份結果預覽
            task["artifacts"]["route_preview"] = rp
        r = super()._finish(task, status, ask)
        r["plan"] = task.get("plan", [])
        r["result_preview"] = self.result_preview(task)
        r["replans"] = task.get("replans", 0)
        r["plan_log"] = task.get("plan_log", [])
        return r
