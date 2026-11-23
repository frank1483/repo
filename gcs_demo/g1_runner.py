"""ADR-0002 G1 執行器（範圍 B，使用者 2026-11-23 11:51「g1選b」）。

先核對 G1 manifest（RF-08）：manifest 自身雜湊、gate_id、dependencies、每一筆 source 的 sha256 與 bytes、
程式清冊的 commit 必須等於目前 HEAD 且工作樹乾淨、有效配置必須等於 PolicyProfile。任何一項不符 → 寫 RUN_INFO
（result＝NOT_RELEASED、原因清單），**不執行任何測試**，退出碼 2。
全部相符才依 manifest 的 trial_ids 各跑一次 unittest，保存每套輸出與首跑結果雜湊。只跑一次；輸出目錄已存在就停。
用法：python -m gcs_demo.g1_runner --manifest <GateManifest_G1.json> --sha256 <預期 manifest 雜湊> --out <新目錄>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASE = os.path.dirname(os.path.dirname(REPO))        # 研究工作區根（manifest 的 relative_path 以此為基底）


def sha(b):
    return hashlib.sha256(b).hexdigest()


def canonical(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def effective_config():
    """各模組目前生效的測試值（G1 只認 PolicyProfile 已列的鍵）。"""
    from . import agent_controller, commit_layer, coverage, preview_api
    return {"commit_layer": dict(commit_layer.TEST_VALUES), "preview_api": dict(preview_api.TEST_VALUES),
            "agent_controller": dict(agent_controller.TEST_VALUES), "coverage": dict(coverage.DEFAULTS)}


def _git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True).stdout.strip()


def verify(manifest_path, expect_sha, gate_id="ADR-0002:G1"):
    """回傳 (ok, reasons, manifest)。只讀檔，不寫任何東西。"""
    reasons = []
    try:
        raw = open(manifest_path, "rb").read()
        man = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as e:
        return False, [f"manifest_unreadable:{e!r}"[:200]], None
    if sha(raw) != expect_sha:
        reasons.append("manifest_hash_mismatch")
    if canonical(man) != raw:
        reasons.append("manifest_not_canonical")
    if man.get("gate_id") != gate_id:
        reasons.append(f"gate_id_mismatch:{man.get('gate_id')}")
    if man.get("scope", {}).get("platform") != "desktop-windows-pc":
        reasons.append("scope_platform_not_desktop")      # 校準／研究或裝置範圍不得由本執行器開啟
    by = {}
    for s in man.get("sources", []):
        p = os.path.normpath(os.path.join(BASE, s["relative_path"]))
        if not p.startswith(os.path.normpath(BASE) + os.sep):
            reasons.append(f"path_outside_package:{s['relative_path']}")
            continue
        try:
            b = open(p, "rb").read()
        except OSError:
            reasons.append(f"source_missing:{s['relative_path']}")
            continue
        if sha(b) != s["sha256"] or len(b) != s["bytes"]:
            reasons.append(f"source_hash_mismatch:{s['relative_path']}")
        by[s["role"]] = by.get(s["role"], []) + [(s, b)]
    for dep in man.get("dependencies", []):
        res = [b for s, b in by.get("dependency_result", []) if sha(b) == dep.get("result_sha256")]
        if not res:
            reasons.append(f"dependency_unverified:{dep.get('gate_id')}")
            continue
        try:
            r = json.loads(res[0].decode("utf-8"))
            if r.get("gate_id") != dep.get("gate_id"):
                reasons.append(f"dependency_gate_mismatch:{dep.get('gate_id')}")
        except ValueError:
            reasons.append("dependency_result_unparsable")
    inv = by.get("code_inventory", [])
    if len(inv) != 1:
        reasons.append("code_inventory_missing")
    else:
        ci = json.loads(inv[0][1].decode("utf-8"))
        head = _git("rev-parse", "HEAD")
        if ci.get("commit") != head:
            reasons.append(f"commit_mismatch:{head[:7]}")
        if _git("status", "--porcelain"):
            reasons.append("worktree_dirty")
        for e in ci.get("entries", []):
            blob = subprocess.run(["git", "-C", REPO, "show", f"{ci.get('commit')}:{e['path']}"],
                                  capture_output=True).stdout
            if sha(blob) != e["sha256"]:
                reasons.append(f"blob_mismatch:{e['path']}")
    pol = by.get("policy_profile", [])
    if len(pol) != 1:
        reasons.append("policy_profile_missing")
    else:
        pp = json.loads(pol[0][1].decode("utf-8"))
        eff = effective_config()
        for k in pp.get("bound_effective_config", []):
            mod, key = k["module"], k["key"]
            if eff.get(mod, {}).get(key) != k["value"]:
                reasons.append(f"config_mismatch:{mod}.{key}")
    return not reasons, reasons, man


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if os.path.exists(a.out):
        raise SystemExit("輸出目錄已存在。依「只跑一次」規則不重跑；要修正請開新目錄。")
    os.makedirs(a.out)
    info = {"start": time.strftime("%Y-%m-%d %H:%M:%S") + " 台灣時間", "manifest": os.path.abspath(a.manifest),
            "manifest_sha256": a.sha256, "commit": _git("rev-parse", "HEAD")}
    ok, reasons, man = verify(a.manifest, a.sha256)
    info["verify"] = {"ok": ok, "reasons": reasons}
    if not ok:
        info.update(result="NOT_RELEASED", stop_reason="manifest_verification_failed", end=time.strftime("%Y-%m-%d %H:%M:%S"))
        json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("NOT_RELEASED", reasons[:5])
        return 2
    info["effective_config"] = effective_config()
    results = {}
    for t in man["scope"]["trial_ids"]:
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, "-m", "unittest", "-v", t], cwd=REPO, capture_output=True, text=True)
        out = p.stdout + p.stderr
        with open(os.path.join(a.out, f"{t}.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(out)
        results[t] = {"exit": p.returncode, "seconds": round(time.monotonic() - t0, 3),
                      "output_sha256": sha(out.encode("utf-8"))}
    info["results"] = results
    info["result"] = "PASS" if all(r["exit"] == 0 for r in results.values()) else "FAIL"
    info["first_run_result_sha256"] = sha(canonical(results))
    info["end"] = time.strftime("%Y-%m-%d %H:%M:%S") + " 台灣時間"
    json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(info["result"], info["first_run_result_sha256"])
    return 0 if info["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
