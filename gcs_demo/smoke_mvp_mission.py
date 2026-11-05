"""MVP live 冒煙：任務規劃串的模型呼叫（出發前規劃、重規劃、報告各一次，加上過程中的告警說明）。

經共用 LLM 閘道（契約 v0.3）；只在使用者同意後執行一次。
  python3 -m gcs_demo.smoke_mvp_mission OUT.json            # 接閘道
  python3 -m gcs_demo.smoke_mvp_mission OUT.json --rules-only  # 不接模型，只驗流程
出發前規劃的模型選擇只記錄；起飛固定用規則選擇（預設情境為 C3，會觸發重規劃），
這樣三個步驟都一定會呼叫到模型。每完成一步就重寫 OUT（出錯時保留已完成的步驟）。
環境變數已設定者優先（見 server.MVP_LLM_DEFAULTS）。
結束碼：0 三步皆由模型完成，1 有退回規則，2 流程錯誤。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import server as srv

ALERT_WAIT_S = 45


def _call(llm):
    if not llm:
        return None
    return {k: llm.get(k) for k in ("ok", "error", "latency_s", "backend", "model", "prompt_hash", "raw")}


def _checker(rep):
    """報告檢核器結果：模型沒回應時檢核器沒有執行（ran=False）。"""
    llm = rep.get("llm") or {}
    ran = bool(llm.get("ok"))
    return {"ran": ran, "passed": rep["source"] == "llm",
            "fallback_reason": rep.get("llm_fallback_reason") or (None if ran or not llm else "model_call_failed")}


def _alerts(alerts):
    return [{"key": a["key"], "title": a["title"], "source": a["source"], "text_zh": a["text_zh"]} for a in alerts]


def run(rules_only=False, save=lambda res: None) -> dict:
    srv.apply_mvp_llm_defaults(rules_only)
    s = srv.SESSION
    s.reset()
    t0 = time.time()
    res = {"kind": "mvp_mission_smoke", "version": 2, "rules_only": rules_only,
           "env": {k: os.environ.get(k) for k in srv.MVP_LLM_DEFAULTS}, "steps": []}
    steps = res["steps"]
    try:
        plan = srv.handle("/api/plan", {})
        pick = plan["pick"]
        fly = plan["rule_choice"]
        steps.append({"step": "plan", "source": pick["source"], "decision": pick.get("decision"),
                      "choice_id": pick["choice_id"], "rule_choice": plan["rule_choice"], "flown": fly,
                      "reason_zh": pick["reason_zh"], "llm": _call(pick.get("llm"))})
        save(res)

        started = srv.handle("/api/start", {"mission_version": plan["mission_version"], "choice_id": fly})
        if started.get("ok") is False:
            raise RuntimeError("起飛被拒：" + started.get("reason_zh", ""))
        if "replan" not in started:
            raise RuntimeError(f"規則選擇 {fly} 起飛後沒有觸發重規劃")
        r = started["replan"]
        rp = r["pick"]
        feasible = [c["id"] for c in r["candidates"] if c["feasible"]]
        rfly = rp["choice_id"] if rp["choice_id"] in feasible else (r.get("rule_choice") or feasible[0])
        steps.append({"step": "replan", "source": rp["source"], "decision": rp.get("decision"),
                      "choice_id": rp["choice_id"], "rule_choice": r.get("rule_choice"), "flown": rfly,
                      "reason_zh": rp["reason_zh"], "llm": _call(rp.get("llm"))})
        save(res)

        done = srv.handle("/api/continue", {"mission_version": r["mission_version"], "choice_id": rfly})
        if done.get("ok") is False:
            raise RuntimeError("重規劃套用被拒：" + done.get("reason_zh", ""))
        rep = done["report"]
        steps.append({"step": "report", "source": rep["source"], "summary_zh": rep["summary_zh"],
                      "suggestions": rep["suggestions"],
                      "checker": _checker(rep),
                      "llm": _call(rep.get("llm"))})
        save(res)

        # 告警說明在背景補上（閘道 /f/alerts/v1）；等它們完成再記錄，不算進結束碼
        deadline = time.time() + ALERT_WAIT_S
        out = srv.handle("/api/alerts", {})
        while out["pending"] and time.time() < deadline:
            time.sleep(1)
            out = srv.handle("/api/alerts", {})
        res["alerts"] = {"pending": out["pending"], "items": _alerts(out["alerts"])}
    except Exception as exc:  # 流程錯誤也要留下已完成的步驟
        res["error"] = f"{type(exc).__name__}: {exc}"
    res["wall_s"] = round(time.time() - t0, 2)
    res["all_model"] = len(steps) == 3 and all(x["source"] == "llm" for x in steps)
    save(res)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--rules-only", action="store_true")
    a = ap.parse_args(argv)
    with open(a.out, "x", encoding="utf-8") as f:
        def save(res):
            f.seek(0)
            f.truncate()
            json.dump(res, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        res = run(a.rules_only, save)
    for x in res["steps"]:
        llm = x["llm"] or {}
        print(f"{x['step']}: {x['source']} latency={llm.get('latency_s')} error={llm.get('error')}")
    for al in res.get("alerts", {}).get("items", []):
        print(f"alert {al['key']}: {al['source']}")
    if "error" in res:
        print(res["error"], file=sys.stderr)
        return 2
    return 0 if res["all_model"] else 1


if __name__ == "__main__":
    sys.exit(main())
