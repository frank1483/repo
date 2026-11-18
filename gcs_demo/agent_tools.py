"""ADR-0002 M3：把 Agent 動作接到真工具（M1 預覽服務、cg-v2、具名區域表）。

依「M3 多方向、真工具接線與資源優先序」演算法說明 v1（使用者 2026-11-17 13:17「同意，照建議」）。
參數都由程式帶：區域（具名區域表，H-10）、home、間距（任務設定）、航高（相對起飛點，Q-08）、
保留電量（句子裡明講的「留／保留 N%」，沒講用機型預設）。模型不填參數。
"""
from __future__ import annotations

import json
import os
import re

from .planner import _to_ll

AREAS = os.path.join(os.path.dirname(__file__), "areas_v1.json")
RESERVE_RE = re.compile(r"(?:保留|留)\s*(\d{1,2}(?:\.\d+)?)\s*[%％]")


def parse_constraints(text):
    m = RESERVE_RE.search(text or "")
    return {"reserve_req_pct": float(m.group(1))} if m else {}


def load_areas(path=AREAS, origin=(24.0, 121.0)):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for a in data["areas"]:
        poly = [dict(zip(("lat", "lon"), _to_ll(origin, tuple(p)))) for p in a["xy_m"]]
        out.append({"id": a["id"], "name": a["name"], "aliases": a.get("aliases", []), "polygon": poly})
    return out


def match_areas(text, areas):
    """回傳句子提到的區域；名稱互為前後綴時取最長的（「北側二」不算「北側」）。"""
    hits = []
    for a in areas:
        for n in [a["name"]] + a["aliases"]:
            for m in re.finditer(re.escape(n), text or ""):
                hits.append((m.start(), m.end(), a))
    keep = []
    for s, e, a in hits:
        if not any(s2 <= s and e <= e2 and (e2 - s2) > (e - s) for s2, e2, _ in hits):
            if a not in keep:
                keep.append(a)
    return keep


class AgentTools(dict):
    """Controller 用的工具表。session_id 為預覽服務的 session；PROPOSE_HOME_ROUTE 只開確認視窗。"""

    def __init__(self, service, principal, session_id, slot_id="home", spacing_m=20.0, areas=None, manual_index=None):
        super().__init__()
        self.svc = service
        self.principal = principal
        self.sid = session_id
        self.slot = slot_id
        self.spacing = spacing_m
        self.areas = areas if areas is not None else load_areas()
        self.constraints = {}
        self.dialogs = []          # 交給 UI 開的確認視窗
        self.drawn = {}            # 使用者框選的 area_ref
        self["bind_task"] = self.bind_task
        self["query_area"] = self.query_area
        self["gen_coverage"] = self.gen_coverage
        self["verify_preview"] = self.verify_preview
        self["propose_home_route"] = self.propose_home_route
        self["qa_lookup"] = lambda text: {"claims": [], "ref": None, "note": "問答工具尚未接上（ADR-0001 §6），回查不到"}
        self["report_draft"] = lambda kinds: {"ref": "report-template", "kinds": kinds}
        if manual_index is not None:                      # rag_index.Index；沒有索引時不提供（回「手冊尚未載入」）
            self["manual_search"] = lambda text: manual_index.search(text)

    def _call(self, fn, body):
        with self.svc.lock:
            return fn(self.principal, self.sid, body)

    def bind_task(self, task):
        self.constraints = parse_constraints(task["text"])

    def query_area(self, text):
        hits = match_areas(text, self.areas)
        if len(hits) == 1:
            return {"status": "ONE", "candidates": [hits[0]["id"]]}
        if len(hits) > 1:
            return {"status": "MANY", "candidates": [h["id"] for h in hits]}
        return {"status": "NONE", "candidates": []}

    def _polygon(self, ref):
        for a in self.areas:
            if a["id"] == ref:
                return {"area": a["polygon"]}
        return {"area_ref": ref}           # 使用者框選（/api/area/submit 回傳的 ref）

    def gen_coverage(self, area_ref):
        from .preview_api import ApiError
        body = dict(self._polygon(area_ref), spacing_m=self.spacing)
        try:
            d = self._call(self.svc.generate, body)
        except ApiError as e:
            return {"status": e.code, "reasons": e.reasons}
        return {"status": "OK", "route_ref": d["route_ref"]}

    def verify_preview(self, route_ref):
        body = {"route_ref": route_ref}
        if "reserve_req_pct" in self.constraints:
            body["reserve_req_pct"] = self.constraints["reserve_req_pct"]
        d = self._call(self.svc.verify, body)
        ev = d["evaluation"]
        return {"preview_ref": d["preview_ref"], "result": ev["result"], "est_end_pct": ev["est_end_pct"],
                "reasons": [r["code"] for r in ev["reasons"]], "takeoff_source": d["takeoff_source"]}

    def propose_home_route(self, preview_ref):
        body = {"preview_ref": preview_ref, "draft_id": "agent-draft", "draft_rev": 1, "target_slot_id": self.slot,
                "target_generation": self.svc.c.word.current().root_gen}
        ch = self._call(self.svc.apply_check, body)["check"]
        self.dialogs.append(ch)            # UI 收到後顯示視窗，按確認才走提交層
        return {"shown_hash": ch["shown_hash"], "decision": ch["decision"]}
