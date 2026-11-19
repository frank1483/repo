"""ADR-0002 M4b：方案 A 逐方向逐步迴圈（演算法說明 v3.4；使用者 2026-11-19 12:58 同意照 v3.4 實作、混合句採 D-1 新版）。

流程：Gate（薄：空輸入、超過 200 字）→ LLM 第 1 段（10 種方向選出並排序）→ 查詢向量 1 次（第 1 段之後）
→ 按方向檢索 ID＋預算分配 → 共用排程：依方向優先序，一次做一個方向；方向卡住才推進下一個
→ 每步 LLM 輸出 {"action", "ids", "params"}，程式驗證（動作白名單、ID 在本次候選內且型別相符、params 為允許值）後執行
→ 套用類動作只到 PROPOSED → LLM 整理回覆（數字必須出自成果，否則用模板）。
沒有任何飛控動作；flight_request 方向只回固定說明，模型漏判時程式仍補上說明。
"""
from __future__ import annotations

import copy
import json
import re
import time

from .agent_loop import default_extract
from .id_graph import DIRECTION_CATS, pack

KINDS = ("plan", "ui", "qa", "report", "chat", "manual", "layout", "color", "model", "flight_request")
KIND_ZH = {"plan": "任務規劃", "ui": "放到首頁", "qa": "問答", "report": "報告", "chat": "閒聊", "manual": "手冊查詢",
           "layout": "版面", "color": "顏色", "model": "模型切換", "flight_request": "飛控要求"}
KEYWORDS = {"plan": ["巡檢", "航線", "規劃", "覆蓋"], "ui": ["首頁"], "qa": ["是什麼", "如何", "為什麼", "多少"],
            "report": ["報告", "摘要"], "manual": ["手冊", "說明書", "PX4", "QGC"],
            "layout": ["放大", "縮小", "移到", "隱藏", "顯示", "版面", "文字", "字體", "大小"],
            "color": ["主題", "深色", "淺色", "高對比", "顏色", "配色", "夜間"],
            "model": ["模型", "規則模式", "VLM", "LLM", "辨識"],
            "flight_request": ["起飛", "降落", "返航", "解鎖", "上鎖", "懸停", "拍照", "錄影"]}
FLIGHT_WORDS = KEYWORDS["flight_request"]
FLIGHT_NOTICE = "飛控指令（例如起飛、返航）不會由 AI 執行，請用畫面上的指令區（需滑動確認）。"
ACTIONS = {"plan": ["QUERY_AREA", "GEN_COVERAGE", "VERIFY_PREVIEW"], "ui": ["PROPOSE_HOME_ROUTE"],
           "layout": ["UI_LAYOUT_PROPOSE"], "color": ["UI_THEME_PROPOSE"], "model": ["MODEL_SWITCH_PROPOSE"],
           "manual": ["MANUAL_SEARCH"], "qa": ["QA_LOOKUP"], "report": ["REPORT_DRAFT"], "chat": [],
           "flight_request": ["DECLINE_FLIGHT"]}
ID_INPUT = {"QUERY_AREA": ["A"], "UI_LAYOUT_PROPOSE": ["C", "P"], "UI_THEME_PROPOSE": ["T"],
            "MODEL_SWITCH_PROPOSE": ["M"], "PROPOSE_HOME_ROUTE": ["U"]}
PROPOSE = {"PROPOSE_HOME_ROUTE", "UI_LAYOUT_PROPOSE", "UI_THEME_PROPOSE", "MODEL_SWITCH_PROPOSE"}
TEST_VALUES = {"per_sentence_calls": 30, "steps_max": 6, "direction_cap": 3}


class Ledger:
    def __init__(self, per_sentence=None):
        self.limit = TEST_VALUES["per_sentence_calls"] if per_sentence is None else per_sentence
        self.used = 0

    def reserve(self):
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


class M4bController:
    def __init__(self, tools, model, graph, counter, ledger_cfg=None, steps_max=None, direction_cap=None,
                 summary_llm=True):
        self.tools = tools
        self.model = model
        self.graph = graph
        self.counter = counter
        self.ledger_cfg = ledger_cfg or {}
        self.steps_max = steps_max or TEST_VALUES["steps_max"]
        self.cap = direction_cap or TEST_VALUES["direction_cap"]
        self.summary_llm = summary_llm

    # ---------- 模型呼叫（經帳本，最多修正一次） ----------
    def _call(self, task, purpose, content, parse):
        trace = {"purpose": purpose, "replies": [], "source": "rule"}
        task["traces"].append(trace)
        if self.model is None:
            return None
        err = ""
        for attempt in range(2):
            if not task["ledger"].reserve():
                trace["budget_exhausted"] = True
                return None
            msg = content + (f"\n上次錯誤：{err}。請只輸出合法 JSON。" if err else "")
            call = {"messages": [{"role": "system", "content": task["rules"]}, {"role": "user", "content": msg}],
                    "purpose": purpose}
            try:
                raw = self.model(call)
            except Exception as e:  # noqa: BLE001
                trace["replies"].append({"error": repr(e)})
                err = "沒有回覆"
                continue
            trace["replies"].append({"raw": (raw or "")[:300]})
            ok, val, err = parse(raw)
            if ok:
                trace["source"] = "model"
                return val
        return None

    # ---------- 入口 ----------
    def request(self, text):
        t0 = time.monotonic()
        raw = str(text or "")
        if not raw.strip() or not re.search(r"[0-9A-Za-z一-鿿]", raw):
            return {"status": "INVALID_INPUT", "reply_zh": "請輸入內容", "proposals": [], "traces": []}
        if len(raw) > 200:
            return {"status": "TOO_LONG", "reply_zh": "輸入過長，請拆成短句", "proposals": [], "traces": []}
        task = {"text": raw, "ledger": Ledger(**self.ledger_cfg), "traces": [], "artifacts": {}, "proposals": [],
                "steps": [], "notes": [], "directions": [], "dir_status": {}, "t0": t0,
                "rules": ("你是地面站助理。只輸出 JSON。規則：飛控命令（起飛、降落、返航、解鎖、拍照等）一律不執行，"
                          "只能規劃、查詢或開確認視窗；遇到飛控要求請選 flight_request 方向。數字一律來自工具，不可自行計算。")}
        if "bind_task" in self.tools:                       # 保留電量等條件由程式從原句解析（同 M4）
            self.tools["bind_task"]({"text": raw})
        dirs = self._directions(task)
        if len(dirs) > self.cap:
            task["notes"].append(f"方向 {len(dirs)} 個超過上限 {self.cap}，請分批")
            return self._finish(task, "PARKED", ask=f"這句話包含 {len(dirs)} 件事，請先選最多 {self.cap} 件")
        task["directions"] = dirs
        qv = self.tools["embed_query"](raw) if "embed_query" in self.tools else None   # 第 1 段之後，1 次
        task["qv_ok"] = qv is not None
        retrieved = {d: self.graph.retrieve(d, qv) for d in dirs}
        task["retrieval"] = {d: retrieved[d]["log"] for d in dirs}
        task["packing"] = {"batches": []}
        task["cands"], task["lines"] = {}, {}
        for d in dirs:
            task["dir_status"][d] = "PENDING_BATCH"
        remaining = list(dirs)
        while remaining:                                   # v3.5：每批上限 3,000；每個方向只分配一次
            packed = pack(self.graph, remaining, retrieved, self.counter)
            task["packing"]["batches"].append(
                {"directions": list(packed["plan"]), "pending": packed["pending"], "log": packed["log"],
                 "total_tokens": packed["total_tokens"],
                 "per_dir": {d: {"items": p["items"], "tokens": p["tokens"], "cap": p["cap"]}
                             for d, p in packed["plan"].items()}})
            if not packed["plan"]:                          # 空批：剩下的方向單獨也放不進 → 記原因並結束
                for d in remaining:
                    task["dir_status"][d] = "NEEDS_USER"
                    task["notes"].append(f"{KIND_ZH[d]}：必要資料超過單方向上限，請把範圍講小")
                task["packing"]["over_dir_limit"] = list(remaining)
                break
            for d, pl in packed["plan"].items():
                task["cands"][d], task["lines"][d] = pl["items"], pl["lines"]
                task["dir_status"][d] = "PENDING"
            for d in task["directions"]:                    # 等前一批結果的方向重新判斷
                if task["dir_status"][d] == "WAITING":
                    task["dir_status"][d] = "PENDING"
            self._schedule(task, qv)
            remaining = packed["pending"]
        if any(w in raw for w in FLIGHT_WORDS) and not any(p.get("kind") == "flight_notice"
                                                             for p in task["artifacts"].values()):
            task["artifacts"]["flight_notice"] = {"kind": "flight_notice", "by": "program"}
            task["notes"].append("程式補上飛控說明（模型未選 flight_request）")
        st = task["dir_status"]
        if any(s == "NEEDS_USER" for s in st.values()):
            status = "PARKED"
        elif all(s == "DONE" for s in st.values()) and st:
            status = "DONE"
        elif any(s == "DONE" for s in st.values()):
            status = "PARTIAL"
        else:
            status = "INCOMPLETE"
        return self._finish(task, status)

    # ---------- 第 1 段 ----------
    def _directions(self, task):
        def parse(raw):
            obj = default_extract(raw)
            if not isinstance(obj, dict) or list(obj) != ["directions"]:
                return False, None, "只能有 directions 一個欄位"
            ds = obj["directions"]
            if not isinstance(ds, list) or not ds or not all(isinstance(d, str) and d in KINDS for d in ds):
                return False, None, "directions 必須是白名單內的方向清單"
            return True, list(dict.fromkeys(ds)), ""
        content = ("句子：" + task["text"] + "\n可選方向（依你判斷的先後排序輸出）：" + "｜".join(
            f"{k} {KIND_ZH[k]}" for k in KINDS) + '\n只輸出 JSON：{"directions":["..."]}')
        ds = self._call(task, "stage1", content, parse)
        if ds is None:
            ds = [k for k in KINDS if any(w in task["text"] for w in KEYWORDS.get(k, []))] or ["chat"]
            task["notes"].append("第 1 段無效或未呼叫模型，改用關鍵字表")
        if "ui" in ds and "plan" in ds and ds.index("ui") < ds.index("plan"):   # 明確相依：ui 需要 plan 的成果
            ds.remove("ui")
            ds.insert(ds.index("plan") + 1, "ui")
            task["notes"].append("依相依把 ui 排到 plan 之後")
        return ds

    # ---------- 共用排程 ----------
    def _schedule(self, task, qv):
        progressed = True
        while progressed:
            progressed = False
            for d in task["directions"]:                       # 依優先序；前面卡住才推進後面
                if task["dir_status"][d] not in ("PENDING", "WAITING"):
                    continue
                if d == "ui" and not self._ui_ready(task):
                    task["dir_status"][d] = "WAITING" if task["dir_status"].get("plan") in ("PENDING", "RUNNING", "WAITING", "PENDING_BATCH") \
                        else "INCOMPLETE"
                    continue
                task["dir_status"][d] = "RUNNING"
                self._run_direction(task, d, qv)
                progressed = True
                break

    def _ui_ready(self, task):
        rp = task["artifacts"].get("route_preview")
        return bool(rp and rp.get("verdict") == "pass")

    # ---------- 方向內逐步 ----------
    def _run_direction(self, task, d, qv):
        allowed = ACTIONS[d] + ["FINISH", "HOLD"]
        steps = 0
        while steps < self.steps_max:
            steps += 1
            done_actions = [s["action"] for s in task["steps"] if s["direction"] == d]
            content = (f"句子：{task['text']}\n方向：{d}（{KIND_ZH[d]}）\n可用 ID：\n" +
                       ("\n".join(task["lines"].get(d, [])) or "（無）") +
                       f"\n目前進度：{self._progress(task)}\n本方向已做：{'、'.join(done_actions) or '無'}\n"
                       f"可選動作：{'｜'.join(allowed)}\n"
                       '只輸出 JSON：{"action":"動作","ids":["ID"],"params":{}}')
            step = self._call(task, f"step:{d}", content, lambda raw: self._parse_step(task, d, raw, allowed))
            source = "model" if step is not None else "rule"
            if step is None:
                step = self._rule_step(task, d)
            task["steps"].append(dict(step, direction=d, source=source))
            if step["action"] == "HOLD":
                task["dir_status"][d] = "FAILED_SAFE"
                return
            if step["action"] == "FINISH":
                task["dir_status"][d] = "DONE" if self._dir_done(task, d) else "INCOMPLETE"
                return
            res = self._exec(task, d, step, qv)
            if res == "NEEDS_USER":
                task["dir_status"][d] = "NEEDS_USER"
                return
            if res == "BLOCKED":
                task["dir_status"][d] = "INCOMPLETE"
                return
        task["dir_status"][d] = "DONE" if self._dir_done(task, d) else "INCOMPLETE"

    def _parse_step(self, task, d, raw, allowed):
        obj = default_extract(raw)
        if not isinstance(obj, dict) or not set(obj) <= {"action", "ids", "params"} or "action" not in obj:
            return False, None, "格式錯誤"
        a = obj["action"]
        if a not in allowed:
            return False, None, f"動作 {a} 不在可選清單"
        ids = obj.get("ids") or []
        params = obj.get("params") or {}
        if not isinstance(ids, list) or not isinstance(params, dict):
            return False, None, "ids／params 型別錯誤"
        cands = set(task["cands"].get(d, []))
        for i in ids:
            if i not in cands:
                return False, None, f"{i} 不在本次候選"
        err = self.check_schema(a, ids, params)
        if err:
            return False, None, err
        return True, {"action": a, "ids": ids, "params": params}, ""

    def check_schema(self, a, ids, params):
        """依動作逐槽驗證 ID 角色、數量與參數鍵值（CODEX-APP-0405 第 3 點）。回傳錯誤字串或空字串。"""
        if len(set(ids)) != len(ids):
            return "ids 重複"
        cats = [self.graph.nodes[i]["cat"] for i in ids]
        if a == "UI_LAYOUT_PROPOSE":
            ps = [i for i, c in zip(ids, cats) if c == "P"]
            cs = [i for i, c in zip(ids, cats) if c == "C"]
            if len(ps) != 1 or len(cs) + len(ps) != len(ids):
                return "版面提案要剛好一個參數（P），其餘只能是元件（C）"
            if ps[0] == "P001" and cs:
                return "全域文字大小（P001）不帶元件"
            if ps[0] != "P001" and len(cs) != 1:
                return "元件參數要剛好指定一個元件"
            allowed = self.graph.nodes[ps[0]].get("allowed") or []
            if list(params) != ["value"] or params["value"] not in allowed:
                return f"params 只能是 {{\"value\": {'／'.join(allowed)}}}"
            return ""
        if params:
            return f"{a} 不收 params"
        if a == "UI_THEME_PROPOSE":
            return "" if cats == ["T"] else "主題提案要剛好一個主題（T）"
        if a == "MODEL_SWITCH_PROPOSE":
            return "" if cats == ["M"] else "模型提案要剛好一個模型（M）"
        if a == "PROPOSE_HOME_ROUTE":
            return "" if ids in ([], ["U100"]) else "首頁提案只能指定 U100"
        if a == "QUERY_AREA":
            return "" if all(c == "A" for c in cats) else "區域查詢只能指定區域（A）"
        return "" if not ids else f"{a} 不收 ids"

    def _rule_step(self, task, d):
        """規則腳本：依目前缺的成果選下一步；ID 取該方向候選中相似度最高的對應型別。"""
        A = task["artifacts"]
        cands = task["cands"].get(d, [])

        def named(i):
            n = self.graph.nodes[i]
            return any(w and w.lower() in task["text"].lower() for w in [n["name"]] + list(n.get("aliases") or []))

        def first(cat):                                 # 規則：先找原句提到名稱或別名者，再依相似度
            xs = [i for i in cands if self.graph.nodes[i]["cat"] == cat]
            return ([i for i in xs if named(i)] or xs)[:1]

        def value_for(ids):
            vals = []
            for i in ids:
                vals += [v for v in self.graph.nodes[i].get("allowed") or [] if v in task["text"]]
            return {"value": max(vals, key=len)} if vals else {}
        if d == "plan":
            if "area_record" not in A:
                ids = []
                if "query_area" in self.tools:                 # 規則備援：用原句比對區域名，不猜
                    q = self.tools["query_area"](task["text"])
                    if q["status"] == "ONE":
                        ids = [i for i, n in self.graph.nodes.items() if n.get("area") == q["candidates"][0]][:1]
                    else:
                        ids = [i for i, n in self.graph.nodes.items() if n.get("area") in q["candidates"]]
                else:
                    ids = first("A")
                return {"action": "QUERY_AREA", "ids": ids, "params": {}}
            if "coverage_route" not in A:
                return {"action": "GEN_COVERAGE", "ids": [], "params": {}}
            if "route_preview" not in A:
                return {"action": "VERIFY_PREVIEW", "ids": [], "params": {}}
            return {"action": "FINISH", "ids": [], "params": {}}
        for a in ACTIONS[d]:
            if not any(s["action"] == a and s["direction"] == d for s in task["steps"]):
                ids = []
                for c in ID_INPUT.get(a, []):
                    ids += first(c)
                if a == "UI_LAYOUT_PROPOSE" and "P001" in ids:      # 全域文字大小不帶元件
                    ids = ["P001"]
                if a == "PROPOSE_HOME_ROUTE":
                    ids = ["U100"]
                return {"action": a, "ids": ids, "params": value_for(ids) if a == "UI_LAYOUT_PROPOSE" else {}}
        return {"action": "FINISH", "ids": [], "params": {}}

    def _exec(self, task, d, step, qv):
        A, T, a = task["artifacts"], self.tools, step["action"]
        ids, params = step["ids"], step["params"]
        err = self.check_schema(a, ids, params) if a in PROPOSE else ""
        if err:
            task["notes"].append(f"{a}：{err}")
            return "NEEDS_USER"
        if a == "QUERY_AREA":
            areas = [i for i in ids if self.graph.nodes[i]["cat"] == "A"]
            if len(areas) != 1:
                task["notes"].append("區域未唯一指定")
                return "NEEDS_USER"
            A["area_record"] = {"kind": "area_record", "ref": self.graph.nodes[areas[0]]["area"], "id": areas[0]}
            return "OK"
        if a == "GEN_COVERAGE":
            if "area_record" not in A:
                return "BLOCKED"
            r = T["gen_coverage"](A["area_record"]["ref"])
            if r["status"] != "OK":
                return "BLOCKED"
            A["coverage_route"] = {"kind": "coverage_route", "ref": r["route_ref"]}
            return "OK"
        if a == "VERIFY_PREVIEW":
            if "coverage_route" not in A:
                return "BLOCKED"
            r = T["verify_preview"](A["coverage_route"]["ref"])
            A["route_preview"] = {"kind": "route_preview", "ref": r["preview_ref"], "verdict": r["result"],
                                  "est_end_pct": r.get("est_end_pct")}
            return "OK"
        if a == "PROPOSE_HOME_ROUTE":
            if not self._ui_ready(task):
                return "BLOCKED"
            try:
                r = T["propose_home_route"](A["route_preview"]["ref"])
            except Exception as e:  # noqa: BLE001 - 開窗失敗不算提案
                task["notes"].append(f"首頁確認視窗沒有開成：{e!r}")
                return "BLOCKED"
            if r.get("decision") == "BLOCK" or not r.get("shown_hash"):
                task["notes"].append(f"首頁確認視窗被擋下（decision={r.get('decision')}）")
                return "BLOCKED"
            self._propose(task, d, a, ["U100"], {}, r.get("shown_hash"))
            return "OK"
        if a == "UI_LAYOUT_PROPOSE":
            cs = [i for i in ids if self.graph.nodes[i]["cat"] == "C"]
            ps = [i for i in ids if self.graph.nodes[i]["cat"] == "P"]
            if not ps:
                return "BLOCKED"
            if ps[0] == "P004" and cs and self.graph.nodes[cs[0]].get("locked") and params.get("value") == "隱藏":
                task["notes"].append("鎖定元件不可隱藏")
                return "BLOCKED"
            self._propose(task, d, a, cs + ps, params, None)
            return "OK"
        if a in ("UI_THEME_PROPOSE", "MODEL_SWITCH_PROPOSE"):
            need = "T" if a == "UI_THEME_PROPOSE" else "M"
            xs = [i for i in ids if self.graph.nodes[i]["cat"] == need]
            self._propose(task, d, a, xs, {}, None)
            return "OK"
        if a == "MANUAL_SEARCH":
            r = T["manual_search"](task["text"], qv) if "manual_search" in T else {"results": [], "status": "NOT_LOADED"}
            A["manual_claims"] = {"kind": "manual_claims", "verdict": "ok" if r.get("results") else "not_found",
                                  "refs": [{k: x[k] for k in ("manual", "path", "heading_path", "version", "chunk_id")}
                                           | {"excerpt": x["text"][:400]} for x in r.get("results", [])],
                                  "degraded": r.get("degraded"), "degraded_reason": r.get("degraded_reason")}
            return "OK"
        if a == "QA_LOOKUP":
            A["qa_claims"] = {"kind": "qa_claims", "verdict": "none", "note": "問答工具尚未接上"}
            return "OK"
        if a == "REPORT_DRAFT":
            A["report_draft"] = {"kind": "report_draft", "verdict": "ok"}
            return "OK"
        if a == "DECLINE_FLIGHT":
            A["flight_notice"] = {"kind": "flight_notice", "by": "model"}
            return "OK"
        return "BLOCKED"

    def _propose(self, task, d, action, ids, params, ref):
        task["proposals"].append({"direction": d, "action": action, "ids": list(ids), "params": dict(params),
                                  "state": "PROPOSED", "ref": ref,
                                  "t_ready_s": round(time.monotonic() - task["t0"], 3)})

    def _dir_done(self, task, d):
        A = task["artifacts"]
        if d == "plan":
            return bool(A.get("route_preview") and A["route_preview"].get("verdict") == "pass")
        if d in ("ui", "layout", "color", "model"):
            return any(p["direction"] == d for p in task["proposals"])
        if d == "manual":
            return A.get("manual_claims", {}).get("verdict") == "ok"
        if d == "qa":
            return False
        if d == "report":
            return "report_draft" in A
        if d == "flight_request":
            return "flight_notice" in A
        return True

    def _progress(self, task):
        A = task["artifacts"]
        bits = [k for k in A]
        if "route_preview" in A:
            bits.append(f"預覽{'合格' if A['route_preview']['verdict'] == 'pass' else '不合格'}")
        bits += [f"提案:{p['action']}" for p in task["proposals"]]
        return "、".join(bits) or "無"

    def _metrics(self, task):
        """回覆可用的數字：{名稱: (字串值, 出處)}；字串值與模板寫法相同。"""
        out = {}
        rp = task["artifacts"].get("route_preview")
        if rp and rp.get("est_end_pct") is not None:
            out["預估落地電量"] = (f"{rp['est_end_pct']:.1f}", f"預覽 {rp['ref']}")
        return out

    # ---------- 回覆 ----------
    def _template(self, task):
        A = task["artifacts"]
        lines = []
        if "route_preview" in A:
            rp = A["route_preview"]
            lines.append(f"預覽驗算{'合格' if rp['verdict'] == 'pass' else '不合格'}，預估落地電量 "
                         f"{rp['est_end_pct']:.1f}%（出處：預覽 {rp['ref']}）" if rp.get("est_end_pct") is not None
                         else "預覽驗算完成")
        for p in task["proposals"]:
            names = "、".join(self.graph.nodes[i]["name"] for i in p["ids"] if i in self.graph.nodes)
            lines.append(f"已開確認視窗（尚未寫入）：{KIND_ZH[p['direction']]} {names} {''.join(p['params'].values())}")
        if A.get("manual_claims", {}).get("verdict") == "ok":
            for r in A["manual_claims"]["refs"][:3]:
                lines.append(f"手冊出處：{r['manual'].upper()} {r['path']}（{r['heading_path'] or '無標題'}）")
        if "flight_notice" in A:
            lines.append(FLIGHT_NOTICE)
        for d, s in task["dir_status"].items():
            if s not in ("DONE",):
                lines.append(f"{KIND_ZH[d]}：{ {'PENDING_BATCH': '待處理（下一批）', 'NEEDS_USER': '需要你補充', 'WAITING': '等待前一步'}.get(s, '未完成') }")
        return "\n".join(lines) or "完成。"

    def _finish(self, task, status, ask=None):
        t_pre = round(time.monotonic() - task["t0"], 3)       # 提案就緒（整理回覆前）
        template = self._template(task) if ask is None else ask
        reply, reply_src = template, "template"
        metrics = self._metrics(task)                          # 具名、帶出處的數字（CODEX-APP-0405 第 4 點）
        allowed_nums = {v for v, _ in metrics.values()} | set(re.findall(r"\d+(?:\.\d+)?", task["text"]))
        use_llm = self.summary_llm and self.model is not None and ask is None
        if use_llm and len(metrics) > 1:                        # 多個數字時模型可能配錯指標 → 用模板
            use_llm = False
            task["notes"].append("成果含多個數字，整理回覆直接用模板")
        if use_llm:
            def parse(raw):
                obj = default_extract(raw)
                if not isinstance(obj, dict) or list(obj) != ["reply"] or not isinstance(obj["reply"], str):
                    return False, None, "只能有 reply 一個欄位"
                nums = re.findall(r"\d+(?:\.\d+)?", obj["reply"])
                if any(n not in allowed_nums for n in nums):
                    return False, None, "回覆中的數字不是成果欄位的值（要完全相同）"
                if "已寫入" in obj["reply"] or "已套用" in obj["reply"]:
                    return False, None, "提案尚未寫入，不可宣稱已寫入"
                return True, obj["reply"], ""
            r = self._call(task, "summary", "請把以下事實整理成給操作員的繁體中文回覆，只能用這些事實：\n" +
                           template + '\n只輸出 JSON：{"reply":"..."}', parse)
            if r is not None:
                reply, reply_src = r, "model"
        return {"status": status, "reply_zh": reply, "reply_source": reply_src, "proposals": task["proposals"],
                "directions": task["directions"], "dir_status": task["dir_status"], "steps": task["steps"],
                "notes": task["notes"], "calls_used": task["ledger"].used, "traces": task["traces"],
                "retrieval": task.get("retrieval"), "packing": task.get("packing"), "artifacts": task["artifacts"],
                "qv_ok": task.get("qv_ok"), "t_pre_summary_s": t_pre}
