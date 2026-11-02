"""MVP live 冒煙：任務規劃串的三次模型呼叫，各一次（出發前規劃、重規劃、報告）。

經共用 LLM 閘道（契約 v0.3），不送任何飛行資料以外的東西；只在使用者同意後執行一次。
  python3 -m gcs_demo.smoke_mvp_mission OUT.json            # 接閘道，3 次模型呼叫
  python3 -m gcs_demo.smoke_mvp_mission OUT.json --rules-only  # 不接模型，只驗流程
環境變數已設定者優先（見 server.MVP_LLM_DEFAULTS）。結束碼：0 三次皆由模型完成，1 有退回規則，2 流程錯誤。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import server as srv


def _call(llm):
    if not llm:
        return None
    return {k: llm.get(k) for k in ("ok", "error", "latency_s", "backend", "model", "prompt_hash", "raw")}


def run(rules_only=False) -> dict:
    srv.apply_mvp_llm_defaults(rules_only)
    s = srv.SESSION
    s.reset()
    steps = []
    t0 = time.time()

    plan = srv.handle("/api/plan", {})
    pick = plan["pick"]
    steps.append({"step": "plan", "source": pick["source"], "decision": pick.get("decision"),
                  "choice_id": pick["choice_id"], "rule_choice": plan.get("rule_choice"),
                  "reason_zh": pick["reason_zh"], "llm": _call(pick.get("llm"))})
    # 模型回 HOLD 時以規則選擇起飛，只為了走到重規劃與報告
    choice = pick["choice_id"] or plan.get("rule_choice") or plan["candidates"][0]["id"]
    started = srv.handle("/api/start", {"mission_version": plan["mission_version"], "choice_id": choice})
    if "replan" not in started:
        raise RuntimeError("起飛後沒有觸發重規劃：" + json.dumps(started.get("reason_zh") or started.get("state"),
                                                       ensure_ascii=False))
    r = started["replan"]
    rp = r["pick"]
    steps.append({"step": "replan", "source": rp["source"], "decision": rp.get("decision"),
                  "choice_id": rp["choice_id"], "rule_choice": r.get("rule_choice"),
                  "reason_zh": rp["reason_zh"], "llm": _call(rp.get("llm"))})
    feasible = [c["id"] for c in r["candidates"] if c["feasible"]]
    rchoice = rp["choice_id"] if rp["choice_id"] in feasible else (r.get("rule_choice") or feasible[0])
    done = srv.handle("/api/continue", {"mission_version": r["mission_version"], "choice_id": rchoice})
    rep = done["report"]
    steps.append({"step": "report", "source": rep["source"], "summary_zh": rep["summary_zh"],
                  "fallback_reason": rep.get("llm_fallback_reason"), "llm": _call(rep.get("llm"))})

    return {"kind": "mvp_mission_smoke", "rules_only": rules_only,
            "env": {k: os.environ.get(k) for k in srv.MVP_LLM_DEFAULTS},
            "wall_s": round(time.time() - t0, 2), "steps": steps,
            "all_model": all(x["source"] == "llm" for x in steps)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--rules-only", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = run(a.rules_only)
    except Exception as exc:  # 流程錯誤也要留下紀錄
        res = {"kind": "mvp_mission_smoke", "error": f"{type(exc).__name__}: {exc}"}
    with open(a.out, "x", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if "error" in res:
        print(res["error"], file=sys.stderr)
        return 2
    for x in res["steps"]:
        llm = x["llm"] or {}
        print(f"{x['step']}: {x['source']} latency={llm.get('latency_s')} error={llm.get('error')}")
    return 0 if res["all_model"] else 1


if __name__ == "__main__":
    sys.exit(main())
