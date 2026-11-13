"""告警 MVP 冒煙測試：3 個情境，確認「規則先發、模型說明非同步後補」。

只準備、不自行執行；要等使用者對測試包打「同意 hash8」後由 MVP live 測試只跑一次。

  # 正式（經共用閘道接 gemma4:e2b，閘道需先啟動）：
  python3 -m gcs_demo.alerts.mvp_smoke out/alerts_mvp_smoke_run1
  # 乾跑（行程內假模型，不連網，只驗腳本本身）：
  python3 -m gcs_demo.alerts.mvp_smoke out/dry --fake

情境
  S1 舊多旋翼引擎陣風情境（sim gusty／ignore）：每則告警的規則文字是否立刻回傳，模型說明幾則成功。
  S2 typed 定翼 P1/P2 編排：電量驟降觸發告警，模型只能寫兩句說明、selected_id 必須是 null。
  S3 版本過期：S2 的告警發出後立刻解除，模型回覆抵達時應被丟棄、不覆蓋畫面。
輸出 summary.json 與 explanations.jsonl；目錄已存在且非空時拒絕執行（每版只跑一次、保留首次結果）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

from . import explain, sim
from . import typed_explain as tx

CAPACITY_POLICY = {"capacity_check": False, "reason": "依 2026-11-08 使用者決定停用容量判斷（P3）"}

RULE_DEADLINE_S = 2.0      # 規格：異常進 GCS 後 2 秒內判斷


class _FakeBackend:
    """--fake 用：照規則文字回覆，固定延遲 0.2 秒；不連網。"""
    name, model = "fake", "fake"

    def complete_json(self, system, user, schema, timeout_s=None):
        time.sleep(0.2)
        facts = json.loads(user)
        if "alert_version" in facts:
            e1 = facts["evidence"][0]
            data = {"alert_version": facts["alert_version"], "selected_id": None,
                    "sentences": [f"{e1['text']}為 {e1['value']}。", "請操作員評估是否提早返航。"],
                    "evidence_ids": [e1["id"]]}
        else:
            c = next((c for c in facts["candidates"] if c.get("feasible") is True), facts["candidates"][0])
            data = {"decision": facts["rule_decision"], "choice_id": c["id"], "reason_zh": "依規則選擇。",
                    "evidence_ids": [facts["evidence"][0]["id"]], "summary_zh": f"{facts['alert']['title']}。"}
        return {"ok": True, "data": data, "raw": json.dumps(data, ensure_ascii=False),
                "latency_s": 0.2, "error": None}


def _count(results):
    src = [r["result"].get("source") for r in results]
    return {"llm": src.count("llm"), "rule_fallback": src.count("rule"),
            "fallback_reasons": sorted({r["result"].get("fallback_reason") for r in results
                                        if r["result"].get("source") == "rule"} - {None})}


def s1_legacy(backend, log):
    ex = tx.LegacyAlertExplainer(backend)
    shown_s = []

    def fn(ev):
        t0 = time.perf_counter()
        r = ex(ev)
        shown_s.append(time.perf_counter() - t0)
        return r

    t0 = time.perf_counter()
    run = sim.run("gusty", "ignore", explain_fn=fn, capacity_check=False)
    sim_s = time.perf_counter() - t0
    ex.close(wait=True)
    got = ex.poll()
    for g in got:
        log.append({"scenario": "S1", **g})
    for d in ex.async_.discarded:          # 過期未套用的回覆也保留，供檢查模型品質
        log.append({"scenario": "S1", "discarded": True, **d})
    return {"events": len(run["events"]), "explained": len(shown_s),
            "rule_shown_max_s": round(max(shown_s, default=0.0), 4),
            "rule_within_deadline": all(s < RULE_DEADLINE_S for s in shown_s),
            "sim_wall_s": round(sim_s, 2), "model_results": len(got),
            "discarded_stale": len(ex.async_.discarded), **_count(got),
            "landed_pct_of_nominal": run["summary"]["landed_true_pct_of_nominal"]}


def _typed_outputs():
    from gcs_demo.test_typed_orchestration import vehicle, measurement, request
    from .typed_mission_feed import TypedMissionSampleFeed
    f = TypedMissionSampleFeed(vehicle(), raise_ticks=2, clear_ticks=2, max_gap_s=30)
    return [f.tick(i, measurement(i, 90 if i < 4 else 0)["mission"],
                   request()["mission"]) for i in range(6)]


def s2_typed(backend, log):
    ex = tx.TypedAlertExplainer(backend)
    shown, shown_s = [], []
    for out in _typed_outputs():
        t0 = time.perf_counter()
        shown += ex.on_output(out)
        shown_s.append(time.perf_counter() - t0)
    ex.close(wait=True)
    got = ex.poll()
    for g in got:
        log.append({"scenario": "S2", **g})
    for d in ex.async_.discarded:          # 過期未套用的回覆也保留，供檢查模型品質
        log.append({"scenario": "S2", "discarded": True, **d})
    return {"alerts_shown": len(shown), "rule_shown_max_s": round(max(shown_s), 4),
            "rule_within_deadline": all(s < RULE_DEADLINE_S for s in shown_s),
            "model_results": len(got), "selected_id_all_null": all(
                g["result"]["text"].get("selected_id") is None for g in got),
            "discarded_stale": len(ex.async_.discarded), **_count(got)}


def s3_stale(backend, log):
    ex = tx.TypedAlertExplainer(backend)
    raised = [e for e in _typed_outputs()[-1]["events"] if e["type"] == "raise"][:1]
    ex.on_output({"events": raised})
    ex.on_output({"events": [dict(raised[0], type="resolve", active=False)]})   # 模型回覆前就解除
    ex.close(wait=True)
    got = ex.poll()
    for d in ex.async_.discarded:
        log.append({"scenario": "S3", "discarded": True, **d})
    return {"raised": len(raised), "applied_after_resolve": len(got),
            "discarded_stale": len(ex.async_.discarded),
            "pass": len(got) == 0 and len(ex.async_.discarded) == len(raised)}


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    out_dir, fake = argv[0], "--fake" in argv
    if os.path.isdir(out_dir) and os.listdir(out_dir):
        print(f"拒絕執行：{out_dir} 已有結果（每版只跑一次，保留首次結果）")
        return 3
    os.makedirs(out_dir, exist_ok=True)
    backend = _FakeBackend() if fake else explain.get_backend()
    log = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary = {"started": started, "backend": getattr(backend, "name", "?"),
               "model": getattr(backend, "model", None), "url": getattr(backend, "url", None),
               "fake": fake, "capacity_policy": dict(CAPACITY_POLICY), "S1_legacy_multirotor": s1_legacy(backend, log),
               "S2_typed_fixed_wing": s2_typed(backend, log), "S3_stale_version": s3_stale(backend, log),
               "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(os.path.join(out_dir, "explanations.jsonl"), "w", encoding="utf-8") as fh:
        for row in log:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    for name in ("summary.json", "explanations.jsonl"):
        with open(os.path.join(out_dir, name), "rb") as fh:
            print(name, hashlib.sha256(fh.read()).hexdigest())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
