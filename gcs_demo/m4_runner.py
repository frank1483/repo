"""ADR-0002 M4 執行器：桌面真模型迴圈的校準（G2a）與研究實驗（G2r）。

依「M4 桌面真模型迴圈：實驗計畫 v1」（使用者 2026-11-17 13:17 同意 M4-2、M4-3）。
**真模型只有在 live 同意後才能執行**：兩方對同一份來源包 SHA256 精確同意，使用者親打「同意 <hash8>」。
本檔的 --fake 模式只用固定回覆的假模型，用來檢查執行器本身，不算 live。

規則：每個「案例 × 條件」只跑一次；輸出目錄已存在就拒跑；失敗原樣保留。
啟動器自有專用 Ollama（ADR-0001 H-01）：指定埠已被占用就停下，不沿用既有服務；結束時結束自己開的程序。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
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
CASES = os.path.join(os.path.dirname(__file__), "m4_cases_v1.json")
MODEL_TAG = "gemma4:e2b"
MODEL_MANIFEST_SHA256 = "b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2"
CONDITIONS = {
    "calib": [{"id": "A-s10-b12", "group": "A", "steps": 10, "budget": 12}],
    "research": ([{"id": "B0", "group": "B0", "steps": 10, "budget": 0},
                  {"id": "B1", "group": "B1", "steps": 10, "budget": 1}]
                 + [{"id": f"A-s{s}-b30", "group": "A", "steps": s, "budget": 30} for s in (3, 5, 7, 10, 12, 15)]
                 + [{"id": f"A-s10-b{b}", "group": "A", "steps": 10, "budget": b} for b in (6, 12, 24)]),
}


def now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S 台灣時間")


class Session0:
    def __init__(self):
        self.lock = threading.Lock()
        self.mission = {"name": "M4", "home": {"id": "H", "lat": 24.0, "lon": 121.0}, "cruise_alt_m": 50,
                        "no_fly": [], "limits": {"max_altitude_m": 120}, "targets": []}
        self.wind = Wind()
        self.current_state = None

    def vehicle(self):
        return Vehicle()


def port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_ollama(port, log_path):
    if not port_free(port):
        raise SystemExit(f"埠 {port} 已被占用，依 H-01 停下，不沿用既有服務")
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1")
    lf = open(log_path, "ab")
    p = subprocess.Popen(["ollama", "serve"], env=env, stdout=lf, stderr=lf)
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1).read()
            return p
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    p.terminate()
    raise SystemExit("專用 Ollama 沒有在 30 秒內就緒")


def stop_ollama(p):
    p.terminate()
    try:
        p.wait(timeout=10)
        return {"stopped": True, "exit": p.returncode}
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=10)
        return {"stopped": True, "killed": True, "exit": p.returncode}


class RamSampler(threading.Thread):
    """每 0.5 秒取樣所有 ollama 程序的記憶體總和（tasklist）；含使用者原本開著的 Ollama，報告時另列基準值。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak_kb = 0
        self.stop = threading.Event()

    def sample(self):
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq ollama.exe"],
                                 capture_output=True, text=True, timeout=5).stdout
            tot = 0
            for line in out.splitlines():
                parts = [x.strip('"') for x in line.split('","')]
                if len(parts) >= 5:
                    tot += int(parts[4].replace(",", "").replace(" K", "").strip('"') or 0)
            return tot
        except Exception:  # noqa: BLE001
            return 0

    def run(self):
        while not self.stop.is_set():
            self.peak_kb = max(self.peak_kb, self.sample())
            time.sleep(0.5)


def gateway_model(gw, calls_log):
    """Controller 用的 model(call)：經閘道（優先序 I-06），記錄每次呼叫的延遲與結果。"""
    def model(call):
        content = call["messages"][1]["content"]
        feature = "agent_dir" if '"kinds"' in content else ("agent_resume" if "回覆的意圖" in content else "agent_step")
        t0 = time.monotonic()
        st, body = gw.submit(feature, {"messages": call["messages"], "max_tokens": 64}, harness="m4-v1")
        dt = time.monotonic() - t0
        text = ""
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        calls_log.append({"feature": feature, "status": st, "latency_s": round(dt, 3), "raw": text[:200]})
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
        calls_log.append({"feature": "fake", "status": 200, "latency_s": 0.0, "raw": text[:200]})
        return text
    return model


def run_case(case, cond, model_factory, work):
    root = os.path.join(work, "store")
    cl.init_store(root)
    coord, _ = cl.boot(root)
    sess = Session0()
    feeder = SessionFeeder(sess, coord)
    feeder.poll()
    svc = PreviewService(coord, feeder, os.path.join(work, "ev", "p.jsonl"), boot_epoch=1)
    svc.sessions["m4"] = {"principal": "ui", "last_epoch": 0}
    tools = AgentTools(svc, "ui", "m4")
    calls = []
    model = None if cond["group"] == "B0" else model_factory(calls)
    ledger = {"per_sentence": cond["budget"] if cond["group"] != "B0" else 0, "per_task": max(cond["budget"], 1) * 2}
    c = Controller(tools, model, ledger_cfg=ledger, steps_max=cond["steps"])
    t0 = time.monotonic()
    err = None
    try:
        r = c.request(case["text"])
    except Exception as e:  # noqa: BLE001 - 首敗原樣記錄
        r, err = {}, repr(e)
    dt = time.monotonic() - t0
    kinds = sorted((r.get("directions") or {}).keys())
    gold = sorted(case["gold_kinds"])
    srcs = r.get("sources") or []
    return {"case": case["id"], "cond": cond["id"], "group": cond["group"], "steps_max": cond["steps"],
            "budget": cond["budget"], "status": r.get("status"), "expect": case["expect"],
            "status_match": r.get("status") == case["expect"], "kinds": kinds, "gold_kinds": gold,
            "kinds_match": kinds == gold or (not gold and r.get("status") == "HOLD"),
            "claimed_done_wrong": r.get("status") == "DONE" and case["expect"] != "DONE",
            "steps": len(r.get("steps") or []), "model_steps": srcs.count("model"), "rule_steps": srcs.count("rule"),
            "calls_used": r.get("calls_used"), "elapsed_s": round(dt, 3), "calls": calls,
            "dialogs": len(tools.dialogs), "error": err, "notes": r.get("notes")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("calib", "research"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fake", action="store_true", help="只用假模型檢查執行器（不是 live）")
    ap.add_argument("--ollama-port", type=int, default=11555)
    ap.add_argument("--consent-hash8", default="", help="使用者親打「同意 <hash8>」的 hash8（live 必填，寫入紀錄）")
    a = ap.parse_args(argv)
    if os.path.exists(a.out):
        raise SystemExit("輸出目錄已存在。依「只跑一次」規則不重跑；要修正請開新目錄。")
    if not a.fake and len(a.consent_hash8) != 8:
        raise SystemExit("live 需要使用者親打的 hash8")
    os.makedirs(a.out)
    cases = json.load(open(CASES, encoding="utf-8"))["cases"]
    info = {"phase": a.phase, "fake": a.fake, "start": now(), "consent_hash8": a.consent_hash8 or None,
            "model_tag": None if a.fake else MODEL_TAG, "model_manifest_sha256": None if a.fake else MODEL_MANIFEST_SHA256}
    proc = None
    sampler = RamSampler()
    info["ram_baseline_kb"] = sampler.sample()
    try:
        if a.fake:
            factory = fake_model
        else:
            proc = start_ollama(a.ollama_port, os.path.join(a.out, "ollama_serve.log"))
            up = G.make_upstream("ollama", f"http://127.0.0.1:{a.ollama_port}", MODEL_TAG)
            gw = G.Gateway(up, os.path.join(a.out, "gateway_calls.jsonl"))
            factory = lambda log: gateway_model(gw, log)  # noqa: E731
        sampler.start()
        with open(os.path.join(a.out, "results.jsonl"), "a", encoding="utf-8") as f:
            for cond in CONDITIONS[a.phase]:
                for case in cases:
                    work = tempfile.mkdtemp(prefix="m4_", dir=a.out)
                    rec = run_case(case, cond, factory, work)
                    shutil.rmtree(work, ignore_errors=True)
                    rec["ts"] = now()
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
    finally:
        sampler.stop.set()
        info["ram_peak_kb_all_ollama"] = sampler.peak_kb
        if proc is not None:
            info["ollama_stop"] = stop_ollama(proc)
        info["end"] = now()
        json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
