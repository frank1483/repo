"""ADR-0002 M1 預覽端點與框選區域（另開伺服器，127.0.0.1:8766；不改 server.py）。

依「演算法說明 v1：預覽端點與框選區域」（adr0002_algo/預覽端點_演算法說明_v1.md，使用者 2026-11-17 08:57「是」）。
- 檢查順序照 ADR-0001 §11：標頭大小 → Host／Origin → 路徑與方法 → token → 長度 → body → JSON → schema → 准入。
- 不送任何 CORS 標頭；只收 POST。token 只在記憶體。
- 讀任務狀態只在 SESSION.lock 內拷貝（最多等 200 ms），計算在鎖外；套用一律走提交層（commit_layer）。
數值都是測試用值。
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import coverage as cv
from . import commit_layer as cl
from .energy import Vehicle, Wind
from .planner import _to_xy
from .planner_t3 import _canonical
from .route_recheck import make_route_recheck

TW = timezone(timedelta(hours=8))
TEST_VALUES = {"lock_wait_s": 0.2, "header_cap": 8192, "max_area_vertices": 50, "max_area_diameter_m": 5000.0,
               "max_home_distance_m": 20000.0, "max_redisplay": 2, "label_max": 40,
               "confirm_token_ttl_s": 600.0}    # G0-11：確認權杖期限（測試值 10 分鐘，待凍結）
BODY_CAP = {"/api/session/open": 1024, "/api/area/submit": 16384, "/api/preview/generate": 65536,
            "/api/preview/verify": 16384, "/api/preview/get": 4096, "/api/preview/apply_check": 8192,
            "/api/preview/presented": 8192, "/api/preview/commit": 8192,
            "/api/preview/transaction/get": 4096, "/api/preview/undo": 4096,
            "/api/agent/request": 16384, "/api/agent/resume": 16384, "/api/agent/task/get": 4096,
            "/api/agent/cancel": 4096}
COMMON = {"boot_epoch": "int", "request_epoch": "int"}
SCHEMA = {
    "/api/session/open": ({}, {}),
    "/api/area/submit": ({"session_id": "str", "polygon": "geo_list"}, {"task_id": "str", "label": "str"}),
    "/api/preview/generate": ({"session_id": "str"},
                              {"task_id": "str", "area_ref": "str", "area": "geo_list", "home": "geo",
                               "spacing_m": "num", "alt": "num", "angle_deg": "num"}),
    "/api/preview/verify": ({"session_id": "str", "route_ref": "str"},
                            {"task_id": "str", "planned_takeoff_pct": "num", "reserve_req_pct": "num"}),
    "/api/preview/get": ({"session_id": "str", "artifact_id": "str"}, {}),
    "/api/preview/apply_check": ({"session_id": "str", "preview_ref": "str", "draft_id": "str", "draft_rev": "int",
                                  "target_slot_id": "str", "target_generation": "int"}, {"task_id": "str"}),
    "/api/preview/presented": ({"session_id": "str", "shown_hash": "str", "apply_intent_id": "str",
                                "target_slot_id": "str", "window_id": "str", "frame_id": "str"}, {}),
    "/api/preview/commit": ({"session_id": "str", "target_slot_id": "str", "nonce": "str", "apply_intent_id": "str",
                             "shown_hash": "str", "confirm_token": "str"}, {}),
    "/api/preview/transaction/get": ({"session_id": "str", "transaction_id": "str", "target_slot_id": "str"}, {}),
    "/api/preview/undo": ({"session_id": "str", "target_slot_id": "str", "target_generation": "int",
                           "transaction_id": "str", "nonce": "str"}, {}),
    # M3：Agent 端點（同樣的 token、檢查順序與封閉 schema）。text 超過 200 字由 Gate 回 TOO_LONG，不截斷。
    "/api/agent/request": ({"session_id": "str", "text": "text"}, {}),
    "/api/agent/resume": ({"session_id": "str", "task_id": "str"}, {"answers": "answers", "text": "text"}),
    "/api/agent/task/get": ({"session_id": "str", "task_id": "str"}, {}),
    "/api/agent/cancel": ({"session_id": "str", "task_id": "str"}, {}),
}
HTTP_OF = {"AUTH_MISSING": 401, "AUTH_INVALID": 401, "HOST_DENIED": 403, "ORIGIN_DENIED": 403,
           "AREA_BINDING_MISMATCH": 403, "NOT_FOUND": 404, "METHOD_DENIED": 405, "BODY_TOO_LARGE": 413,
           "HEADER_TOO_LARGE": 431, "SCHEMA_UNKNOWN_FIELD": 400, "SCHEMA_TYPE": 400, "NONFINITE": 400,
           "EPOCH_STALE": 409, "BUSY_RETRY": 503}


class ApiError(Exception):
    def __init__(self, code, reasons=None, hint=None):
        super().__init__(code)
        self.code, self.reasons, self.hint = code, reasons or [], hint


def _sha(o):
    return hashlib.sha256(_canonical(o).encode("ascii")).hexdigest()


def _check_type(v, t):
    if t == "str":
        return isinstance(v, str) and 0 < len(v) <= 200
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "num":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        if not math.isfinite(v):
            raise ApiError("NONFINITE")
        return True
    if t == "text":
        return isinstance(v, str) and 0 < len(v) <= 1000
    if t == "answers":
        return (isinstance(v, list) and 0 < len(v) <= 8 and all(
            isinstance(a, dict) and set(a) == {"field", "value"} and a["field"] in
            ("boundary", "area_choice", "cancel_confirm") and isinstance(a["value"], (str, bool)) for a in v))
    if t == "geo":
        return (isinstance(v, dict) and set(v) == {"lat", "lon"} and all(_check_type(v[k], "num") for k in v)
                and -90 <= v["lat"] <= 90 and -180 <= v["lon"] <= 180)
    if t == "geo_list":
        return isinstance(v, list) and 0 < len(v) <= TEST_VALUES["max_area_vertices"] and all(_check_type(p, "geo") for p in v)
    return False


def validate(path, body):
    if not isinstance(body, dict):
        raise ApiError("SCHEMA_TYPE", ["body"])
    req, opt = SCHEMA[path]
    req = dict(COMMON, **req)
    unknown = set(body) - set(req) - set(opt)
    if unknown:
        raise ApiError("SCHEMA_UNKNOWN_FIELD", sorted(unknown))
    for k, t in req.items():
        if k not in body or not _check_type(body[k], t):
            raise ApiError("SCHEMA_TYPE", [k])
    for k, t in opt.items():
        if k in body and not _check_type(body[k], t):
            raise ApiError("SCHEMA_TYPE", [k])


# ---------------- 任務狀態 → 安全入站 ----------------

class SessionFeeder:
    """在 SESSION.lock 內拷貝快照（最多等 lock_wait_s），比較後送入提交層的安全入站。"""

    def __init__(self, session, coordinator: cl.Coordinator):
        self.s = session
        self.c = coordinator
        self.last = None
        self.waits = []

    def snapshot(self):
        t0 = time.monotonic()
        if not self.s.lock.acquire(timeout=TEST_VALUES["lock_wait_s"]):
            self.waits.append(time.monotonic() - t0)
            raise ApiError("BUSY_RETRY", ["任務執行中，稍後再試"])
        try:
            m = copy.deepcopy(self.s.mission)
            w = {"speed_mps": self.s.wind.speed_mps, "from_deg": self.s.wind.from_deg}
            v = self.s.vehicle().to_dict()
            cs = copy.deepcopy(self.s.current_state)
        finally:
            self.s.lock.release()
        self.waits.append(time.monotonic() - t0)
        batt = cs.get("battery_pct") if isinstance(cs, dict) else None
        return {"mission": m, "wind": w, "vehicle": v,
                "battery": float(batt) if batt is not None else None,
                "battery_source": "telemetry" if batt is not None else "planned"}

    def poll(self):
        snap = self.snapshot()
        m = snap["mission"]
        src = {"no_fly": m.get("no_fly", []), "policy": {"version": "policy-test-1"},
               "limits": {"reserve_req_pct": m.get("reserve_req_pct", 20.0),
                          "max_alt_m": m.get("limits", {}).get("max_altitude_m", 120)},
               "area": {"mission": m.get("name")}, "vehicle": snap["vehicle"],
               "battery": snap["battery"] if snap["battery"] is not None else 100.0,   # Q-05：沒有遙測用 100% 預計值
               "wind": snap["wind"], "position": (0.0, 0.0)}
        for k, v in src.items():
            if self.last is None or self.last.get(k) != v:
                if k in cl.CONTINUOUS_SOURCES and self.last is not None:
                    self.c.ingest.sample(k, v)
                else:
                    self.c.ingest.event(k, v)
        self.last = src
        return snap


# ---------------- 服務邏輯 ----------------

class PreviewService:
    def __init__(self, coordinator: cl.Coordinator, feeder: SessionFeeder, evidence_path, boot_epoch=None):
        self.c = coordinator
        self.feeder = feeder
        self.store = cv.PreviewStore(evidence_path)
        self.boot_epoch = boot_epoch if boot_epoch is not None else int(time.time())
        self.lock = threading.RLock()   # Agent 工具在同一程序內呼叫時可重入
        self.sessions = {}        # session_id → {principal, last_epoch}
        self.areas = {}           # area_ref → AreaRecord
        self.routes = {}          # route_ref → generate output
        self.previews = {}        # artifact_id → record
        self.shown = {}           # shown_hash → {check, preview, slot, intent, draft}
        self.tokens = {}          # confirm_token → {shown_hash, slot, intent, state, expires, preview}
        self.tok_lock = threading.Lock()   # G0-9／G0-11：權杖狀態只在這把小鎖內改（不經 self.lock，生產端可直接撤銷）
        self.now = time.monotonic          # 服務端單調時鐘（測試可替換）
        self.current_preview = {}  # (principal, slot, draft_id) → (preview_ref, draft_rev)
        self.superseded = {}       # preview_ref → reason
        self.intents = {}         # apply_intent_id → {redisplays}
        self.idem = {}            # (principal, boot, slot, nonce) → result
        self.seq = 0
        self.controller = None    # M3：attach_controller() 之後才提供 /api/agent/*
        self.task_owner = {}      # task_id → session_id

    def attach_controller(self, controller):
        self.controller = controller

    # --- 共用
    def _session(self, principal, body):
        s = self.sessions.get(body["session_id"])
        if s is None or s["principal"] != principal:
            raise ApiError("AUTH_INVALID", ["session"])
        if body["boot_epoch"] != self.boot_epoch or body["request_epoch"] < s["last_epoch"]:
            raise ApiError("EPOCH_STALE")
        s["last_epoch"] = body["request_epoch"]
        return s

    def dispatch(self, path, principal, body):
        if path == "/api/session/open":
            if body["boot_epoch"] != self.boot_epoch:
                raise ApiError("EPOCH_STALE")
            sid = "s-" + secrets.token_hex(8)
            self.sessions[sid] = {"principal": principal, "last_epoch": body["request_epoch"]}
            return {"session_id": sid}
        sess = self._session(principal, body)
        fn = {"/api/area/submit": self.area_submit, "/api/preview/generate": self.generate,
              "/api/preview/verify": self.verify, "/api/preview/get": self.get,
              "/api/preview/apply_check": self.apply_check, "/api/preview/presented": self.presented,
              "/api/preview/commit": self.commit, "/api/preview/transaction/get": self.transaction_get,
              "/api/preview/undo": self.undo, "/api/agent/request": self.agent_request,
              "/api/agent/resume": self.agent_resume, "/api/agent/task/get": self.agent_get,
              "/api/agent/cancel": self.agent_cancel}[path]
        with self.lock:
            return fn(principal, body["session_id"], body)

    # --- 框選區域（E-2、F-5、B-1）
    def area_submit(self, principal, sid, b):
        poly = b["polygon"]
        label = b.get("label")
        if label is not None and len(label) > TEST_VALUES["label_max"]:
            raise ApiError("SCHEMA_TYPE", ["label"])
        if len(poly) < 3:
            raise ApiError("INVALID", ["頂點少於 3"])
        o = (poly[0]["lat"], poly[0]["lon"])
        xy = [_to_xy(o, (p["lat"], p["lon"])) for p in poly]
        if abs(cv._area(xy)) < 1e-6 or cv._self_intersecting(xy):
            raise ApiError("INVALID", ["面積為 0 或自我交叉"])
        if not cv._is_convex(xy):
            raise ApiError("UNSUPPORTED_CONCAVE")
        diam = max(math.dist(a, c) for a in xy for c in xy)
        if diam > TEST_VALUES["max_area_diameter_m"]:
            raise ApiError("LIMIT_EXCEEDED", ["直徑"])
        snap = self.feeder.snapshot()
        home = snap["mission"].get("home")
        home_check = "PENDING"
        if home:
            hd = max(math.dist(_to_xy((home["lat"], home["lon"]), (p["lat"], p["lon"])), (0, 0)) for p in poly)
            if hd > TEST_VALUES["max_home_distance_m"]:
                raise ApiError("LIMIT_EXCEEDED", ["與 home 距離"])
            home_check = "OK"
        self.seq += 1
        name = label or "框選區域 " + datetime.now(TW).strftime("%Y%m%d-%H%M") + f"-{self.seq}"
        object_id = f"area-{self.seq}-{secrets.token_hex(4)}"
        rec = {"name": name, "polygon": poly, "origin": {"provider_id": "user_drawn", "object_id": object_id,
                                                          "revision": 1}}
        rec["origin"]["digest"] = _sha({"polygon": poly, "provider_id": "user_drawn", "object_id": object_id,
                                        "revision": 1})
        rec["binding"] = {"principal_id": principal, "session_id": sid, "task_id": b.get("task_id")}
        ref = object_id
        self.areas[ref] = rec
        return {"area_ref": ref, "name": name,
                "checks": {"convex": True, "vertices": len(poly), "diameter_m": diam, "home_distance": home_check}}

    def _area_for(self, principal, sid, b):
        if "area_ref" in b and "area" in b:
            raise ApiError("SCHEMA_TYPE", ["area_ref 與 area 擇一"])
        if "area_ref" in b:
            rec = self.areas.get(b["area_ref"])
            if rec is None:
                raise ApiError("NOT_FOUND", ["area_ref"])
            bd = rec["binding"]
            if bd["principal_id"] != principal or bd["session_id"] != sid or \
                    (bd["task_id"] and b.get("task_id") and bd["task_id"] != b.get("task_id")):
                raise ApiError("AREA_BINDING_MISMATCH")
            return rec["polygon"]
        if "area" in b:
            return b["area"]
        raise ApiError("MISSING", ["area"])

    # --- 生成與驗算
    def generate(self, principal, sid, b):
        area = self._area_for(principal, sid, b)
        snap = self.feeder.poll()
        m = snap["mission"]
        home = b.get("home") or ({"lat": m["home"]["lat"], "lon": m["home"]["lon"]} if m.get("home") else None)
        if home is None:
            raise ApiError("MISSING", ["home"])
        spacing = b.get("spacing_m", m.get("spacing_m"))      # 明講值優先（E-11）
        g = cv.coverage_generate(area=area, home=home, spacing_m=spacing, alt_m=b.get("alt", m.get("cruise_alt_m")),
                                 angle_deg=b.get("angle_deg"), no_fly=m.get("no_fly", []))
        if g["status"] != "OK":
            raise ApiError(g["status"], g.get("missing") or [g.get("reason", "")])
        self.routes[g["route_id"]] = g
        return {"route_ref": g["route_id"], "stats": g["stats"], "saved": False}

    def verify(self, principal, sid, b):
        g = self.routes.get(b["route_ref"])
        if g is None:
            raise ApiError("NOT_FOUND", ["route_ref"])
        snap = self.feeder.poll()
        m = snap["mission"]
        planned = b.get("planned_takeoff_pct", 100.0)
        if snap["battery"] is not None:
            takeoff, src = min(snap["battery"], planned), "telemetry_or_planned_min"   # S-08
        else:
            takeoff, src = planned, "planned"                                          # Q-05
        reserve = b.get("reserve_req_pct", m.get("reserve_req_pct", 20.0))
        rec = cv.preview_check(g, Vehicle(**{k: v for k, v in snap["vehicle"].items() if k != "airframe_profile"}),
                               Wind(**snap["wind"]), takeoff, reserve, m.get("no_fly", []),
                               max_alt_m=m.get("limits", {}).get("max_altitude_m", 120),
                               created_at=datetime.now(TW).isoformat())
        rec["takeoff_source"] = src
        # F-4（G1 範圍 B）：預覽 ID 帶目前的證據世代（boot_epoch）。內容雜湊 preview_version 不變（AC-9 照舊可重算），
        # 但不同世代驗算出的預覽一定是新 ID；舊世代的預覽只能唯讀查看（get），不能直接 apply_check。
        rec["artifact_id"] = f"rp-e{self.boot_epoch}-" + rec["preview_version"].split(":")[1][:16]
        rec["evidence_generation"] = self.boot_epoch
        try:
            self.store.append(rec)
            saved = True
        except OSError:
            saved = False
        self.previews[rec["artifact_id"]] = rec
        return {"preview_ref": rec["artifact_id"], "preview_version": rec["preview_version"],
                "evaluation": {k: rec[k] for k in ("result", "reasons", "est_end_pct", "coverage")},
                "takeoff_source": src, "saved": saved}

    def get(self, principal, sid, b):
        rec = self.previews.get(b["artifact_id"]) or self.store.get(b["artifact_id"])
        if rec is None:
            raise ApiError("NOT_FOUND", ["artifact_id"])
        return {"preview": rec}

    # --- 套用
    def _vehicle(self, snap):
        """顯示用的估算一律用 legacy 欄位（cg-v2 的 apply_check 只支援舊版多旋翼）。"""
        return Vehicle(**{k: v for k, v in snap["vehicle"].items() if k != "airframe_profile"})

    def _vehicle_full(self, snap):
        """0437 #6：提交重驗用的機型保留 airframe_profile，讓適用域檢查能看到真實機型並擋下。"""
        return Vehicle(**snap["vehicle"])

    # --- G0-9：預覽被取代
    def supersede_preview(self, preview_ref, reason="superseded", mark=True):
        """把舊預覽標為 SUPERSEDED：綁定它的權杖（已發出或提交中、尚未生效）全部撤銷。已生效的提交不受影響。
        mark=False：只撤銷權杖、不標預覽（同一預覽換新草稿版本時用）。"""
        with self.tok_lock:
            return self._supersede_locked(preview_ref, reason, mark)

    def _supersede_locked(self, preview_ref, reason, mark):
        if mark:
            self.superseded[preview_ref] = reason
        n = 0
        for t in self.tokens.values():
            if t["preview"] == preview_ref and t["state"] in ("ISSUED", "INFLIGHT"):
                t["state"], t["revoked"] = "REVOKED", reason
                n += 1
        return n

    def apply_check(self, principal, sid, b):
        rec = self.previews.get(b["preview_ref"])
        if rec is None:
            raise ApiError("NOT_FOUND", ["preview_ref"])
        k = (principal, b["target_slot_id"], b["draft_id"])
        # 0439 #5：先取結構寫入租約（與所有結構發布同一把），世代在檢查到版本轉移結束之間不會變；
        # 鎖序固定為「租約 → tok_lock」，與提交路徑（租約內的 guard 取 tok_lock）一致。
        if not self.c.lease.acquire(timeout=cl.TEST_VALUES["lease_timeout_s"]):
            raise ApiError("BUSY_RETRY", ["結構寫入中，稍後再試"])
        try:
            self._apply_transition(principal, b, k)
        finally:
            self.c.lease.release()
        snap = self.feeder.poll()
        return self._apply_check_rest(principal, b, rec, snap)

    def _apply_transition(self, principal, b, k):
        if hasattr(self, "_pause_lease"):                 # 測試用暫停點（取得租約前後）
            self._pause_lease()
        if b["target_generation"] != self.c.word.current().root_gen:   # 過期請求：不留任何副作用
            raise ApiError("TARGET_STALE")
        with self.tok_lock:                               # 0438 #5：檢查、撤銷與版本更新是同一個狀態轉移
            if b["preview_ref"] in self.superseded:
                raise ApiError("CONFIRM_TOKEN_STALE", ["preview_superseded"])
            old = self.current_preview.get(k)
            if old and b["draft_rev"] < old[1]:          # 草稿版本只能前進（不論是不是同一預覽）
                raise ApiError("CONFIRM_TOKEN_STALE", ["draft_rev_older_than_current"])
            if old and old[0] != b["preview_ref"]:        # 同一草稿改用新預覽 → 舊預覽 SUPERSEDED
                self._supersede_locked(old[0], "new_preview_same_draft", True)
            elif old and b["draft_rev"] > old[1]:        # 同一預覽、新草稿版本 → 撤銷舊版本的權杖
                self._supersede_locked(old[0], "new_draft_rev", False)
            if hasattr(self, "_pause"):                  # 測試用暫停點（並行換版）
                self._pause()
            self.current_preview[k] = (b["preview_ref"], b["draft_rev"])

    def _apply_check_rest(self, principal, b, rec, snap):
        m = snap["mission"]
        cur = dict(vehicle=self._vehicle(snap), wind=Wind(**snap["wind"]),
                   takeoff_pct=snap["battery"] if snap["battery"] is not None else 100.0,
                   reserve_req_pct=rec["inputs"]["reserve_req_pct"], no_fly=m.get("no_fly", []),
                   max_alt_m=m.get("limits", {}).get("max_altitude_m", 120))
        chk = cv.apply_check(rec, **cur)
        intent = "ai-" + secrets.token_hex(6)
        self.intents[intent] = {"redisplays": 0}
        return self._show(chk, rec, b["target_slot_id"], intent, b["draft_id"], b["draft_rev"], cur, principal)

    def _show(self, chk, rec, slot, intent, draft_id, draft_rev, cur, principal=None):
        sh = _sha({"check": {k: chk[k] for k in ("decision", "diffs", "inputs_now")}, "nonce": secrets.token_hex(8)})
        self.shown[sh] = {"check": chk, "preview": rec, "slot": slot, "intent": intent, "draft_id": draft_id,
                          "principal": principal,
                          "draft_rev": draft_rev, "base": {"reserve_req_pct": cur["reserve_req_pct"],
                                                           "max_alt_m": cur["max_alt_m"]}}
        return {"check": {"decision": chk["decision"], "diffs": chk["diffs"],
                          "reasons": chk["reasons"], "hint": chk.get("hint"), "shown_hash": sh,
                          "apply_intent_id": intent}}

    def presented(self, principal, sid, b):
        sh = self.shown.get(b["shown_hash"])
        if sh is None or sh["intent"] != b["apply_intent_id"] or sh["slot"] != b["target_slot_id"]:
            raise ApiError("CONFIRM_TOKEN_STALE")
        if sh["check"]["decision"] == "BLOCK":
            raise ApiError("BLOCK", [r["code"] for r in sh["check"]["reasons"]])
        ttl = TEST_VALUES["confirm_token_ttl_s"]
        tok = "ct-" + secrets.token_hex(12)
        with self.tok_lock:                               # 0437 #5：取代狀態與目前版本在同一把鎖內核對，再發證
            if not self._binding_current(sh, principal):
                raise ApiError("CONFIRM_TOKEN_STALE", ["not_current_version"])
            for t, v in self.tokens.items():          # 同一槽同時只有一個未消耗權杖
                if v["slot"] == b["target_slot_id"] and v["state"] == "ISSUED":
                    v["state"], v["revoked"] = "REVOKED", "new_window"
            self.tokens[tok] = {"shown_hash": b["shown_hash"], "slot": b["target_slot_id"],
                                "intent": b["apply_intent_id"], "state": "ISSUED", "principal": principal,
                                "expires": self.now() + ttl, "preview": sh["preview"]["artifact_id"],
                                "draft_id": sh["draft_id"], "draft_rev": sh["draft_rev"]}
        return {"confirm_token": tok, "expires_at": (datetime.now(TW) + timedelta(seconds=ttl)).isoformat()}

    def _binding_current(self, sh, principal):
        """呼叫端持有 tok_lock。這個畫面綁定的（principal、槽、草稿、版本、預覽）仍是目前版本，而且預覽沒有被取代。"""
        if sh.get("principal") not in (None, principal):
            return False
        if sh["preview"]["artifact_id"] in self.superseded:
            return False
        cur = self.current_preview.get((principal, sh["slot"], sh["draft_id"]))
        return cur == (sh["preview"]["artifact_id"], sh["draft_rev"])

    def _expired(self, t):
        return self.now() >= t["expires"]          # 0437 #5：等於期限即視為逾期

    def commit(self, principal, sid, b):
        key = (principal, self.boot_epoch, b["target_slot_id"], b["nonce"])
        fp = _sha({k: b[k] for k in ("apply_intent_id", "shown_hash", "confirm_token")})
        if key in self.idem:                      # 冪等表先於權杖檢查
            prev_fp, res = self.idem[key]
            if prev_fp != fp:
                raise ApiError("NONCE_CONFLICT")
            return res
        with self.tok_lock:                       # G0-11：受理時核對期限；G0-9：已撤銷就拒絕
            t = self.tokens.get(b["confirm_token"])
            if t is None or t["state"] != "ISSUED" or t["shown_hash"] != b["shown_hash"] \
                    or t["slot"] != b["target_slot_id"] or t["intent"] != b["apply_intent_id"] \
                    or t["principal"] != principal:
                raise ApiError("CONFIRM_TOKEN_STALE")
            if self._expired(t):
                t["state"] = "EXPIRED"
                raise ApiError("CONFIRM_TOKEN_STALE", ["expired"])
            if not self._binding_current(self.shown[b["shown_hash"]], principal):
                t["state"], t["revoked"] = "REVOKED", "not_current_version"
                raise ApiError("CONFIRM_TOKEN_STALE", ["not_current_version"])
            t["state"] = "INFLIGHT"

        def guard(publish):                      # 生效前（P 的 CAS 之前）在權杖鎖內再核對一次
            with self.tok_lock:
                if t["state"] != "INFLIGHT":
                    return "CONFIRM_TOKEN_STALE", False
                if self._expired(t):
                    t["state"] = "EXPIRED"
                    return "CONFIRM_TOKEN_STALE", False
                if not self._binding_current(self.shown[t["shown_hash"]], principal):
                    t["state"], t["revoked"] = "REVOKED", "not_current_version"
                    return "CONFIRM_TOKEN_STALE", False
                ok = publish()
                if ok:
                    t["state"] = "CONSUMED"
                return None, ok
        sh = self.shown[b["shown_hash"]]
        rec = sh["preview"]
        try:
            snap = self.feeder.poll()
        except cl.CommitError as e:                       # 0438 #4：入站在服務入口就耗盡 → 權杖收尾、回拒絕碼
            with self.tok_lock:
                if t["state"] == "INFLIGHT":
                    t["state"] = "CONSUMED"
            out = {"transaction": {"action": "BLOCK", "code": e.code, "reasons": [e.code],
                                   "transaction_id": None}}
            self.idem[key] = (fp, out)
            return out
        rc = make_route_recheck(rec, self._vehicle_full(snap), sh["base"], shown=sh["check"])
        tx = "tx-" + _sha({"k": list(key)})[:16]
        r = self.c.route_apply(tx, b["target_slot_id"], rec["route_id"], rec["route"], sh["draft_id"],
                               sh["draft_rev"], rc, guard=guard)
        with self.tok_lock:
            if t["state"] == "INFLIGHT":            # 沒有生效（重顯、擋下等）：權杖用掉，不能再用
                t["state"] = "CONSUMED"
        out = {"transaction": dict(r, transaction_id=tx)}
        if r["action"] == "REDISPLAY":
            it = self.intents[sh["intent"]]
            if it["redisplays"] >= TEST_VALUES["max_redisplay"]:
                out = {"transaction": dict(r, action="BLOCK", code="REDISPLAY_LIMIT", transaction_id=tx)}
            else:
                it["redisplays"] += 1
                cur_chk = r.get("diffs")
                m = snap["mission"]
                cur = dict(vehicle=self._vehicle(snap), wind=Wind(**snap["wind"]),
                           takeoff_pct=snap["battery"] if snap["battery"] is not None else 100.0,
                           reserve_req_pct=sh["base"]["reserve_req_pct"], no_fly=m.get("no_fly", []),
                           max_alt_m=sh["base"]["max_alt_m"])
                chk = cv.apply_check(rec, **cur)
                out["redisplay"] = self._show(chk, rec, sh["slot"], sh["intent"], sh["draft_id"], sh["draft_rev"],
                                              cur, principal)["check"]
                out["transaction"]["diffs"] = cur_chk
        self.idem[key] = (fp, out)
        return out

    def transaction_get(self, principal, sid, b):
        r = self.c.results.get(b["transaction_id"])
        if r is None:
            raise ApiError("NOT_FOUND", ["transaction_id"])
        return {"transaction": r}

    def undo(self, principal, sid, b):
        if b["target_generation"] != self.c.word.current().root_gen:
            raise ApiError("TARGET_STALE")
        key = (principal, self.boot_epoch, b["target_slot_id"], "undo:" + b["nonce"])
        if key in self.idem:
            return self.idem[key][1]
        r = self.c.undo("u-" + _sha({"k": list(key)})[:16])
        out = {"transaction": r}
        self.idem[key] = ("", out)
        return out


# ---------------- Agent 端點（M3） ----------------

def _agent_view(r):
    keep = ("status", "task_id", "reply_zh", "questions", "directions", "calls_used", "notes")
    return {k: r.get(k) for k in keep}


def _agent_owned(svc, sid, b):
    if svc.controller is None:
        raise ApiError("NOT_FOUND", ["agent 未啟用"])
    tid = b.get("task_id")
    if tid is not None and svc.task_owner.get(tid) != sid:
        raise ApiError("NOT_FOUND", ["task_id"])
    return tid


def _agent_request(self, principal, sid, b):
    _agent_owned(self, sid, b)
    r = self.controller.request(b["text"])
    if r.get("task_id"):
        self.task_owner[r["task_id"]] = sid
    return _agent_view(r)


def _agent_resume(self, principal, sid, b):
    tid = _agent_owned(self, sid, b)
    if "answers" in b:
        r = self.controller.resume(tid, b["answers"])
    elif "text" in b:
        r = self.controller.resume_text(tid, b["text"])
    else:
        r = self.controller.continue_task(tid)
    return _agent_view(r)


def _agent_get(self, principal, sid, b):
    tid = _agent_owned(self, sid, b)
    return _agent_view(self.controller._reply(self.controller.tasks[tid]))


def _agent_cancel(self, principal, sid, b):
    tid = _agent_owned(self, sid, b)
    return _agent_view(self.controller.cancel(tid))


PreviewService.agent_request = _agent_request
PreviewService.agent_resume = _agent_resume
PreviewService.agent_get = _agent_get
PreviewService.agent_cancel = _agent_cancel


# ---------------- HTTP ----------------

class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, service: PreviewService, token: str, origins=()):
        super().__init__(addr, PreviewHandler)
        self.service = service
        self.token = token
        self.origins = set(origins)
        self.hosts = {f"127.0.0.1:{self.server_address[1]}", f"localhost:{self.server_address[1]}"}


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass                                     # token 不進日誌

    def _send(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _err(self, e: ApiError, default=400):
        self._send(HTTP_OF.get(e.code, default),
                   {"ok": False, "error": {"code": e.code, "reasons": e.reasons, "hint": e.hint}})

    def _pre(self, method_ok):
        srv = self.server
        if len(str(self.headers)) > TEST_VALUES["header_cap"]:
            raise ApiError("HEADER_TOO_LARGE")
        if self.headers.get("Host") not in srv.hosts:
            raise ApiError("HOST_DENIED")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in srv.origins:
            raise ApiError("ORIGIN_DENIED")
        path = self.path.split("?", 1)[0]
        if path not in SCHEMA:
            raise ApiError("NOT_FOUND")
        if not method_ok:
            raise ApiError("METHOD_DENIED")
        auth = self.headers.get_all("Authorization") or []
        if not auth:
            raise ApiError("AUTH_MISSING")
        if len(auth) != 1 or not auth[0].startswith("Bearer ") or \
                not hmac.compare_digest(auth[0][7:].encode(), srv.token.encode()):
            raise ApiError("AUTH_INVALID")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError("SCHEMA_TYPE", ["Transfer-Encoding"])
        cls = self.headers.get_all("Content-Length") or []
        if len(cls) != 1 or not cls[0].isdigit():
            raise ApiError("SCHEMA_TYPE", ["Content-Length"])
        n = int(cls[0])
        if n > BODY_CAP[path]:
            raise ApiError("BODY_TOO_LARGE")
        return path, n

    def _other(self):
        try:
            self._pre(False)
        except ApiError as e:
            self._err(e)

    do_GET = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _other

    def do_POST(self):
        try:
            path, n = self._pre(True)
            raw = self.rfile.read(n)
            def _nonfinite(_c):
                raise ApiError("NONFINITE")
            try:
                body = json.loads(raw.decode("utf-8"), parse_constant=_nonfinite)
            except (ValueError, UnicodeDecodeError):
                raise ApiError("SCHEMA_TYPE", ["json"])
            validate(path, body)
            data = self.server.service.dispatch(path, "ui", body)
            self._send(200, {"ok": True, "data": data})
        except ApiError as e:
            self._err(e)
        except cl.CommitError as e:
            self._err(ApiError(e.code, [e.detail]))
