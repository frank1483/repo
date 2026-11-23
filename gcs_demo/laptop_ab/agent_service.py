"""筆電互動用 Agent 服務：讓正式 UI 的 AiAgent 面板實際操作方案 A 或方案 B（說明 v3，使用者 2026-11-23 16:15 同意）。

一個程序只跑一種方案（A＝M4bController 逐步迴圈；B＝PlanBController 結構化計畫，第 1 段自己跑）。
控制器、提示詞、檢索、預算、條件都和 v3.11 評估相同（條件 A-s6-b30：每句最多 6 步、預算 30 次呼叫；B0 規則可選）。
只聽 127.0.0.1。模型永遠不能自己套用：面板在操作員按「套用」後才改畫面，再回報這裡記錄 APPLIED／UNDONE。
真模型只有在 live 同意之後才能啟動（--bundle 與 --consent-hash8，核對方式和評估執行器相同）；--fake 只用固定回覆的假模型。

API（JSON）：
  GET  /api/agent/health                      → 方案、模式、模型、索引、Ollama 版本
  POST /api/agent/request {text, group?}      → 一句話的完整結果（方向、步驟或計畫、引文、提案與畫面動作）
  POST /api/agent/mark {task_id, index, state, detail?}   → 面板回報套用（APPLIED）或復原（UNDONE）或失敗（APPLY_FAILED）
每句話寫一筆到 <logdir>/requests.jsonl（請求、回覆、模型呼叫、時間）。
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import llm_gateway as G
from .. import m4_runner as R
from .. import m4b_runner as R4
from ..id_graph import load_index
from . import polish as P

PLAN_NAME = {"A": "方案 A（逐步迴圈）", "B": "方案 B（結構化計畫）"}
COND = {"steps": 6, "budget": 30}                  # 與 v3.11 smoke／research 的 A-s6-b30 相同
TEXT_SCALE = {"小": 0.85, "中": 1.0, "大": 1.15, "特大": 1.3}
SIZE_OP = {"縮小": "shrink", "原始": "reset", "放大": "grow"}
MOVE_REGION = {"左上": "top_left", "右上": "top_right", "左下": "bottom_left", "右下": "bottom_right", "中央": "center"}
THEME = {"T001": "dark", "T002": "light", "T003": "high_contrast"}
MAX_BODY = 16384


class AgentService:
    def __init__(self, plan, logdir, fake=False, ollama_port=11555, bundle="", hash8="", base=None):
        if plan not in ("A", "B"):
            raise SystemExit("--plan 只能是 A 或 B")
        self.plan, self.fake, self.logdir = plan, fake, logdir
        self.lock = threading.Lock()
        self.tasks = {}
        self.ids = itertools.count(1)
        self.proc = None
        self.ollama_port = ollama_port
        os.makedirs(logdir, exist_ok=False)
        base = base or R.BASE_DOC
        self.info = {"plan": plan, "plan_name": PLAN_NAME[plan], "mode": "fake" if fake else "live",
                     "condition": dict(COND), "started": R.now(), "base": base}
        if plan == "B":
            from ..agent_planb import PlanBController
            self.Ctl = PlanBController
            R4.HARNESS["name"] = "planb-v9-interactive"
        else:
            from ..agent_m4b import M4bController
            self.Ctl = M4bController
            R4.HARNESS["name"] = "m4b-v5-interactive"
        if fake:
            self.factory = R4.fake_model
            R.set_manual_index(os.path.join(base, "adr0002_rag_v1", "index_v1"), "http://127.0.0.1:1", use_vector=False)
            self.graph, man = load_index(os.path.join(base, "adr0002_rag_v1", "id_index_v1"))
            self.counter = len
            self.info["token_counter"] = "len（假模型模式）"
        else:
            vb = R.verify_bundle(bundle, hash8)
            self.info["bundle_verification"] = {k: vb.get(k) for k in ("ok", "error", "sums_sha256", "commit", "frozen_commit",
                                                                       "dirty", "models_root", "platform", "ollama_bin")}
            if not vb["ok"]:
                self._write_info()
                raise SystemExit("來源包核對不通過，未啟動模型（見 SERVICE_INFO.json）")
            self.proc = R.start_ollama(ollama_port, os.path.join(logdir, "ollama_serve.log"))
            self.info["ollama_pid"] = self.proc.pid
            import urllib.request
            self.info["ollama_server_version"] = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{ollama_port}/api/version", timeout=5).read())
            lines = vb["lines"]
            idx = next(l for l in lines if l["name"].endswith("index_v1/INDEX_MANIFEST.json"))
            R.set_manual_index(os.path.dirname(os.path.join(R.BASE_DOC, idx["name"])), f"http://127.0.0.1:{ollama_port}",
                               use_vector=True)
            lid = next(l for l in lines if l["name"].endswith("ID_INDEX_MANIFEST.json"))
            self.graph, man = load_index(os.path.dirname(os.path.join(R.BASE_DOC, lid["name"])))
            up = G.make_upstream("ollama", f"http://127.0.0.1:{ollama_port}", R.MODEL_TAG)
            self.gw = G.Gateway(up, os.path.join(logdir, "gateway_calls.jsonl"), budgets=R4.GATEWAY_BUDGETS)
            self.factory = lambda log: R4.gateway_model(self.gw, log)  # noqa: E731
            from .. import gemma4_tokenizer as TK
            tok = TK.load_vocab()
            self.counter = lambda text: len(TK.encode(text, tok))  # noqa: E731
            self.info["token_counter"] = {"blob_digest": tok["blob_digest"]}
        self.info["id_index"] = {"graph_sha256": man["graph_sha256"], "vectors_sha256": man["vectors_sha256"]}
        self.info["polish"] = P.describe()
        self.env_dir = os.path.join(logdir, "env")
        self.svc, self.tools = R.build_env(self.env_dir)
        idx = R.manual_index()
        self.tools["embed_query"] = lambda text: idx.query_vector(text) if R._INDEX["use_vector"] else None
        self.tools["manual_search"] = lambda text, qv, manual=None, extra=None: idx.search(
            text, use_vector=R._INDEX["use_vector"], vector=qv, require_pre=R._INDEX["use_vector"], manual=manual, extra=extra)
        self._write_info()

    def _write_info(self):
        with open(os.path.join(self.logdir, "SERVICE_INFO.json"), "w", encoding="utf-8") as f:
            json.dump(self.info, f, ensure_ascii=False, indent=1, default=str)

    def close(self):
        if self.proc is not None:
            self.info["ollama_stop"] = R.stop_ollama(self.proc, self.ollama_port)
            self.proc = None
        self.info["stopped"] = R.now()
        self._write_info()

    # ---------- 一句話 ----------
    def request(self, text, group="model"):
        if group not in ("model", "B0"):
            raise ValueError("group 只能是 model 或 B0")
        with self.lock:
            if self.proc is not None:
                R.check_owner(self.proc, self.ollama_port)
            calls = []
            model = None if group == "B0" else self.factory(calls)
            c = self.Ctl(self.tools, model, self.graph, self.counter, ledger_cfg={"per_sentence": 0 if group == "B0" else COND["budget"]},
                         steps_max=COND["steps"], summary_llm=False)
            if self.plan == "A" and R4.STRICT_PARAMS_A:
                c.strict_params = True
            t0 = time.monotonic()
            err = tb = None
            idx = R.manual_index()
            n_embed = len(idx.calls) if idx else 0
            try:
                r = c.request(text)
            except Exception as e:  # noqa: BLE001 - 原樣記錄，面板顯示錯誤
                r, err, tb = {}, repr(e), traceback.format_exc()
            elapsed = round(time.monotonic() - t0, 3)
            pol = P.polish(r, model, calls) if r and not err and group != "B0" else P.skipped(r, "B0 或錯誤不潤飾")
            tid = f"t{next(self.ids):04d}"
            out = self.view(tid, text, group, r, err, elapsed, calls, pol, idx.calls[n_embed:] if idx else [])
            self.tasks[tid] = out
            self._log({"task_id": tid, "text": text, "group": group, "time": R.now(), "result": out, "raw": r,
                       "traceback": tb, "calls": calls}, "requests.jsonl")
            return out

    def view(self, tid, text, group, r, err, elapsed, calls, pol, embeds):
        A = (r or {}).get("artifacts") or {}
        props = [self.ui_action(i, p, A) for i, p in enumerate((r or {}).get("proposals") or [])]
        rp = A.get("route_preview") or {}
        if rp.get("verdict") == "pass" and not any(p["action"] == "PROPOSE_HOME_ROUTE" for p in props):
            # 規劃方向只產生「驗算通過的預覽」；面板另給一個由操作員決定的「寫進任務規劃頁」（不是模型提案，標 from_artifact）
            item = self.ui_action(len(props), {"action": "PROPOSE_HOME_ROUTE", "direction": "plan", "ids": [],
                                               "state": "PREVIEW", "by": "program", "source": {"preview_ref": rp.get("ref")}}, A)
            item["from_artifact"] = True
            item["label"] = "（預覽驗算通過）" + item["label"]
            props.append(item)
        mc = A.get("manual_claims") or {}
        return {"ok": err is None, "error": err, "task_id": tid, "plan": self.plan, "group": group, "text": text,
                "status": (r or {}).get("status"), "reply": pol["reply"], "reply_source": pol["source"],
                "reply_template": (r or {}).get("reply_zh"), "polish": pol,
                "directions": (r or {}).get("directions") or [], "dir_status": (r or {}).get("dir_status") or {},
                "steps": [{k: s.get(k) for k in ("direction", "action", "ids", "params", "result", "by", "state")}
                          for s in ((r or {}).get("steps") or (r or {}).get("plan") or [])],
                "replans": (r or {}).get("replans"), "notes": (r or {}).get("notes") or [],
                "manual": {"verdict": mc.get("verdict"), "refs": mc.get("refs") or [], "query": mc.get("query")} if mc else None,
                "qa": A.get("qa_claims"), "report": A.get("report_draft"), "flight_notice": A.get("flight_notice"),
                "proposals": props, "calls_used": (r or {}).get("calls_used"), "model_calls": len(calls),
                "embed_calls": len(embeds), "t_pre_summary_s": (r or {}).get("t_pre_summary_s"), "elapsed_s": elapsed}

    def ui_action(self, i, p, A):
        """把一筆提案翻成面板能執行的畫面動作（只翻譯，不執行）。翻不出來的標 supported=false 並說明。"""
        act, ids, params = p.get("action"), p.get("ids") or [], p.get("params") or {}
        node = lambda x: self.graph.nodes.get(x, {})  # noqa: E731
        base = {"index": i, "action": act, "direction": p.get("direction"), "ids": ids, "params": params,
                "state": p.get("state"), "by": p.get("by"), "t_ready_s": p.get("t_ready_s")}
        if act == "PROPOSE_HOME_ROUTE":
            src = p.get("source") or {}
            rec = self.svc.previews.get(src.get("preview_ref")) or {}
            pts = [{"lat": q["lat"], "lon": q["lon"], "alt": q.get("alt", 50)} for q in rec.get("route") or []
                   if q.get("kind") != "home"]
            ev = {k: rec.get(k) for k in ("result", "reasons", "est_end_pct", "coverage")}
            return base | {"ui": {"kind": "route", "points": pts, "evaluation": ev, "preview_ref": src.get("preview_ref")},
                           "supported": bool(pts), "label": f"把覆蓋航線（{len(pts)} 個航點）寫進任務規劃頁"}
        if act == "UI_LAYOUT_PROPOSE":
            cs = [x for x in ids if node(x).get("cat") == "C"]
            ps = [x for x in ids if node(x).get("cat") == "P"]
            v = params.get("value")
            mod = node(cs[0]).get("module") if cs else None
            name = node(cs[0]).get("name") if cs else ""
            pid = ps[0] if ps else None
            if pid == "P001" and v in TEXT_SCALE:
                return base | {"ui": {"kind": "text_scale", "value": TEXT_SCALE[v]}, "supported": True, "label": f"全域文字大小改為「{v}」"}
            if pid == "P002" and mod and v in SIZE_OP:
                return base | {"ui": {"kind": "layout", "module": mod, "op": SIZE_OP[v]}, "supported": True, "label": f"{name}{v}"}
            if pid == "P003" and mod and v in MOVE_REGION:
                return base | {"ui": {"kind": "layout", "module": mod, "op": "move", "region": MOVE_REGION[v]},
                               "supported": True, "label": f"{name}移到{v}"}
            if pid == "P004" and mod and v in ("顯示", "隱藏"):
                return base | {"ui": {"kind": "layout", "module": mod, "op": "show" if v == "顯示" else "hide"},
                               "supported": True, "label": f"{v}{name}"}
            return base | {"ui": None, "supported": False, "label": "版面提案缺元件或值，無法對應畫面動作"}
        if act == "UI_THEME_PROPOSE":
            t = next((x for x in ids if x in THEME), None)
            return base | {"ui": {"kind": "theme", "theme": THEME.get(t)} if t else None, "supported": bool(t),
                           "label": f"切換到{node(t).get('name', '主題')}" if t else "主題提案缺主題 ID"}
        if act == "MODEL_SWITCH_PROPOSE":
            m = next((x for x in ids if node(x).get("cat") == "M"), None)
            return base | {"ui": {"kind": "model", "model_id": m, "name": node(m).get("name")} if m else None,
                           "supported": bool(m), "label": f"選用{node(m).get('name', '模型')}（筆電只有 gemma4:e2b，記錄選擇）"}
        return base | {"ui": None, "supported": False, "label": f"{act}：沒有對應的畫面動作"}

    def mark(self, tid, index, state, detail=None):
        if state not in ("APPLIED", "UNDONE", "APPLY_FAILED"):
            raise ValueError("state 只能是 APPLIED、UNDONE、APPLY_FAILED")
        with self.lock:
            t = self.tasks.get(tid)
            if t is None or not (0 <= int(index) < len(t["proposals"])):
                raise KeyError("task_id 或 index")
            p = t["proposals"][int(index)]
            p.setdefault("history", []).append({"state": state, "time": R.now(), "detail": detail})
            p["state"] = state
            self._log({"task_id": tid, "index": index, "state": state, "detail": detail, "time": R.now()}, "marks.jsonl")
            return {"ok": True, "task_id": tid, "index": index, "state": state}

    def health(self):
        return {"ok": True, "plan": self.plan, "plan_name": PLAN_NAME[self.plan], "mode": self.info["mode"],
                "model": None if self.fake else R.MODEL_TAG, "ollama": self.info.get("ollama_server_version"),
                "polish": self.info["polish"], "tasks": len(self.tasks)}

    def _log(self, rec, name):
        with open(os.path.join(self.logdir, name), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"ok": False, "error": "host"})
        if self.path == "/api/agent/health":
            return self._send(200, self.server.svc.health())
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"ok": False, "error": "host"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"ok": False, "error": "body too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if not isinstance(body, dict):
                raise ValueError("body")
            s = self.server.svc
            if self.path == "/api/agent/request":
                return self._send(200, s.request(str(body.get("text", "")), body.get("group", "model")))
            if self.path == "/api/agent/mark":
                return self._send(200, s.mark(str(body.get("task_id")), body.get("index", -1), body.get("state"),
                                              body.get("detail")))
            return self._send(404, {"ok": False, "error": "not found"})
        except (KeyError, ValueError, TypeError) as e:
            return self._send(400, {"ok": False, "error": str(e)})
        except SystemExit as e:                   # 例如專用 Ollama 歸屬核對失敗
            return self._send(503, {"ok": False, "error": str(e)})


def main(argv=None):
    ap = argparse.ArgumentParser(description="方案 A／B 互動 Agent 服務（只聽 127.0.0.1）")
    ap.add_argument("--plan", choices=("A", "B"), required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--logdir", required=True)
    ap.add_argument("--fake", action="store_true", help="假模型（不是 live）")
    ap.add_argument("--ollama-port", type=int, default=11555)
    ap.add_argument("--bundle", default="")
    ap.add_argument("--consent-hash8", default="")
    a = ap.parse_args(argv)
    if not a.fake and not (a.bundle and a.consent_hash8):
        raise SystemExit("真模型需要 --bundle 與 --consent-hash8（使用者親打「同意 <hash8>」之後）")
    svc = AgentService(a.plan, a.logdir, fake=a.fake, ollama_port=a.ollama_port, bundle=a.bundle, hash8=a.consent_hash8)
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    httpd.daemon_threads = True
    httpd.svc = svc
    print(f"Agent 服務：{PLAN_NAME[a.plan]}，{svc.info['mode']}，http://127.0.0.1:{a.port}/api/agent/health", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        svc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
