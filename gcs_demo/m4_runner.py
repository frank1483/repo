"""ADR-0002 M4 執行器 v2：桌面真模型迴圈的校準（G2a）與研究實驗（G2r）。

依「M4 桌面真模型迴圈：實驗計畫 v1」（使用者 2026-11-17 13:17 同意 M4-2、M4-3），
並修正 Codex CODEX-APP-0399 對 v1 來源包（28cce998…）的 5 項異議：
  1. 每個案例×條件的工作目錄、完整回傳與 trace 全部保留（先寫結果，不刪工作目錄）。
  2. 計分依凍結的必要方向／成果逐項判定（完整、部分、漏目標、錯誤宣告完成）。
  3. 保存 T1 所需的引擎 trace（嚴格、寬鬆前綴、修正、無效）；calib 加 T5 告警暫停與取消探測。
  4. 專用 Ollama：埠被占用就停；啟動後核對子程序仍存活、且監聽該埠的 PID 就是自己啟動的程序。
  5. 啟動模型前核對完整來源包（SHA256SUMS 每一行、清單本身雜湊、hash8）與實際模型 manifest，記錄實際讀值。
**真模型只有在 live 同意後才能執行**：兩方對同一份來源包 SHA256 精確同意，使用者親打「同意 <hash8>」。
本程式的 hash8 核對只確認「輸入的 hash8 對應現在的來源包」，不能代替使用者本人的同意。
v3 另修 Codex CODEX-APP-0400：凍結 commit 比對與 git 結束碼、Ollama 用已驗證的模型根、
就緒後與每個案例前復核程序歸屬、T1 依原始回覆整串判定、單案例例外時保留部分任務與堆疊。
--fake 模式只用固定回覆的假模型檢查執行器，不算 live。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from . import commit_layer as cl
from . import llm_gateway as G
from .agent_controller import Controller, KINDS
from .agent_tools import AgentTools
from .preview_api import PreviewService, SessionFeeder
from .energy import Vehicle, Wind

TW = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CASES = os.path.join(HERE, "m4_cases_v2.json")
INDEX_DIR = os.environ.get("GCS_MANUAL_INDEX", os.path.join(os.path.dirname(os.path.dirname(REPO)), "adr0002_rag_v1",
                                                            "index_v1"))
_INDEX = None


def manual_index():
    global _INDEX
    if _INDEX is None and os.path.exists(os.path.join(INDEX_DIR, "INDEX_MANIFEST.json")):
        from .rag_index import Index
        _INDEX = Index(INDEX_DIR)
    return _INDEX
MODEL_TAG = "gemma4:e2b"
MODELS_ROOT = os.path.join(os.path.expanduser("~"), ".ollama", "models")   # 核對與啟動用同一個模型根
MANIFEST_PATH = os.path.join(MODELS_ROOT, "manifests", "registry.ollama.ai", "library", "gemma4", "e2b")
QA_TOOL_NOTE = "問答工具尚未接上（agent_tools qa_lookup 固定回空 claims），QA 方向未完成應歸因於工具，不是模型"
CONDITIONS = {
    "calib": [{"id": "A-s10-b12", "group": "A", "steps": 10, "budget": 12}],
    "research": ([{"id": "B0", "group": "B0", "steps": 10, "budget": 0},
                  {"id": "B1", "group": "B1", "steps": 10, "budget": 1}]
                 + [{"id": f"A-s{s}-b30", "group": "A", "steps": s, "budget": 30} for s in (3, 5, 7, 10, 12, 15)]
                 + [{"id": f"A-s10-b{b}", "group": "A", "steps": 10, "budget": b} for b in (6, 12, 24)]),
}
GROUP_NOTE = {"B0": "規則路由：方向與每步都用規則，零模型呼叫",
              "B1": "固定流程：模型只做一次方向判斷（每句預算 1），之後每步由規則選",
              "A": "有界 Agent：模型判斷方向並逐步選動作"}
# 每個方向的必要成果（E-9：研究分母依凍結的必要方向）
REQUIRED = {"plan": ("route_preview", "pass"), "ui": ("apply_proposal", None), "qa": ("qa_claims", "ok"),
            "report": ("report_draft", None), "manual": ("manual_claims", "ok")}


def now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S 台灣時間")


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------- 第 5 點：來源包與模型核對 ----------------

def verify_bundle(bundle_dir, hash8):
    sums = os.path.join(bundle_dir, "SHA256SUMS.txt")
    sums_sha = sha_file(sums)
    report = {"sums_sha256": sums_sha, "hash8_input": hash8, "lines": [], "ok": True}
    if not hash8 or sums_sha[:8] != hash8:
        report["ok"] = False
        report["error"] = "hash8 與來源包不符"
    base_doc = os.path.dirname(os.path.dirname(REPO))      # C:/Users/.../碩士論文
    for line in open(sums, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        want, name = line.split(" ", 1)
        name = name.lstrip("*")
        if name.startswith("ollama-manifest:"):
            path = MANIFEST_PATH
        elif name.startswith("gcs_demo/") or name.startswith("ui_agent/"):
            path = os.path.join(REPO, name)
        else:
            path = os.path.join(base_doc, name)
        got = sha_file(path) if os.path.exists(path) else None
        report["lines"].append({"name": name, "want": want, "got": got})
        if got != want:
            report["ok"] = False
    h = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True)
    st = subprocess.run(["git", "-C", REPO, "status", "--porcelain=v1", "--untracked-files=all"],
                        capture_output=True, text=True)
    commit = h.stdout.strip()
    frozen_path = os.path.join(bundle_dir, "commit.txt")
    frozen = open(frozen_path, encoding="utf-8").read().split()[0] if os.path.exists(frozen_path) else None
    report.update({"commit": commit, "frozen_commit": frozen, "git_exit": [h.returncode, st.returncode],
                   "dirty": bool(st.stdout.strip()), "models_root": MODELS_ROOT,
                   "model_manifest_sha256": sha_file(MANIFEST_PATH) if os.path.exists(MANIFEST_PATH) else None})
    bad_git = h.returncode != 0 or st.returncode != 0 or not commit or frozen is None or commit != frozen
    if bad_git or report["dirty"]:
        report["ok"] = False
        report.setdefault("error", "git 結束碼、凍結 commit 或工作樹核對不通過")
    if not any(l["name"].startswith("ollama-manifest:") and l["got"] == report["model_manifest_sha256"]
               for l in report["lines"]):
        report["ok"] = False
        report.setdefault("error", "模型 manifest 與來源包不符")
    return report


# ---------------- 第 4 點：專用 Ollama 的歸屬 ----------------

def port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def listener_pids(port):
    r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("netstat 失敗，無法確認埠的歸屬，停下")
    out = r.stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            pids.add(int(parts[4]))
    return pids


def start_ollama(port, log_path):
    if not port_free(port):
        raise SystemExit(f"埠 {port} 已被占用，依 H-01 停下，不沿用既有服務")
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1",
               OLLAMA_MODELS=MODELS_ROOT)       # 不繼承其他模型根
    lf = open(log_path, "ab")
    p = subprocess.Popen(["ollama", "serve"], env=env, stdout=lf, stderr=lf)
    import urllib.request
    for _ in range(60):
        if p.poll() is not None:
            raise SystemExit(f"專用 Ollama 已結束（exit {p.returncode}），不沿用他方端點")
        pids = listener_pids(port)
        if pids:
            if pids != {p.pid}:
                p.terminate()
                raise SystemExit(f"埠 {port} 的監聽者 {sorted(pids)} 不是自己啟動的 {p.pid}，停下")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1).read()
                return p
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.5)
    p.terminate()
    raise SystemExit("專用 Ollama 沒有在 30 秒內就緒")


def check_owner(p, port):
    """就緒後、每個案例前復核：子程序仍存活，且監聽該埠的只有它。"""
    if p.poll() is not None:
        raise SystemExit(f"專用 Ollama 已結束（exit {p.returncode}），停下")
    pids = listener_pids(port)
    if pids != {p.pid}:
        raise SystemExit(f"埠 {port} 的監聽者 {sorted(pids)} 不是自己啟動的 {p.pid}，停下")


def stop_ollama(p, port):
    p.terminate()
    try:
        p.wait(timeout=10)
        out = {"stopped": True, "exit": p.returncode}
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=10)
        out = {"stopped": True, "killed": True, "exit": p.returncode}
    out["port_listeners_after"] = sorted(listener_pids(port))
    return out


class RamSampler(threading.Thread):
    """每 0.5 秒取樣：自己啟動的 Ollama（含子程序）與全部 ollama.exe 分開記錄。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak_all_kb = 0
        self.stop = threading.Event()

    @staticmethod
    def sample_all():
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq ollama.exe"],
                                 capture_output=True, text=True, timeout=5).stdout
            tot = 0
            for line in out.splitlines():
                parts = [x.strip('"') for x in line.split('","')]
                if len(parts) >= 5:
                    tot += int("".join(ch for ch in parts[4] if ch.isdigit()) or 0)
            return tot
        except Exception:  # noqa: BLE001
            return 0

    def run(self):
        while not self.stop.is_set():
            self.peak_all_kb = max(self.peak_all_kb, self.sample_all())
            time.sleep(0.5)


# ---------------- 模型 ----------------

class Session0:
    def __init__(self):
        self.lock = threading.Lock()
        self.mission = {"name": "M4", "home": {"id": "H", "lat": 24.0, "lon": 121.0}, "cruise_alt_m": 50,
                        "no_fly": [], "limits": {"max_altitude_m": 120}, "targets": []}
        self.wind = Wind()
        self.current_state = None

    def vehicle(self):
        return Vehicle()


def gateway_model(gw, calls_log, deadline_s=None):
    def model(call):
        content = call["messages"][1]["content"]
        feature = "agent_dir" if '"kinds"' in content else ("agent_resume" if "回覆的意圖" in content else "agent_step")
        t0 = time.monotonic()
        st, body = gw.submit(feature, {"messages": call["messages"], "max_tokens": 64}, harness="m4-v2",
                             deadline_s=deadline_s)
        dt = time.monotonic() - t0
        text = ""
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        calls_log.append({"feature": feature, "status": st, "latency_s": round(dt, 3), "raw": text,
                          "format_class": classify_raw(content, text) if st == 200 else None,
                          "usage": body.get("usage") if isinstance(body, dict) else None})
        if st != 200:
            raise RuntimeError(f"gateway {st}")
        return text
    return model


def fake_model(calls_log):
    from .test_agent_controller import FakeModel
    fm = FakeModel()

    def model(call):
        content = call["messages"][1]["content"]
        if '"kinds"' in content:
            text = json.dumps({"kinds": [k for k in KINDS if k in ("plan", "ui") and
                                         (k != "ui" or "首頁" in content)] or ["chat"]})
        else:
            text = fm(call)
        calls_log.append({"feature": "fake", "status": 200, "latency_s": 0.0, "raw": text,
                          "format_class": classify_raw(content, text), "usage": None})
        return text
    return model


# ---------------- 第 2、3 點：計分與 trace ----------------

def score(case, task, reply):
    gold = case["gold_kinds"]
    A = task["artifacts"] if task else {}
    per = []
    for k in gold:
        slot, verdict = REQUIRED.get(k, (None, None))
        a = A.get(slot) if slot else None
        ok = a is not None and (verdict is None or a.get("verdict") == verdict)
        per.append({"kind": k, "slot": slot, "satisfied": ok})
    status = reply.get("status")
    if not gold:
        complete = status == "HOLD"
    else:
        complete = all(p["satisfied"] for p in per)
    missed = [p["kind"] for p in per if not p["satisfied"]]
    return {"per_goal": per, "complete": complete,
            "partial": bool(gold) and not complete and any(p["satisfied"] for p in per),
            "missed_kinds": missed,
            "claimed_done_wrong": status == "DONE" and not complete,
            "status_match": status == case["expect"],
            "kinds_selected": sorted((reply.get("directions") or {}).keys())}


def classify_raw(call_content, raw):
    """T1：依原始回覆整串判定格式。分母＝傳輸成功的回覆。"""
    import re as _re
    from .agent_loop import default_extract
    is_dir = '"kinds"' in call_content
    m = _re.search(r"只能選：(.*)", call_content)
    allowed = [x.split(" ")[0] for x in m.group(1).split("｜")] if m else []
    try:
        whole = json.loads(raw)
    except (ValueError, TypeError):
        whole = None
    if isinstance(whole, dict):
        if is_dir:
            return "strict" if list(whole) == ["kinds"] else "invalid"
        if list(whole) == ["value"] and whole["value"] in allowed:
            return "strict"
        if list(whole) == ["value"] and isinstance(whole["value"], str) and any(
                whole["value"].lstrip().startswith(c) for c in allowed if c):
            return "lenient_prefix"
        return "invalid"
    ex = default_extract(raw)
    if isinstance(ex, dict):
        return "extracted"          # 整串不是 JSON，但能從前後文擷取出物件
    return "invalid"


def t1_from_calls(calls):
    c = {"transport_ok": 0, "transport_fail": 0, "strict": 0, "lenient_prefix": 0, "extracted": 0, "invalid": 0}
    for x in calls:
        if x.get("status") != 200:
            c["transport_fail"] += 1
            continue
        c["transport_ok"] += 1
        c[x.get("format_class") or "invalid"] += 1
    c["denominator"] = "transport_ok（傳輸成功的回覆數）"
    return c


def t1_counts(task):
    c = {"model_replies": 0, "strict": 0, "lenient_prefix": 0, "invalid": 0, "repair_requested": 0,
         "rule_fallback": 0}
    for t in (task or {}).get("traces", []):
        if t["source"] != "model":
            c["rule_fallback"] += 1
        for e in t["trace"]:
            ev = e.get("event")
            if ev == "model_reply":
                c["model_replies"] += 1
            elif ev == "invalid":
                c["invalid"] += 1
            elif ev == "lenient_prefix":
                c["lenient_prefix"] += 1
            elif ev == "repair_requested":
                c["repair_requested"] += 1
            elif ev == "filled":
                c["strict"] += 1
    c["strict"] -= c["lenient_prefix"]
    return c


def build_env(work):
    root = os.path.join(work, "store")
    cl.init_store(root)
    coord, _ = cl.boot(root)
    sess = Session0()
    feeder = SessionFeeder(sess, coord)
    feeder.poll()
    svc = PreviewService(coord, feeder, os.path.join(work, "ev", "p.jsonl"), boot_epoch=1)
    svc.sessions["m4"] = {"principal": "ui", "last_epoch": 0}
    return svc, AgentTools(svc, "ui", "m4", manual_index=manual_index())


def run_case(case, cond, model_factory, work):
    svc, tools = build_env(work)
    calls = []
    model = None if cond["group"] == "B0" else model_factory(calls)
    ledger = {"per_sentence": cond["budget"] if cond["group"] != "B0" else 0, "per_task": max(cond["budget"], 1) * 2}
    c = Controller(tools, model, ledger_cfg=ledger, steps_max=cond["steps"])
    t0 = time.monotonic()
    err = None
    tb = None
    try:
        r = c.request(case["text"])
    except Exception as e:  # noqa: BLE001 - 首敗原樣記錄，保留部分任務與堆疊
        import traceback
        r, err, tb = {}, repr(e), traceback.format_exc()
    dt = time.monotonic() - t0
    if r.get("task_id"):
        task = c.tasks.get(r["task_id"])
    else:
        task = c.tasks[sorted(c.tasks)[-1]] if c.tasks else None
    rec = {"case": case["id"], "cond": cond["id"], "group": cond["group"], "steps_max": cond["steps"],
           "budget": cond["budget"], "status": r.get("status"), "expect": case["expect"],
           "gold_kinds": case["gold_kinds"], "steps": len(r.get("steps") or []),
           "model_steps": (r.get("sources") or []).count("model"),
           "rule_steps": (r.get("sources") or []).count("rule"), "calls_used": r.get("calls_used"),
           "elapsed_s": round(dt, 3), "dialogs": len(tools.dialogs), "error": err}
    rec.update(score(case, task, r))
    rec["t1"] = t1_counts(task)
    rec["t1_raw"] = t1_from_calls(calls)
    full = {"reply": r, "task": task, "traceback": tb, "calls": calls, "dialogs": tools.dialogs, "previews": svc.previews,
            "routes": {k: {"stats": v["stats"], "route_id": v["route_id"]} for k, v in svc.routes.items()}}
    return rec, full


# ---------------- T5 探測（calib） ----------------

def t5_probes(model_factory, out_dir, gw=None):
    res = []
    case = {"id": "T5", "text": "北側巡檢，留 25%，放到首頁"}
    for i in range(3):                      # 告警：第一步之後立刻告警，量到迴圈停在步間的時間
        work = os.path.join(out_dir, "t5", f"alert_{i}")
        os.makedirs(work)
        svc, tools = build_env(work)
        flag = {"on": False, "t_set": None}
        calls = []
        base = model_factory(calls)

        def model(call, base=base, flag=flag):
            txt = base(call)
            if '"kinds"' not in call["messages"][1]["content"] and not flag["on"]:
                flag["on"] = True
                flag["t_set"] = time.monotonic()
            return txt
        c = Controller(tools, model, ledger_cfg={"per_sentence": 12, "per_task": 24},
                       alert_active=lambda flag=flag: flag["on"])
        r = c.request(case["text"])
        t_back = time.monotonic()
        res.append({"probe": "alert_pause", "i": i, "status": r["status"],
                    "pause_latency_s": round(t_back - flag["t_set"], 3) if flag["t_set"] else None,
                    "steps_done": len(r["steps"]), "notes": r["notes"]})
        json.dump({"reply": r, "calls": calls}, open(os.path.join(work, "full.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)
    if gw is not None:                      # 取消：極短期限，量閘道放棄時間；模型是否真的停止仍屬未證實
        for i in range(3):
            t0 = time.monotonic()
            st, body = gw.submit("agent_step", {"messages": [{"role": "user", "content": "請詳細說明無人機巡檢流程" * 20}],
                                                "max_tokens": 512}, harness="m4-v2-t5", deadline_s=0.5)
            res.append({"probe": "cancel_deadline", "i": i, "status": st, "gateway_return_s": round(time.monotonic() - t0, 3),
                        "execution_stopped": "未證實（ADR-0001 H-01：僅以結束自有 Ollama 程序為停止證據）"})
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("calib", "research"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fake", action="store_true", help="只用假模型檢查執行器（不是 live）")
    ap.add_argument("--ollama-port", type=int, default=11555)
    ap.add_argument("--bundle", default="", help="live 必填：來源包目錄（含 SHA256SUMS.txt）")
    ap.add_argument("--consent-hash8", default="", help="live 必填：使用者親打「同意 <hash8>」的 hash8")
    a = ap.parse_args(argv)
    if os.path.exists(a.out):
        raise SystemExit("輸出目錄已存在。依「只跑一次」規則不重跑；要修正請開新目錄。")
    info = {"phase": a.phase, "fake": a.fake, "start": now(), "group_definitions": GROUP_NOTE, "qa_note": QA_TOOL_NOTE,
            "consent_hash8_input": a.consent_hash8 or None}
    if not a.fake:
        if not a.bundle:
            raise SystemExit("live 需要 --bundle")
        vb = verify_bundle(a.bundle, a.consent_hash8)
        info["bundle_verification"] = vb
        if not vb["ok"]:
            os.makedirs(a.out)
            json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            raise SystemExit("來源包核對不通過，未啟動模型（紀錄見 RUN_INFO.json）")
    os.makedirs(a.out)
    cases = json.load(open(CASES, encoding="utf-8"))["cases"]
    proc = None
    gw = None
    sampler = RamSampler()
    info["ram_all_ollama_baseline_kb"] = sampler.sample_all()
    try:
        if a.fake:
            factory = fake_model
        else:
            proc = start_ollama(a.ollama_port, os.path.join(a.out, "ollama_serve.log"))
            info["ollama_pid"] = proc.pid
            check_owner(proc, a.ollama_port)
            up = G.make_upstream("ollama", f"http://127.0.0.1:{a.ollama_port}", MODEL_TAG)
            gw = G.Gateway(up, os.path.join(a.out, "gateway_calls.jsonl"))
            factory = lambda log: gateway_model(gw, log)  # noqa: E731
        sampler.start()
        with open(os.path.join(a.out, "results.jsonl"), "a", encoding="utf-8") as f:
            for cond in CONDITIONS[a.phase]:
                for case in cases:
                    if proc is not None:
                        check_owner(proc, a.ollama_port)
                    work = os.path.join(a.out, "cases", cond["id"], case["id"])
                    os.makedirs(work)
                    rec, full = run_case(case, cond, factory, work)
                    rec["ts"] = now()
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")   # 先寫結果
                    f.flush()
                    json.dump(full, open(os.path.join(work, "full.json"), "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1, default=str)   # 工作目錄與完整回傳保留
        if a.phase == "calib":
            if proc is not None:
                check_owner(proc, a.ollama_port)
            info["t5"] = t5_probes(factory, a.out, gw)
            info["t5_note"] = "取消探測只量到閘道返回；逐次模型停止未證實（H-01：僅整次結束自有 Ollama 程序時有停止證據）"
    finally:
        sampler.stop.set()
        info["ram_all_ollama_peak_kb"] = sampler.peak_all_kb
        if proc is not None:
            info["ollama_stop"] = stop_ollama(proc, a.ollama_port)
        info["end"] = now()
        json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False,
                  indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
