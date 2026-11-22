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
from . import outcomes as OC
from .id_graph import DIRECTION_CATS, line_of, pack

KINDS = ("plan", "ui", "qa", "report", "chat", "manual", "layout", "color", "model", "flight_request")
KIND_DEF = {"plan": "任務規劃：巡檢、航線、覆蓋（例：把東側巡一遍）",
            "ui": "放到首頁：把規劃好的航線或結果放進首頁（例：把東側巡檢結果放到首頁）",
            "qa": "問答：問數值或原因（沒有指定手冊時）", "report": "報告：產生摘要", "chat": "閒聊",
            "manual": "手冊查詢：明確要查 PX4／QGC 手冊或文件",
            "layout": "版面：對某個畫面元件做顯示、隱藏、放大縮小、移動，或調整文字大小（例：把圖例顯示出來）",
            "color": "顏色：主題、深色、淺色、高對比", "model": "模型切換：模型或辨識類別",
            "flight_request": "飛控要求：起飛、降落、返航、拍照等（只回固定說明）"}
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
                 summary_llm=False):
        self.tools = tools
        self.model = model
        self.graph = graph
        self.counter = counter
        self.ledger_cfg = ledger_cfg or {}
        self.steps_max = steps_max or TEST_VALUES["steps_max"]
        self.cap = direction_cap or TEST_VALUES["direction_cap"]
        self.summary_llm = summary_llm

    # ---------- 模型呼叫（經帳本，最多修正一次） ----------
    def _call(self, task, purpose, content, parse, schema=None):
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
            task["decision_seq"] = task.get("decision_seq", 0) + (1 if attempt == 0 else 0)
            call = {"messages": [{"role": "system", "content": task["rules"]}, {"role": "user", "content": msg}],
                    "purpose": purpose, "attempt": attempt, "decision": task["decision_seq"]}
            if schema is not None:                          # v3.6：Ollama JSON Schema 約束結構與候選值
                call["schema"] = schema
            try:
                raw = self.model(call)
            except Exception as e:  # noqa: BLE001
                trace["replies"].append({"error": repr(e)})
                err = "沒有回覆"
                continue
            trace["replies"].append({"raw": (raw or "")[:300]})
            try:
                ok, val, err = parse(raw)
            except Exception as e:  # noqa: BLE001 - 合法 JSON 但型別怪異：當作格式錯誤，走修正／規則備援
                ok, val, err = False, None, f"格式錯誤（{type(e).__name__}）"
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
            task["directions"] = dirs                          # v3.7：超限時也保存補後方向，供計分與 B 共用
            task["notes"].append(f"方向 {len(dirs)} 個超過上限 {self.cap}，請分批")
            return self._finish(task, "PARKED", ask=f"這句話包含 {len(dirs)} 件事，請先選最多 {self.cap} 件")
        task["directions"] = dirs
        if "layout" in dirs:                                 # v3.9 §3：必要版面項目（只用於驗收與退回）
            clear, unclear, conflict = self.split_layout_items(self.parse_layout_items(raw))
            task["layout_items"], task["layout_unclear"], task["layout_conflicts"] = clear, unclear, conflict
            neg = self.parse_layout_items(raw, mode="neg")      # v3.9 v5（0432）：否定與詢問分開
            ask = self.parse_layout_items(raw, mode="ask")
            pos_conf = sorted({(c, p) for c, p, v in clear for nc, np_, nv in neg
                               if (c, p) == (nc, np_) and (nv is None or nv == v)}, key=str)
            if pos_conf:                                   # 同句同值正反都說 → 這一項先詢問、擋住；其他獨立項照常
                task["layout_items"] = [x for x in clear if (x[0], x[1]) not in pos_conf]
                task["layout_conflicts"] = sorted(set(map(tuple, conflict)) | set(pos_conf), key=str)
            task["layout_neg"], task["layout_asked"] = neg, ask
            task["layout_negated"] = neg + ask
        if "plan" in dirs:
            task["area_fixed"], task["area_status"] = self.resolve_area(task)
        qv = self.tools["embed_query"](raw) if "embed_query" in self.tools else None   # 第 1 段之後，1 次
        task["qv_ok"] = qv is not None
        retrieved = {d: self.graph.retrieve(d, qv) for d in dirs}
        task["retrieval"] = {d: retrieved[d]["log"] for d in dirs}
        task["packing"] = {"batches": []}
        task["cands"], task["lines"] = {}, {}
        for d in dirs:
            task["dir_status"][d] = "PENDING_BATCH"
        remaining = list(dirs)
        must = {}
        if "layout" in dirs:                               # v3.10（G19）：原句點名的元件與參數列為必要候選，分批時一起計入預算
            named = []
            for x in list(task.get("layout_items") or []) + list(task.get("layout_unclear") or []) + \
                    list(task.get("layout_conflicts") or []):
                named += [i for i in x[:2] if i]
            must["layout"] = list(dict.fromkeys(named))
        while remaining:                                   # v3.5：每批上限 3,000；每個方向只分配一次
            packed = pack(self.graph, remaining, retrieved, self.counter, must=must)
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
                if d == "layout" and packed["log"].get("must", {}).get(d):
                    task.setdefault("reserved_cands", []).extend(packed["log"]["must"][d])
                    task["notes"].append("原句點名的版面對象列為必要候選：" + "、".join(packed["log"]["must"][d]))
                if d == "plan" and task.get("area_fixed"):  # v3.7：原句唯一指定的區域 → 候選只剩它
                    fx = task["area_fixed"]
                    task["cands"][d] = [fx]
                    task["lines"][d] = [line_of(self.graph.nodes, self.graph.nodes[fx], with_desc=False)]
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
        if "layout" in st and (task.get("layout_unclear") or task.get("layout_conflicts")):
            st["layout"] = "NEEDS_USER"                      # v3.9 修正：缺值或衝突的項目要你補充，不可回 DONE
        if st.get("layout") not in (None, "DONE", "NEEDS_USER") and task.get("layout_items") and \
                any(p["direction"] == "layout" for p in task["proposals"]):
            st["layout"] = "PARTIAL"                         # v3.9：只開了部分版面項目
            task["notes"].append("版面還缺：" + "；".join(f"{c or ''}{'＋' if c else ''}{pp}＝{v}"
                                                           for c, pp, v in self.have(task).get("_layout_missing", [])))
        if any(s == "NEEDS_USER" for s in st.values()):
            status = "PARKED"
        elif all(s == "DONE" for s in st.values()) and st:
            status = "DONE"
        elif any(s in ("DONE", "PARTIAL") for s in st.values()):
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
                return False, None, "directions 只能填這些代碼：" + "、".join(KINDS)
            return True, list(dict.fromkeys(ds)), ""
        content = ("句子：" + task["text"] + "\n方向代碼與意思：\n" + "\n".join(f"- {k}：{KIND_DEF[k]}" for k in KINDS) +
                   "\n請選出這句話需要的方向，依先後排序，只填代碼（例如 color），不要加說明。" +
                   '\n只輸出 JSON：{"directions":["代碼"]}')
        schema = {"type": "object", "properties": {"directions": {"type": "array", "minItems": 1,
                                                                  "items": {"type": "string", "enum": list(KINDS)}}},
                  "required": ["directions"]}
        ds = self._call(task, "stage1", content, parse, schema=schema)
        task["stage1_source"] = "model" if ds is not None else "keyword"
        task["stage1_raw"] = list(ds) if ds is not None else None
        if ds is None:
            ds = [k for k in KINDS if any(w in task["text"] for w in KEYWORDS.get(k, []))] or ["chat"]
            task["notes"].append("第 1 段無效或未呼叫模型，改用關鍵字表")
            task["stage1_raw"] = list(ds)
        ds = self._correct_directions(task, ds)               # v3.9：動作＋對象的明確組合由程式校正（A、B 共用）
        if "ui" in ds and "plan" not in ds and "route_preview" not in task["artifacts"] and self._names_route(task):
            ds.insert(ds.index("ui"), "plan")                 # v3.7：要把航線放首頁但沒有預覽 → 程式補前置規劃
            task["stage1_augmented"] = ["plan"]
            task["notes"].append("要放首頁但缺前置規劃，程式補上 plan 方向")
        if "ui" in ds and "plan" in ds and ds.index("ui") < ds.index("plan"):   # 明確相依：ui 需要 plan 的成果
            ds.remove("ui")
            ds.insert(ds.index("plan") + 1, "ui")
            task["notes"].append("依相依把 ui 排到 plan 之後")
        return ds

    def _ids_of(self, task, d, cat):
        return [i for i in task["cands"].get(d, []) if self.graph.nodes[i]["cat"] == cat]

    strict_params = False      # v3.8：第四輪 A 專用；True 時不收參數的動作 params 必須是空物件（B 不受影響）

    def action_shape(self, task, d, a, strict_params=False):
        """v3.7：動作的 ids／params JSON Schema（A 的逐步與 B 的計畫共用）。"""
        ids = {"type": "array", "maxItems": 0}
        params = ({"type": "object", "properties": {}, "additionalProperties": False} if strict_params
                  else {"type": "object"})
        if a == "QUERY_AREA":                                  # 恰好一個；原句唯一時只剩那一個
            ids = {"type": "array", "items": {"type": "string", "enum": self._ids_of(task, d, "A") or ["A001"]},
                   "minItems": 1, "maxItems": 1}
        elif a == "PROPOSE_HOME_ROUTE":
            ids = {"type": "array", "items": {"type": "string", "enum": ["U100"]}, "minItems": 1, "maxItems": 1}
        elif a == "UI_LAYOUT_PROPOSE":
            cp = self._ids_of(task, d, "C") + self._ids_of(task, d, "P")
            allv = sorted({v for i in task["cands"].get(d, []) for v in (self.graph.nodes[i].get("allowed") or [])})
            ids = {"type": "array", "items": {"type": "string", "enum": cp or ["P001"]}, "minItems": 1, "maxItems": 2}
            params = {"type": "object", "properties": {"value": {"type": "string", "enum": allv or ["大"]}},
                      "required": ["value"]}
        elif a in ("UI_THEME_PROPOSE", "MODEL_SWITCH_PROPOSE"):
            ids = {"type": "array", "items": {"type": "string",
                                              "enum": self._ids_of(task, d, "T" if a == "UI_THEME_PROPOSE" else "M") or ["T001"]},
                   "minItems": 1, "maxItems": 1}
        return ids, params

    LAYOUT_VERBS = ("顯示", "隱藏", "放大", "縮小", "移到", "移動", "關掉", "打開", "調大", "調小", "收起", "展開")
    NEG = ("不要", "別", "不用", "先不", "不必", "不想")
    ASK = ("嗎", "怎麼", "如何", "是什麼", "什麼是", "多少", "？", "?")

    def _clauses(self, text):
        # 問號、驚嘆號跟著前一個子句（保留詢問語氣），其他分隔符號與連接詞直接切開
        return [c.strip() for c in re.split(r"(?<=[？?！!])|[，,。；;、]|然後|並且|並|另外|再|接著|和|跟|以及", text) if c.strip()]

    def _layout_clause(self, c, allow_neg=False):
        """版面子句：版面動詞＋命中元件名稱／別名或文字大小詞；對象是首頁、否定或詢問的不算
        （allow_neg＝不看否定與詢問，只看其他條件；用來找出「不要…」「…怎麼…？」這類不該開提案的版面子句）。"""
        if "首頁" in c or (not allow_neg and (any(w in c for w in self.NEG) or any(w in c for w in self.ASK))):
            return False
        if not any(v in c for v in self.LAYOUT_VERBS) and not re.search(r"[字文].{0,4}[大小]", c):
            return False
        names = [w for n in self.graph.nodes.values() if n["cat"] == "C"
                 for w in [n["name"]] + list(n.get("aliases") or []) if len(w) >= 2]
        return any(w in c for w in names) or bool(re.search(r"(文字|字體|字型|字級|字)", c))

    HOME_PUT = ("放到", "放在", "放上", "放首頁", "顯示在", "顯示到", "加到", "加入", "釘到", "送到", "推到", "貼到", "移到", "擺到")
    HOME_ASK = ("是否", "有沒有", "有無", "是不是", "了沒", "沒有")

    def _home_plan_clause(self, c):
        """把規劃成果放首頁的子句：含首頁與放置動詞（放到、顯示在…），且同句有航線／巡檢／規劃／結果或區域名稱。
        v3.10：詢問（是否、嗎、？…）、否定與手冊查詢都不算。"""
        if "首頁" not in c or any(w in c for w in self.NEG) or any(w in c for w in self.ASK) or \
                any(w in c for w in self.HOME_ASK) or any(w in c for w in self.MANUAL_WORDS) or \
                re.search(r"(?i)\b(qgc|px4)\b", c):
            return False
        if not any(w in c for w in self.HOME_PUT):
            return False
        return any(w in c for w in ("航線", "巡檢", "規劃", "結果", "路線")) or self._names_route_text(c)

    def _plan_clause(self, c):
        """v3.10：獨立的規劃子句：含規劃關鍵字（巡檢、航線、規劃、覆蓋）或區域名稱，且不是否定句。"""
        if any(w in c for w in self.NEG):
            return False
        return any(w in c for w in KEYWORDS["plan"]) or self._names_route_text(c)

    def _names_route_text(self, text):
        return "query_area" in self.tools and self.tools["query_area"](text)["status"] != "NONE"

    def _correct_directions(self, task, ds):
        """v3.9 §1：明確的動作＋對象組合校正 layout／ui；記錄理由。只在有把握的組合動手。"""
        cl = self._clauses(task["text"])
        lay = [c for c in cl if self._layout_clause(c)]
        home = [c for c in cl if self._home_plan_clause(c)] or ([task["text"]] if self._home_plan_clause(task["text"]) else [])
        out, fix = list(ds), []
        if home and "ui" not in out:                     # v3.10（G03）：明確把規劃成果放首頁 → 補 ui；缺預覽由既有 plan 前置補上
            out.append("ui")
            fix.append({"op": "add", "dir": "ui", "why": "把規劃成果放首頁：" + "／".join(home)})
        if lay and "layout" not in out:
            out.append("layout")
            fix.append({"op": "add", "dir": "layout", "why": "版面動詞＋元件／文字：" + "／".join(lay)})
        if lay and not home and "ui" in out:
            out.remove("ui")
            fix.append({"op": "remove", "dir": "ui", "why": "只有版面要求，沒有把規劃成果放首頁"})
        neg = [c for c in cl if self._blocked_clause(c) and self._layout_clause(c, allow_neg=True)]
        if neg and not lay and "layout" in out:            # v3.9 修正：只有否定或詢問的版面子句 → 不留 layout
            out.remove("layout")
            fix.append({"op": "remove", "dir": "layout", "why": "版面子句是否定或詢問：" + "／".join(neg)})
        if home and not lay and "layout" in out:
            out.remove("layout")
            fix.append({"op": "remove", "dir": "layout", "why": "只有把規劃成果放首頁，沒有版面子句：" + "／".join(home)})
        plan_cl = [c for c in cl if c not in lay and self._plan_clause(c)]
        if lay and not home and not plan_cl and "plan" in out:   # v3.10（G02）：只有版面要求、沒有獨立規劃子句 → 移除多選的 plan
            out.remove("plan")
            fix.append({"op": "remove", "dir": "plan", "why": "只有版面要求，沒有規劃子句：" + "／".join(lay)})
        if (lay or home) and "chat" in out:                # v3.10（G02）：已有明確操作時，閒聊不算必要方向
            out.remove("chat")
            fix.append({"op": "remove", "dir": "chat", "why": "已有明確操作，閒聊不列為必要方向"})
        if self._manual_explicit(task["text"]):           # v3.9 §2：明確指定手冊 → manual；沒有獨立問答子句就不留 qa
            if "manual" not in out:
                out.append("manual")
                fix.append({"op": "add", "dir": "manual", "why": "明確指定手冊或文件"})
            if "qa" in out and not any(self._is_question(c) and not self._manual_explicit(c) for c in cl):
                out.remove("qa")
                fix.append({"op": "remove", "dir": "qa", "why": "手冊查詢不重複分到問答"})
        if fix:
            task["stage1_corrections"] = fix
            task["notes"].append("第 1 段方向經程式校正：" + "；".join(f"{f['op']} {f['dir']}" for f in fix))
        return out

    def _blocked_layout(self, task, c, p, v):
        """擋下不該開的版面改動（v3.9 v5，CODEX-APP-0432）：
        - 否定子句（不要…）：值寫明時擋該值、沒寫時擋同元件同參數的任何值；**不會**因為同句有正向要求而放行（同值正反並存已在解析時改成衝突）。
        - 詢問子句（…怎麼…？）：同句有明確的正向要求（同元件、同參數、同值）時放行，否則擋同元件同參數的任何值。"""
        neg = task.get("layout_neg")
        ask = task.get("layout_asked")
        if neg is None and ask is None:                     # 舊欄位相容：只有 layout_negated 時視為詢問與否定合併
            neg, ask = [], task.get("layout_negated") or []
        for bc, bp, bv in neg:
            if (bc, bp) == (c, p) and (bv is None or bv == v):
                return True
        if (c, p, v) in [tuple(x) for x in task.get("layout_items") or []]:
            return False
        for bc, bp, bv in ask:
            if (bc, bp) == (c, p) and (bv is None or bv == v):
                return True
        return False

    def _blocked_clause(self, c):
        return any(w in c for w in self.NEG) or any(w in c for w in self.ASK)

    MANUAL_WORDS = ("手冊", "文件", "文檔", "說明書")

    def _manual_explicit(self, text):
        """v3.9 修正：逐子句判斷；「不要查…手冊」這類否定子句不算指定手冊。"""
        for c in self._clauses(text):
            if any(w in c for w in self.NEG):
                continue
            if any(w in c for w in self.MANUAL_WORDS) or re.search(r"(?i)\b(qgc|px4)\b.*(怎麼|如何|設定|參數|哪裡)", c):
                return True
        return False

    SEG_SPLIT = r"(?<=[？?！!])|[，,。；;]|另外|然後|接著|並且"

    def manual_query(self, text):
        """v3.11：手冊檢索只取手冊子句。用強分隔（標點、另外、然後、接著、並且）切段：
        - 段內明確指定手冊或 QGC／PX4 的技術問法 → 保留；
        - 段內沒有手冊指定，且能明確判定為獨立需求（詢問、版面、規劃、首頁子句）→ 切開，交給其他方向；
        - 其他段落保留（不確定就不切）。只有一段、或切完沒有手冊段時，回原句。回傳 (查詢字串, 切掉的段)。"""
        segs = [x.strip() for x in re.split(self.SEG_SPLIT, str(text or "")) if x and x.strip()]
        if len(segs) <= 1:
            return text, []
        keep, drop = [], []
        for x in segs:
            if self._manual_explicit(x):
                keep.append(x)
            elif self._is_question(x) or self._layout_clause(x) or self._plan_clause(x) or self._home_plan_clause(x):
                drop.append(x)
            else:
                keep.append(x)
        if not drop or not any(self._manual_explicit(x) for x in keep):
            return text, []
        return "，".join(keep), drop

    def _is_question(self, c):
        return any(w in c for w in self.ASK)

    def _manual_source(self, text):
        """v3.9 修正：文件來源看「產品名＋（的）手冊／文件」的組合；沒有這種組合時，只出現一個產品名才限定。
        例：「查 QGC 手冊中怎麼連 PX4」→ qgc（PX4 是內容對象，不是文件來源）。否定子句不算。"""
        pos = [c for c in M4bController._clauses(None, text) if not any(w in c for w in M4bController.NEG)]   # 與 _manual_explicit 同一套切法
        joined = "，".join(pos)
        m = re.findall(r"(?i)(qgc|qgroundcontrol|px4)\s*的?\s*(?:手冊|文件|文檔|說明書)", joined)
        srcs = {("px4" if x.lower() == "px4" else "qgc") for x in m}
        if len(srcs) == 1:
            return srcs.pop()
        if srcs:
            return None
        q, p = bool(re.search(r"(?i)qgc|qgroundcontrol", joined)), bool(re.search(r"(?i)px4", joined))
        return "qgc" if q and not p else ("px4" if p and not q else None)

    def _names_route(self, task):
        """原句明確指向某條航線：提到區域名稱／別名，或含規劃關鍵字。"""
        if "query_area" in self.tools and self.tools["query_area"](task["text"])["status"] != "NONE":
            return True
        return any(w in task["text"] for w in KEYWORDS["plan"])

    def resolve_area(self, task):
        """v3.7 §1：原句能唯一比對到一個區域 → 程式定下該區域節點；比對不到或多個 → None 並記狀態。"""
        if "query_area" not in self.tools:
            return None, "NO_TOOL"
        q = self.tools["query_area"](task["text"])
        if q["status"] == "ONE":
            ids = [i for i, n in self.graph.nodes.items() if n.get("area") == q["candidates"][0]]
            return (ids[0] if ids else None), "ONE"
        return None, q["status"]

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
    def have(self, task):
        return OC.have_from(task["artifacts"], task["proposals"], task.get("layout_items"))

    POS = ("左上", "右上", "左下", "右下", "中央")

    def parse_layout_items(self, text, negated=False, mode=None):
        """v3.9 §3：從原句的「動作＋對象」解析必要版面項目 (元件或 None, 參數, 值)。只用於驗收與退回；
        目標或值不明 → 值為 None（該項需要使用者補充）；解析不出任何項目 → 回 []（沿用「至少一張」的判定）。"""
        items = []
        comps = sorted(((w, n["id"]) for n in self.graph.nodes.values() if n["cat"] == "C"
                        for w in [n["name"]] + list(n.get("aliases") or []) if len(w) >= 2), key=lambda x: -len(x[0]))
        for c in self._clauses(text):
            if negated or mode:                            # 只看否定（mode="neg"）或詢問（mode="ask"）的版面子句；negated＝兩者都看
                kind = (any(w in c for w in self.NEG) if mode == "neg" else
                        any(w in c for w in self.ASK) and not any(w in c for w in self.NEG) if mode == "ask" else
                        self._blocked_clause(c))
                if not (kind and self._layout_clause(c, allow_neg=True)):
                    continue
            elif not self._layout_clause(c):
                continue
            hit = next(((w, i) for w, i in comps if w in c), None)
            cid = hit[1] if hit else None
            if hit:                                        # 元件名稱本身含動詞字（例：高度顯示）→ 判斷動作時先去掉名稱
                c = c.replace(hit[0], "")
            if cid and self.graph.nodes[cid].get("locked") and any(v in c for v in ("隱藏", "關掉", "收起")):
                continue                                   # 鎖定元件不可隱藏：不列為必要項目（程式照舊擋下）
            if cid is None and re.search(r"(文字|字體|字型|字級|字)", c):
                val = "特大" if "特大" in c else ("大" if re.search(r"大", c) else ("小" if "小" in c else ("中" if "中" in c else None)))
                items.append((None, "P001", val))
                continue
            if cid is None:
                continue
            if any(v in c for v in ("顯示", "打開", "展開")):
                items.append((cid, "P004", "顯示"))
            elif any(v in c for v in ("隱藏", "關掉", "收起")):
                items.append((cid, "P004", "隱藏"))
            elif any(v in c for v in ("放大", "調大")):
                items.append((cid, "P002", "放大"))
            elif any(v in c for v in ("縮小", "調小")):
                items.append((cid, "P002", "縮小"))
            elif any(v in c for v in ("移到", "移動")):
                items.append((cid, "P003", next((x for x in self.POS if x in c), None)))
        out = []
        for x in items:                                   # 同一改動重複提只算一項
            if x not in out:
                out.append(x)
        return out

    def split_layout_items(self, items):
        """把解析結果分成：明確項目、缺值項目（目標或值不明）、衝突（同一元件同一參數要了不同的值）。"""
        vals = {}
        for c, pp, v in items:
            vals.setdefault((c, pp), set()).add(v)
        conflict = {k for k, vs in vals.items() if len({v for v in vs if v is not None}) > 1}
        clear = [x for x in items if x[2] is not None and (x[0], x[1]) not in conflict]
        unclear = [x for x in items if x[2] is None and (x[0], x[1]) not in conflict]
        return clear, unclear, sorted(conflict, key=str)

    def _run_direction(self, task, d, qv):
        if d == "plan" and task.get("area_status") in ("MANY", "NONE") and "area_record" not in task["artifacts"]:
            task["notes"].append("原句沒有唯一指定區域" + ("（比對到多個）" if task["area_status"] == "MANY" else "（比對不到）") +
                                 "，請框選或指名")
            task["dir_status"][d] = "NEEDS_USER"
            return
        steps = 0
        while steps < self.steps_max:
            have = self.have(task)
            if not OC.missing(d, have):                       # v3.6：必要成果已齊（或合法略過）→ 程式結束本方向
                task["dir_status"][d] = "DONE" if self._dir_done(task, d) else "INCOMPLETE"
                return
            can = OC.executable(d, ACTIONS[d], have)
            redo = [a for a in ACTIONS[d] if a not in can and all(n in have for n in OC.NEEDS.get(a, []))
                    and OC.PRODUCES.get(a) in have]               # 產物已有：只允許換目標、參數或輸入後重做
            if not can:
                task["notes"].append(f"{KIND_ZH[d]}：還缺 {'、'.join(OC.ZH[k] for k in OC.missing(d, have))}，但沒有可做的動作")
                task["dir_status"][d] = "INCOMPLETE"
                return
            steps += 1
            allowed = can + redo + ["FINISH", "HOLD"]
            cands = task["cands"].get(d, [])
            content = (f"句子：{task['text']}\n方向：{d}（{KIND_ZH[d]}）\n可用 ID：\n" +
                       ("\n".join(task["lines"].get(d, [])) or "（無）") +
                       "\n目前狀態：\n" + OC.summary([d], have) +
                       "\n現在能做的動作：\n" + "\n".join(f"- {a}：{OC.ACTION_ZH[a]}" for a in can) +
                       ("".join(f"\n- {a}：已完成（目前：{have.get(OC.PRODUCES[a])}）；只有換目標或參數才可再做，"
                                f"重做後依賴它的後續成果會作廢、要重算" for a in redo)) +
                       "\n- FINISH：本方向結束\n- HOLD：無法安全處理，停下\n"
                       '只輸出 JSON：{"action":"動作代碼","ids":["ID"],"params":{}}')
            schema = {"anyOf": [{"type": "object", "properties": dict(
                zip(("ids", "params"), self.action_shape(task, d, a, strict_params=self.strict_params)), action={"type": "string", "enum": [a]}),
                "required": ["action", "ids", "params"]} for a in allowed]}      # v3.7：每個動作一種形狀
            step = self._call(task, f"step:{d}", content, lambda raw: self._parse_step(task, d, raw, allowed),
                              schema=schema)
            source = "model" if step is not None else "rule"
            if step is None:
                step = self._rule_step(task, d)
            task["steps"].append(dict(step, direction=d, source=source))
            task["cur_by"] = source
            if step["action"] == "HOLD":
                task["dir_status"][d] = "FAILED_SAFE"
                return
            if step["action"] == "FINISH":
                task["dir_status"][d] = "DONE" if self._dir_done(task, d) else "INCOMPLETE"
                return
            if step["action"] not in ("FINISH", "HOLD"):
                task.setdefault("sigs", set()).add(self._sig(step, have))
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
        if not isinstance(a, str) or a not in allowed:
            return False, None, f"動作 {a} 現在不能做；現在能做的動作只有：{'、'.join(allowed)}"
        ids = obj.get("ids", [])
        params = obj.get("params", {})
        ids = [] if ids is None else ids
        params = {} if params is None else params
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return False, None, "ids 必須是字串清單"
        if not isinstance(params, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in params.items()):
            return False, None, "params 必須是字串對字串"
        cands = set(task["cands"].get(d, []))
        for i in ids:
            if i not in cands:
                return False, None, f"{i} 不在本次候選"
        err = self.check_schema(a, ids, params)
        if err:
            return False, None, err
        step = {"action": a, "ids": ids, "params": params}
        if a == "UI_LAYOUT_PROPOSE":                       # v3.9 修正：否定、缺值、衝突的項目在解析時就退回，讓其他項目可以繼續
            c0 = ([i for i in ids if i.startswith("C")] or [None])[0]
            p0 = ([i for i in ids if i.startswith("P")] or [None])[0]
            if self._blocked_layout(task, c0, p0, params.get("value")):
                return False, None, "原句說不要這個改動，不可開提案；請做其他還缺的項目或 FINISH"
            if (c0, p0) in [(x[0], x[1]) for x in (task.get("layout_unclear") or [])] or                     (c0, p0) in [tuple(x) for x in task.get("layout_conflicts") or []]:
                return False, None, "這一項原句沒講清楚或互相衝突，要請使用者補充，不可自己決定；請做其他還缺的項目或 FINISH"
            bad = self._layout_mismatch(task, c0, p0, params.get("value"))
            if bad:
                return False, None, bad
        if a not in ("FINISH", "HOLD") and self._sig(step, self.have(task)) in task.get("sigs", set()):
            return False, None, f"{a}（同一目標、參數與輸入）已經做過；請選下一個還缺的成果的動作"
        return True, step, ""

    def _layout_mismatch(self, task, c, p, v):
        """v3.10（G19）：開窗前核對元件、參數、值是否符合原句的明確需求，並按這三項去重。符合回空字串。"""
        if (c, p, v) in [OC.layout_key(x) for x in task.get("proposals") or [] if x.get("direction") == "layout"]:
            return "這個版面改動（同元件、參數、值）已經開過確認視窗；請做其他還缺的項目或 FINISH"
        clear = [tuple(x) for x in task.get("layout_items") or []]
        named = {(x[0], x[1]) for x in clear + [tuple(y) for y in task.get("layout_unclear") or []]} | \
            {tuple(x) for x in task.get("layout_conflicts") or []}
        if not named or (c, p) in {(x[0], x[1]) for x in task.get("layout_unclear") or []} or \
                (c, p) in {tuple(x) for x in task.get("layout_conflicts") or []}:
            return ""                                  # 原句沒解析出明確項目：沿用舊判定；缺值、衝突另有處理
        if (c, p, v) in clear:
            return ""
        want = "；".join(f"{x[0] + '＋' if x[0] else ''}{x[1]}，value＝{x[2]}" for x in clear)
        return f"不符合原句的明確需求（{c + '＋' if c else ''}{p}，value＝{v}）；原句要的是：{want}"

    def _sig(self, step, have):
        """去重鍵（v2，CODEX-APP-0413 第 2 點）：同一動作、同一目標與參數、同一輸入狀態。"""
        return (step["action"], tuple(sorted(step["ids"])), tuple(sorted(step["params"].items())),
                OC.input_sig(step["action"], have))

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
            return "" if ids == ["U100"] else "首頁提案的 ids 要剛好是 [\"U100\"]"
        if a == "QUERY_AREA":                                # v3.7：恰好一個區域；多個是格式錯誤
            return "" if cats == ["A"] else "區域查詢要剛好一個區域 ID（A），不可以一次填多個"
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
        if d == "layout" and task.get("layout_items"):         # v3.9：規則備援按缺項逐一補
            miss = [x for x in self.have(task).get("_layout_missing", []) if x[2]]
            if not miss:
                return {"action": "FINISH", "ids": [], "params": {}}
            c, pp, v = miss[0]
            return {"action": "UI_LAYOUT_PROPOSE", "ids": ([c] if c else []) + [pp], "params": {"value": v}}
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
            if (A.get("area_record") or {}).get("id") not in (None, areas[0]):   # v3：換區 → 舊航點與舊預覽失效
                for k in ("coverage_route", "route_preview"):
                    if k in A:
                        task.setdefault("invalidated", []).append({k: A.pop(k), "reason": "區域改變"})
            A["area_record"] = {"kind": "area_record", "ref": self.graph.nodes[areas[0]]["area"], "id": areas[0]}
            return "OK"
        if a == "GEN_COVERAGE":
            if "area_record" not in A:
                return "BLOCKED"
            r = T["gen_coverage"](A["area_record"]["ref"])
            if r["status"] != "OK":
                return "BLOCKED"
            if "route_preview" in A:                         # v3：航點重算 → 舊預覽失效
                task.setdefault("invalidated", []).append({"route_preview": A.pop("route_preview"), "reason": "航點改變"})
            A["coverage_route"] = {"kind": "coverage_route", "ref": r["route_ref"], "area_id": A["area_record"]["id"]}
            return "OK"
        if a == "VERIFY_PREVIEW":
            if "coverage_route" not in A:
                return "BLOCKED"
            r = T["verify_preview"](A["coverage_route"]["ref"])
            A["route_preview"] = {"kind": "route_preview", "ref": r["preview_ref"], "verdict": r["result"],
                                  "est_end_pct": r.get("est_end_pct"), "route_ref": A["coverage_route"]["ref"]}
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
            self._propose(task, d, a, ["U100"], {}, r.get("shown_hash"),
                          source={"preview_ref": A["route_preview"]["ref"], "verdict": A["route_preview"]["verdict"]})
            return "OK"
        if a == "UI_LAYOUT_PROPOSE":
            cs = [i for i in ids if self.graph.nodes[i]["cat"] == "C"]
            ps = [i for i in ids if self.graph.nodes[i]["cat"] == "P"]
            if not ps:
                return "BLOCKED"
            if ps[0] == "P004" and cs and self.graph.nodes[cs[0]].get("locked") and params.get("value") == "隱藏":
                task["notes"].append("鎖定元件不可隱藏")
                return "BLOCKED"
            ck = (cs[0] if cs else None, ps[0])
            if self._blocked_layout(task, ck[0], ck[1], params.get("value")):
                task["notes"].append("原句說不要這個版面改動，不開確認視窗")
                return "BLOCKED"
            if ck in [tuple(x) for x in task.get("layout_conflicts") or []]:
                task["notes"].append(f"{ck[0] or ''}{'＋' if ck[0] else ''}{ck[1]}：原句要了互相衝突的值，請你確認")
                return "NEEDS_USER"
            bad = self._layout_mismatch(task, ck[0], ck[1], params.get("value"))
            if bad:                                         # v3.10（G19）：開窗前最後一道核對
                task["notes"].append("版面提案退回：" + bad)
                return "BLOCKED"
            if ck in [(x[0], x[1]) for x in task.get("layout_unclear") or []]:
                task["notes"].append(f"{ck[0] or ''}{'＋' if ck[0] else ''}{ck[1]}：原句沒有講清楚要調成什麼，請你補充")
                return "NEEDS_USER"
            self._propose(task, d, a, cs + ps, params, None)
            return "OK"
        if a in ("UI_THEME_PROPOSE", "MODEL_SWITCH_PROPOSE"):
            need = "T" if a == "UI_THEME_PROPOSE" else "M"
            xs = [i for i in ids if self.graph.nodes[i]["cat"] == need]
            self._propose(task, d, a, xs, {}, None)
            return "OK"
        if a == "MANUAL_SEARCH":
            src = self._manual_source(task["text"])         # v3.9 §2：指定 QGC／PX4 時限定來源，查詢端詞表 v2
            from .rag_index import QUERY_GLOSSARY_V3, RAG_SETTINGS, vector_query_text   # v3.10 詞表 v3；v3.11 子句與英文詞
            mq, dropped = self.manual_query(task["text"]) if RAG_SETTINGS.get("manual_clause") else (task["text"], [])
            vt = vector_query_text(mq, QUERY_GLOSSARY_V3) if RAG_SETTINGS.get("vector_en") else mq
            vv = qv if vt == task["text"] else (T["embed_query"](vt) if "embed_query" in T else None)
            task["manual_query"] = {"lexical": mq, "vector": vt, "dropped": dropped, "vector_reused": vt == task["text"]}
            r = T["manual_search"](mq, vv, manual=src, extra=QUERY_GLOSSARY_V3) if "manual_search" in T \
                else {"results": [], "status": "NOT_LOADED"}
            if src and not r.get("results"):
                task["notes"].append(f"指定的 {src.upper()} 手冊查無可用出處")
            A["manual_claims"] = {"kind": "manual_claims", "verdict": "ok" if r.get("results") else "not_found",
                                  "refs": [{k: x[k] for k in ("manual", "path", "heading_path", "version", "chunk_id")}
                                           | {"excerpt": x["text"][:400]} for x in r.get("results", [])],
                                  "degraded": r.get("degraded"), "degraded_reason": r.get("degraded_reason"),
                                  "query": task["manual_query"]}
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

    def _propose(self, task, d, action, ids, params, ref, source=None):
        task["proposals"].append({"direction": d, "action": action, "ids": list(ids), "params": dict(params),
                                  "state": "PROPOSED", "ref": ref, "source": source, "by": task.get("cur_by", "rule"),
                                  "t_ready_s": round(time.monotonic() - task["t0"], 3)})

    def _dir_done(self, task, d):
        A = task["artifacts"]
        if d == "plan":
            return bool(A.get("route_preview") and A["route_preview"].get("verdict") == "pass")
        if d == "layout" and task.get("layout_items"):
            return "layout_proposal" in self.have(task)
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
        nm = lambda c, pp: "、".join(self.graph.nodes[i]["name"] for i in (c, pp) if i)  # noqa: E731
        for c, pp, v in self.have(task).get("_layout_missing", []):   # v3.9 修正：缺項寫進給操作員的回覆
            lines.append(f"版面還缺（尚未開窗）：{nm(c, pp)} {v}")
        for c, pp, _ in task.get("layout_unclear") or []:
            lines.append(f"版面需要你補充：{nm(c, pp)} 要調成什麼？")
        for c, pp in task.get("layout_conflicts") or []:
            lines.append(f"版面需要你確認：{nm(c, pp)} 同一句裡要了不同的值")
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
                "qv_ok": task.get("qv_ok"), "t_pre_summary_s": t_pre, "stage1_source": task.get("stage1_source"), "stage1_augmented": task.get("stage1_augmented"), "stage1_raw": task.get("stage1_raw"),
                "stage1_corrections": task.get("stage1_corrections"),
                "area_status": task.get("area_status"), "area_fixed": task.get("area_fixed"),
                "outcomes": OC.have_from(task["artifacts"], task["proposals"])}
